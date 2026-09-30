"""
多航段运价组合核算引擎（培训沙箱，全程 Decimal，无真实订座/出票）。

核心教学点：
1. 票价来自"运价组件(fare component)"，一个组件可覆盖多段，不是逐段价格相加。
2. 引擎枚举把 N 段切成连续块的全部 2^(N-1) 种组合方式，逐块匹配运价、逐条
   执行规则表达式，中选与淘汰全程记录（RuleHit），可回溯到规则版本。
3. 转机/停留/跨日均按 UTC 真实时差 + 机场本地日历双重判定。
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from itertools import product

from django.db import transaction

from ..models import (
    CabinInventory, Fare, Flight, Quote, QuoteComponent, QuoteTax, Rule,
    RuleHit, RuleVersion, TaxRule,
)
from .rules_expr import evaluate, RuleContextError, RuleSyntaxError
from . import timeutils

TWO_PLACES = Decimal('0.01')

# 规则上下文里暴露给表达式的变量（白名单）
CONTEXT_KEYS = [
    'segment_count', 'layover_minutes', 'min_layover_minutes',
    'max_layover_minutes', 'stopover_count', 'transfer_count',
    'date_change_count', 'advance_purchase_days', 'stay_days',
    'has_saturday_night', 'booking_class', 'all_booking_classes',
    'component_count', 'other_components_exist',
]


def money(value) -> Decimal:
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class Segment:
    idx: int
    flight: object
    booking_class: str
    cabin: object = None
    available: bool = False


@dataclass
class Transit:
    """两段之间在中转机场的衔接观察结果。"""
    airport: object
    minutes: int
    is_stopover: bool
    date_changed_local: bool


@dataclass
class BlockEval:
    partition: tuple          # (1,2) 这种块大小序列
    start: int
    length: int
    fare: Fare
    rule_results: list = field(default_factory=list)  # list[(rule, passed, ctx, msg)]
    available_ok: bool = True
    availability_detail: list = field(default_factory=list)
    passed: bool = True

    @property
    def seg_indexes(self):
        return list(range(self.start, self.start + self.length))

    @property
    def partition_key(self):
        return '|'.join(str(x) for x in self.partition)


def _build_itinerary(flight_ids, booking_classes):
    segments, transits, errors = [], [], []
    flights = list(Flight.objects
                   .select_related('dep_airport', 'arr_airport', 'carrier')
                   .filter(pk__in=flight_ids))
    by_id = {f.pk: f for f in flights}
    flights = [by_id[i] for i in flight_ids]

    for i, fl in enumerate(flights):
        bc = booking_classes[i]
        cabin = (CabinInventory.objects.filter(flight=fl, booking_class=bc)
                 .first())
        available = bool(cabin and cabin.available)
        segments.append(Segment(i, fl, bc, cabin, available))

    for i in range(len(flights) - 1):
        a, b = flights[i], flights[i + 1]
        if a.arr_airport_id != b.dep_airport_id:
            errors.append(f'段{i+1}到达 {a.arr_airport_id} 与段{i+2}出发 '
                          f'{b.dep_airport_id} 不连续，无法构成联程')
            continue
        mins = timeutils.layover_minutes(a.arr_utc, b.dep_utc)
        if mins < 0:
            errors.append(f'段{i+2}出发早于段{i+1}到达，行程时间倒置')
        transits.append(Transit(
            airport=a.arr_airport,
            minutes=mins,
            is_stopover=timeutils.is_stopover(a.arr_utc, b.dep_utc),
            date_changed_local=timeutils.local_date_changed(
                a.arr_utc, b.dep_utc, a.arr_airport),
        ))
    return flights, segments, transits, errors


def _partitions(n):
    """把 n 段切成连续块的全部切法。n=3 -> (3,) (1,2) (2,1) (1,1,1)。"""
    if n == 0:
        return []
    cuts = product([0, 1], repeat=n - 1) if n > 1 else [()]
    result = []
    for choice in cuts:
        sizes, cur = [], 1
        for c in choice:
            if c:
                sizes.append(cur)
                cur = 1
            else:
                cur += 1
        sizes.append(cur)
        result.append(tuple(sizes))
    return result


def _fare_matches_block(fare, flights, start, length, classes):
    """
    运价路由腿必须与块内城市对序列逐段一致，且每段舱位在运价适用列表内。
    路径完全由 FareRouteLeg 定义 —— 往返运价的 fare.destination 是折返点，
    不能拿它去和最后一段的实际到达地（回到出发地）比较。
    """
    legs = list(fare.route_legs.order_by('seq'))
    if len(legs) != length:
        return False
    for k, leg in enumerate(legs):
        fl = flights[start + k]
        if leg.origin_id != fl.dep_airport_id or \
                leg.destination_id != fl.arr_airport_id:
            return False
        if classes[start + k] not in (fare.booking_classes or []):
            return False
    if fare.origin_id != flights[start].dep_airport_id:
        return False
    return True


def _component_context(segments, transits, start, length,
                       advance_days, component_count):
    """组装规则表达式的取值现场（只暴露 CONTEXT_KEYS 中的白名单名字）。"""
    end = start + length
    internal = transits[start:end - 1]
    classes = [s.booking_class for s in segments[start:end]]
    layovers = [t.minutes for t in internal]
    transfer_mins = [t.minutes for t in internal if not t.is_stopover]
    ctx = {
        'segment_count': length,
        'layover_minutes': layovers[0] if len(layovers) == 1 else (
            min(layovers) if layovers else 0),
        'min_layover_minutes': min(layovers) if layovers else 0,
        'max_layover_minutes': max(layovers) if layovers else 0,
        'min_transfer_minutes': min(transfer_mins) if transfer_mins else 0,
        'max_transfer_minutes': max(transfer_mins) if transfer_mins else 0,
        'stopover_count': sum(1 for t in internal if t.is_stopover),
        'transfer_count': len(transfer_mins),
        # 只统计"转机点"上的跨本地日期；停留跨日不算红眼中转
        'date_change_count': sum(
            1 for t in internal
            if t.date_changed_local and not t.is_stopover),
        'advance_purchase_days': advance_days,
        'stay_days': 0,
        'has_saturday_night': False,
        'booking_class': classes[0] if len(set(classes)) == 1 else classes[0],
        'all_booking_classes': classes,
        'component_count': component_count,
        'other_components_exist': component_count > 1,
    }
    # 往返运价的停留日 / 周六过夜：块长度为偶数时，前半去程、后半回程，
    # 折返点是去程最后一段的到达地（也是回程第一段的出发地）。
    if length >= 4 and length % 2 == 0:
        half = length // 2
        dep0 = segments[start].flight.dep_utc
        ret = segments[start + half].flight.dep_utc
        origin_ap = segments[start].flight.dep_airport
        turn_ap = segments[start + half - 1].flight.arr_airport
        ctx['stay_days'] = timeutils.calendar_stay_days(
            dep0, origin_ap, ret, turn_ap)
        ctx['has_saturday_night'] = timeutils.saturday_night(
            dep0, origin_ap, ret, turn_ap)
    return ctx


def _evaluate_block(fare, segments, transits, start, length, partition,
                    advance_days, component_count, hits_sink, version_tag):
    """对一块执行：舱位硬检查 + 每条表达式规则。结果写入 hits_sink。"""
    be = BlockEval(partition=partition, start=start, length=length, fare=fare)

    # 硬规则 1：舱位可用性（系统判定，表达式无法绕过）
    for s in segments[start:start + length]:
        detail = {
            'segment': s.idx + 1, 'flight': str(s.flight),
            'booking_class': s.booking_class,
            'status': s.cabin.status if s.cabin else 'NO_RECORD',
            'seats': s.cabin.seats if s.cabin else 0,
        }
        be.availability_detail.append(detail)
        ok = s.available
        hits_sink.append(dict(
            component_seq=start, segment_indexes=be.seg_indexes,
            fare_code=fare.fare_code, partition_key=be.partition_key,
            rule_code='HARD-AVAILABILITY',
            rule_category=Rule.Category.AVAILABILITY,
            result=RuleHit.Result.PASS if ok else RuleHit.Result.FAIL,
            message=('舱位可售' if ok else
                     f'段{s.idx+1} {s.flight} 舱位 {s.booking_class} 不可用'
                     f'（{detail["status"]}, 余座 {detail["seats"]}）'),
            expression='', context=detail, rule_version=version_tag))
        if not ok:
            be.available_ok = False
            be.passed = False

    # 表达式规则（scope=BOUNDARY 的规则留到组件拼接时对衔接点求值）
    ctx = _component_context(segments, transits, start, length,
                             advance_days, component_count)
    for rule in fare.rules.filter(active=True).order_by('code'):
        if rule.hardcoded or rule.scope == Rule.RuleScope.BOUNDARY:
            continue
        passed, err = None, ''
        try:
            passed = evaluate(rule.expression, ctx)
        except (RuleSyntaxError, RuleContextError) as exc:
            err = str(exc)
            passed = False
        ok = bool(passed)
        hits_sink.append(dict(
            component_seq=start, segment_indexes=be.seg_indexes,
            fare_code=fare.fare_code, partition_key=be.partition_key,
            rule_code=rule.code, rule_category=rule.category,
            result=RuleHit.Result.PASS if ok else RuleHit.Result.FAIL,
            message=rule.message_zh + (f' [表达式错误: {err}]' if err else ''),
            expression=rule.expression, context=ctx,
            rule_version=version_tag))
        if not ok:
            be.passed = False
        be.rule_results.append((rule, ok, ctx))
    return be


def _compute_taxes(component_totals, seg_counts):
    """税项分别核算：返回 [(component_seq, tax, amount), ...] 与每组件税额。"""
    rows, per_component = [], {}
    taxes = list(TaxRule.objects.filter(active=True))
    for seq, base in component_totals:
        n_seg = seg_counts[seq]
        per_component[seq] = Decimal('0.00')
        for tax in taxes:
            if tax.kind == TaxRule.Kind.FIXED_PER_COMPONENT:
                amount = money(tax.amount)
            elif tax.kind == TaxRule.Kind.FIXED_PER_SEGMENT:
                amount = money(tax.amount * n_seg)
            else:  # PERCENT_OF_BASE
                amount = money(base * tax.amount / Decimal('100'))
            rows.append((seq, tax, amount))
            per_component[seq] += amount
        per_component[seq] = money(per_component[seq])
    return rows, per_component


@transaction.atomic
def price_itinerary(flight_ids, booking_classes, booking_date=None,
                    scenario='', purpose=Quote.Purpose.PRICE, persist=True,
                    rule_version_tag=None):
    """
    试算主入口。返回 (quote_or_none, detail_dict)。

    一次试算固定使用一个 RuleVersion：只有该版本下的运价与规则参与判断，
    结果因此可精确追溯到规则版本。rule_version_tag=None 时取最新生效版本。
    """
    if rule_version_tag:
        version = RuleVersion.objects.filter(
            version=rule_version_tag, active=True).first()
    else:
        version = RuleVersion.objects.filter(active=True).order_by(
            '-published_at').first()
    version_tag = version.version if version else 'NONE'

    flights, segments, transits, errors = _build_itinerary(
        flight_ids, booking_classes)

    quote = None
    detail = {
        'segments': [], 'transits': [], 'candidates': [],
        'chosen': None, 'failure_reason': '', 'errors': errors,
        'rule_version': version_tag,
    }
    for s in segments:
        fl = s.flight
        detail['segments'].append({
            'idx': s.idx, 'flight': str(fl),
            'carrier': fl.carrier_id,
            'from': fl.dep_airport_id, 'to': fl.arr_airport_id,
            'dep_utc': fl.dep_utc.isoformat(),
            'arr_utc': fl.arr_utc.isoformat(),
            'dep_local': timeutils.local_dt(
                fl.dep_utc, fl.dep_airport).strftime('%Y-%m-%d %H:%M %Z'),
            'arr_local': timeutils.local_dt(
                fl.arr_utc, fl.arr_airport).strftime('%Y-%m-%d %H:%M %Z'),
            'booking_class': s.booking_class, 'available': s.available,
        })
    for i, t in enumerate(transits):
        detail['transits'].append({
            'after_segment': i + 1, 'airport': t.airport.code,
            'minutes': t.minutes,
            'kind': '停留' if t.is_stopover else '转机',
            'date_changed_local': t.date_changed_local,
        })

    if errors:
        detail['failure_reason'] = '；'.join(errors)
        if persist:
            quote = _save_quote(detail, None, [], [], scenario, purpose,
                                version, flight_ids, booking_classes,
                                booking_date)
        return quote, detail

    if booking_date is None:
        booking_date = segments[0].flight.dep_utc.date()
    if isinstance(booking_date, str):
        booking_date = datetime.strptime(booking_date, '%Y-%m-%d').date()
    advance_days = (segments[0].flight.dep_utc.date() - booking_date).days

    n = len(segments)
    all_hits = []          # 暂存命中轨迹
    valid_candidates = []  # (total, partition, [BlockEval])

    for partition in _partitions(n):
        start, blocks, block_failed = 0, [], False
        component_no = 0
        for size in partition:
            end = start + size
            # 找所有覆盖这一块的候选运价（含不满足 end-on-end 的，稍后统一判）
            fares = [f for f in Fare.objects.filter(
                active=True, rule_version=version).prefetch_related(
                'rules', 'route_legs')
                if _fare_matches_block(f, flights, start, size, booking_classes)]
            block_options = []
            for fare in fares:
                be = _evaluate_block(
                    fare, segments, transits, start, size, partition,
                    advance_days, len(partition), all_hits, version_tag)
                block_options.append(be)
            if not block_options:
                all_hits.append(dict(
                    component_seq=start,
                    segment_indexes=list(range(start, end)),
                    fare_code='', partition_key='|'.join(map(str, partition)),
                    rule_code='HARD-ROUTING',
                    rule_category=Rule.Category.ITINERARY,
                    result=RuleHit.Result.FAIL,
                    message=f'第{start+1}-{end}段没有任何运价路由覆盖此城市对序列与舱位',
                    expression='', context={}, rule_version=version_tag))
                block_failed = True
                break
            good = [b for b in block_options if b.passed]
            if not good:
                block_failed = True
                # 仍然保留所有块轨迹
            blocks.append(block_options)
            start = end
            component_no += 1

        if block_failed:
            detail['candidates'].append({
                'partition': list(partition), 'passed': False,
                'reason': '存在块无可用运价或规则未通过',
            })
            continue

        # 每块取"通过的候选"做笛卡尔组合；联程组合限制：
        # 多组件时任一运价 end_on_end_allowed=False => 整个切分淘汰
        good_per_block = [[b for b in opts if b.passed] for opts in blocks]
        for combo in product(*good_per_block):
            combo_ok = True
            combo_msg = ''
            if len(combo) > 1:
                for be in combo:
                    if not be.fare.end_on_end_allowed:
                        combo_ok = False
                        combo_msg = (f'运价 {be.fare.fare_code} 不允许 end-on-end '
                                     f'联程组合，不能与其他运价拼接')
                        all_hits.append(dict(
                            component_seq=be.start,
                            segment_indexes=be.seg_indexes,
                            fare_code=be.fare.fare_code,
                            partition_key=be.partition_key,
                            rule_code='COMB-ENDONEND',
                            rule_category=Rule.Category.COMBINATION,
                            result=RuleHit.Result.FAIL,
                            message=combo_msg,
                            expression='other_components_exist == false',
                            context={'other_components_exist': True},
                            rule_version=version_tag))
            else:
                all_hits.append(dict(
                    component_seq=combo[0].start,
                    segment_indexes=combo[0].seg_indexes,
                    fare_code=combo[0].fare.fare_code,
                    partition_key=combo[0].partition_key,
                    rule_code='COMB-ENDONEND',
                    rule_category=Rule.Category.COMBINATION,
                    result=RuleHit.Result.PASS,
                    message='单一运价组件覆盖全部航段，无联程组合限制问题',
                    expression='', context={'other_components_exist': False},
                    rule_version=version_tag))

            # 跨组件规则：对组件之间的每个衔接点（boundary transit）求值。
            # 例如红眼中转限制 —— 它约束的是"前一个运价组件结束、下一个开始"
            # 的那个转机点，组件内部上下文里看不到它。
            if combo_ok and len(combo) > 1:
                boundary = combo[0].start + combo[0].length
                for be in combo:
                    boundary_t = transits[boundary - 1]
                    cc_rules = be.fare.rules.filter(active=True).filter(
                        scope__in=[Rule.RuleScope.BOUNDARY,
                                   Rule.RuleScope.BOTH])
                    for r in cc_rules:
                        bctx = {
                            'segment_count': n,
                            'layover_minutes': boundary_t.minutes,
                            'min_layover_minutes': boundary_t.minutes,
                            'max_layover_minutes': boundary_t.minutes,
                            'stopover_count': 1 if boundary_t.is_stopover else 0,
                            'transfer_count': 0 if boundary_t.is_stopover else 1,
                            'date_change_count': (
                                1 if boundary_t.date_changed_local
                                and not boundary_t.is_stopover else 0),
                            'advance_purchase_days': advance_days,
                            'stay_days': 0,
                            'has_saturday_night': False,
                            'booking_class': segments[boundary].booking_class,
                            'all_booking_classes': [s.booking_class for s in segments],
                            'component_count': len(combo),
                            'other_components_exist': True,
                        }
                        try:
                            ok = evaluate(r.expression, bctx)
                            err = ''
                        except (RuleSyntaxError, RuleContextError) as exc:
                            ok, err = False, str(exc)
                        all_hits.append(dict(
                            component_seq=be.start,
                            segment_indexes=be.seg_indexes,
                            fare_code=be.fare.fare_code,
                            partition_key=be.partition_key,
                            rule_code=r.code, rule_category=r.category,
                            result=RuleHit.Result.PASS if ok else RuleHit.Result.FAIL,
                            message=r.message_zh + (f' [表达式错误: {err}]' if err else ''),
                            expression=r.expression, context=bctx,
                            rule_version=version_tag))
                        if not ok:
                            combo_ok = False
                            combo_msg = (f'组件间衔接点 {boundary_t.airport.code} '
                                         f'未通过 {r.code}: {r.message_zh}')

            base = money(sum((b.fare.price for b in combo), Decimal('0.00')))
            comp_bases = [(i, b.fare.price) for i, b in enumerate(combo)]
            seg_counts = {i: b.length for i, b in enumerate(combo)}
            tax_rows, tax_per = _compute_taxes(comp_bases, seg_counts)
            tax_total = money(sum((a for _, _, a in tax_rows), Decimal('0.00')))
            total = money(base + tax_total)

            cand = {
                'partition': list(partition),
                'passed': combo_ok,
                'components': [{
                    'seq': i,
                    'fare_code': b.fare.fare_code,
                    'segment_indexes': b.seg_indexes,
                    'base_fare': str(b.fare.price),
                    'tax_total': str(tax_per[i]),
                    'end_on_end_allowed': b.fare.end_on_end_allowed,
                } for i, b in enumerate(combo)],
                'base_fare': str(base),
                'taxes': [{'component_seq': i, 'code': t.code, 'name': t.name,
                           'amount': str(a)} for i, t, a in tax_rows],
                'tax_total': str(tax_total),
                'total': str(total),
                'rejected_reason': combo_msg if not combo_ok else '',
            }
            detail['candidates'].append(cand)
            if combo_ok:
                valid_candidates.append((total, cand, combo, tax_rows, tax_per))

    if not valid_candidates:
        detail['failure_reason'] = ('所有运价组合均被规则淘汰：可能是单段便宜运价'
                                     '不允许联程组合、跨日期变更规则或舱位不可用')
        if persist:
            quote = _save_quote(detail, None, [], [], scenario, purpose,
                                version, flight_ids, booking_classes,
                                booking_date, all_hits)
        return quote, detail

    # 教学口径：选含税总价最低的合法组合
    valid_candidates.sort(key=lambda c: c[0])
    total, cand, combo, tax_rows, tax_per = valid_candidates[0]
    chosen_keys = {(b.partition_key, b.fare.fare_code) for b in combo}
    for h in all_hits:
        h['chosen'] = (h['partition_key'], h['fare_code']) in chosen_keys
    detail['chosen'] = cand
    detail['failure_reason'] = ''

    if persist:
        quote = _save_quote(detail, cand, combo, tax_rows, scenario, purpose,
                            version, flight_ids, booking_classes,
                            booking_date, all_hits)
        detail['quote_id'] = quote.pk
    return quote, detail


def _save_quote(detail, cand, combo, tax_rows, scenario, purpose, version,
                flight_ids, booking_classes, booking_date, hits=None):
    quote = Quote.objects.create(
        purpose=purpose, scenario=scenario,
        status=Quote.Status.OK if cand else Quote.Status.FAILED,
        rule_version=version,
        request_payload={'flight_ids': flight_ids,
                         'booking_classes': booking_classes,
                         'booking_date': str(booking_date) if booking_date else None},
        base_fare=Decimal(cand['base_fare']) if cand else Decimal('0.00'),
        tax_total=Decimal(cand['tax_total']) if cand else Decimal('0.00'),
        total=Decimal(cand['total']) if cand else Decimal('0.00'),
        failure_reason=detail.get('failure_reason', '')[:255],
    )
    if cand:
        for i, b in enumerate(combo):
            QuoteComponent.objects.create(
                quote=quote, seq=i, fare=b.fare,
                segment_indexes=b.seg_indexes, base_fare=b.fare.price,
                tax_total=Decimal(cand['components'][i]['tax_total']))
        for comp_seq, tax, amount in tax_rows:
            QuoteTax.objects.create(quote=quote, component_seq=comp_seq,
                                    tax=tax, amount=amount)
    for h in (hits or []):
        RuleHit.objects.create(quote=quote, **h)
    return quote
