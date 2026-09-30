"""
改签（培训沙箱）。

流程严格按培训顺序：
  1. 先检查剩余票联（Coupon）状态 —— 有 USED / EXCHANGED 票联就不能再改该段；
  2. 对新行程试算（复用定价引擎，规则版本以新试算为准并记录）；
  3. 价差 = 新含税总价 - 原含税总价；手续费按原票运价组件上的 change_fee 合计；
  4. 补收/退还原为模拟数，系统不会生成任何真实购票或退款指令。
"""

from decimal import Decimal

from django.db import transaction

from ..models import (
    ChangeQuote, Coupon, Quote, RuleHit, TrainingTicket,
)
from .pricing import money, price_itinerary


def check_coupons(ticket):
    """返回 (是否允许改, 明细列表)。任何非 OPEN 票联都阻断改签。"""
    rows, allowed = [], True
    for c in ticket.coupons.order_by('seq'):
        ok = c.status == Coupon.Status.OPEN
        allowed = allowed and ok
        rows.append({
            'seq': c.seq,
            'flight': str(c.flight),
            'booking_class': c.booking_class,
            'status': c.status,
            'status_label': Coupon.Status(c.status).label,
            'changeable': ok,
            'reason': '' if ok else f"票联状态为 {c.status}，不可再次换开",
        })
    return allowed, rows


@transaction.atomic
def quote_change(ticket_no, new_flight_ids, new_booking_classes,
                 booking_date=None):
    """改签试算。不产生真实出票/退款，只写沙箱记录。"""
    ticket = TrainingTicket.objects.select_for_update().get(
        ticket_no=ticket_no)

    allowed, coupon_rows = check_coupons(ticket)
    if not allowed:
        cq = ChangeQuote.objects.create(
            ticket=ticket,
            new_quote=Quote.objects.create(
                purpose=Quote.Purpose.CHANGE, status=Quote.Status.FAILED,
                rule_version=ticket.quote.rule_version,
                request_payload={'flight_ids': new_flight_ids,
                                 'booking_classes': new_booking_classes},
                failure_reason='票联状态检查未通过，改签在计价前终止'),
            status=ChangeQuote.Status.BLOCKED,
            coupon_check=coupon_rows,
            original_total=ticket.total, new_total=Decimal('0.00'),
            fare_diff=Decimal('0.00'), change_fee=Decimal('0.00'),
            collect_or_refund=Decimal('0.00'),
            note='存在已使用/已换开票联；改签必须先过票联状态关')
        return cq, None

    # 票联通过后才允许进入计价
    new_quote, detail = price_itinerary(
        new_flight_ids, new_booking_classes, booking_date=booking_date,
        scenario=f'CHANGE:{ticket.ticket_no}', purpose=Quote.Purpose.CHANGE)

    if new_quote.status != Quote.Status.OK:
        cq = ChangeQuote.objects.create(
            ticket=ticket, new_quote=new_quote,
            status=ChangeQuote.Status.BLOCKED, coupon_check=coupon_rows,
            original_total=ticket.total, new_total=Decimal('0.00'),
            fare_diff=Decimal('0.00'), change_fee=Decimal('0.00'),
            collect_or_refund=Decimal('0.00'),
            note='票联状态正常，但新行程无可用运价组合')
        return cq, detail

    # 手续费：原票各运价组件上的 change_fee
    fee = Decimal('0.00')
    for comp in ticket.quote.components.select_related('fare'):
        fee += comp.fare.change_fee
    fee = money(fee)

    diff = money(new_quote.total - ticket.total)
    collect = money(diff + fee)

    cq = ChangeQuote.objects.create(
        ticket=ticket, new_quote=new_quote,
        status=ChangeQuote.Status.OK, coupon_check=coupon_rows,
        original_total=ticket.total, new_total=new_quote.total,
        fare_diff=diff, change_fee=fee, collect_or_refund=collect,
        note='正数=模拟补收，负数=模拟退还；不生成真实支付/退款指令')
    detail['change'] = {
        'coupon_check': coupon_rows,
        'original_total': str(ticket.total),
        'new_total': str(new_quote.total),
        'fare_diff': str(diff), 'change_fee': str(fee),
        'collect_or_refund': str(collect),
        'change_quote_id': cq.pk,
    }
    return cq, detail


@transaction.atomic
def commit_change(change_quote_id):
    """
    培训换开：把旧票联置 EXCHANGED，按新报价生成一张 TRN- 培训票。
    明确声明：只在沙箱数据库内改状态，不向任何订座/出票/支付系统发指令。
    """
    cq = ChangeQuote.objects.select_for_update().get(pk=change_quote_id)
    if cq.status != ChangeQuote.Status.OK:
        raise ValueError('只有可改签(OK)的试算可以执行培训换开')

    cq.ticket.coupons.update(status=Coupon.Status.EXCHANGED)
    cq.ticket.status = TrainingTicket.Status.EXCHANGED
    cq.ticket.save(update_fields=['status'])

    seq = TrainingTicket.objects.count() + 1
    new_ticket = TrainingTicket.objects.create(
        ticket_no=f'TRN-{cq.new_quote_id:05d}-{seq:03d}',
        quote=cq.new_quote, total=cq.new_quote.total,
        status=TrainingTicket.Status.ISSUED)
    for comp in cq.new_quote.components.all():
        fare = comp.fare
        for seg_idx in comp.segment_indexes:
            fl = cq.new_quote.request_payload['flight_ids'][seg_idx]
            bc = cq.new_quote.request_payload['booking_classes'][seg_idx]
            Coupon.objects.create(
                ticket=new_ticket, seq=seg_idx, flight_id=fl, fare=fare,
                booking_class=bc, status=Coupon.Status.OPEN)

    cq.status = ChangeQuote.Status.COMMITTED
    cq.save(update_fields=['status'])
    return new_ticket


@transaction.atomic
def issue_training_ticket(quote_id):
    """从成功试算生成虚构培训票（TRN- 开头），不产生任何真实购票指令。"""
    quote = Quote.objects.get(pk=quote_id)
    if quote.status != Quote.Status.OK:
        raise ValueError('只有试算成功的报价单可以出票(培训)')
    seq = TrainingTicket.objects.count() + 1
    ticket = TrainingTicket.objects.create(
        ticket_no=f'TRN-{quote_id:05d}-{seq:03d}',
        quote=quote, total=quote.total)
    for comp in quote.components.all():
        for seg_idx in comp.segment_indexes:
            Coupon.objects.create(
                ticket=ticket, seq=seg_idx,
                flight_id=quote.request_payload['flight_ids'][seg_idx],
                fare=comp.fare,
                booking_class=quote.request_payload['booking_classes'][seg_idx],
                status=Coupon.Status.OPEN)
    return ticket
