"""
载入虚构培训数据：机场/航司/航班/舱位/运价/规则版本/税项。

数据刻意覆盖三类教学案例：
  A. CHEAP-SPLIT  单段便宜但 end-on-end 组合被禁止
  B. CROSS-MIDNIGHT 转机跨本地日期，命中 date_change_count 规则
  C. CABIN-CLOSED 某段舱位不可用
另外含停留/最短最长停留/周六过夜/改签与规则版本演进示例。
"""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction

from pricing.models import (
    Airline, Airport, CabinInventory, Fare, FareRouteLeg, Flight, Rule,
    RuleVersion, TaxRule,
)

AIRPORTS = [
    ('PEK', '北京首都', '北京', 'Asia/Shanghai'),
    ('PKX', '北京大兴', '北京', 'Asia/Shanghai'),
    ('XIY', '西安咸阳', '西安', 'Asia/Shanghai'),
    ('KWL', '桂林两江', '桂林', 'Asia/Shanghai'),
    ('CAN', '广州白云', '广州', 'Asia/Shanghai'),
    ('URC', '乌鲁木齐地窝堡', '乌鲁木齐', 'Asia/Urumqi'),
]


def utc(local_str, tzname):
    return datetime.strptime(local_str, '%Y-%m-%d %H:%M').replace(
        tzinfo=ZoneInfo(tzname)).astimezone(ZoneInfo('UTC'))


class Command(BaseCommand):
    help = '载入虚构航班与运价规则培训数据'

    @transaction.atomic
    def handle(self, *args, **opts):
        from pricing.models import (
            ChangeQuote, Coupon, Quote, QuoteComponent, QuoteTax,
            RuleHit, TrainingTicket,
        )
        ChangeQuote.objects.all().delete()
        Coupon.objects.all().delete()
        TrainingTicket.objects.all().delete()
        QuoteComponent.objects.all().delete()
        QuoteTax.objects.all().delete()
        RuleHit.objects.all().delete()
        Quote.objects.all().delete()
        Rule.objects.all().delete()
        FareRouteLeg.objects.all().delete()
        Fare.objects.all().delete()
        TaxRule.objects.all().delete()
        CabinInventory.objects.all().delete()
        Flight.objects.all().delete()
        RuleVersion.objects.all().delete()
        Airport.objects.all().delete()
        Airline.objects.all().delete()

        airports = {c: Airport.objects.create(
            code=c, name=n, city=city, timezone=tz)
            for c, n, city, tz in AIRPORTS}
        ca = Airline.objects.create(code='CA', name='演示航空(虚构)')
        mu = Airline.objects.create(code='MU', name='教学航空(虚构)')

        # (carrier, no, origin, dest, local-dep, local-arr), classes dict
        F = []

        def fl(carrier, no, o, d, dep_local, arr_local, cabins):
            F.append((carrier, no, o, d, dep_local, arr_local, cabins))

        # —— 案例 A/B 共用：10/20 PEK-XIY-KWL ——
        fl(ca, 1201, 'PEK', 'XIY', '2026-10-20 08:00', '2026-10-20 10:30',
           {'M': 9, 'Q': 5, 'V': 0})
        # 同日衔接（10:30 到, 11:40 飞；M 充足）
        fl(mu, 2317, 'XIY', 'KWL', '2026-10-20 11:40', '2026-10-20 14:00',
           {'M': 6, 'Q': 8, 'H': 4})
        # 跨本地午夜衔接：23:30 到 XIY，次日 00:50 才飞（<24h 仍是转机，
        # 但在 XIY 本地日历上跨了日期；用于案例 B/C）
        fl(ca, 1211, 'PEK', 'XIY', '2026-10-20 20:40', '2026-10-20 23:30',
           {'M': 7, 'Q': 0, 'H': 2})
        fl(mu, 2319, 'XIY', 'KWL', '2026-10-21 00:50', '2026-10-21 03:20',
           {'M': 7, 'Q': 0, 'H': 3})

        # —— PEK-XIY 超便宜单段运价所挂航班（晚班，更便宜但不能拼） ——
        fl(ca, 1209, 'PEK', 'XIY', '2026-10-20 16:00', '2026-10-20 18:20',
           {'Q': 20, 'V': 12})
        fl(mu, 2325, 'XIY', 'KWL', '2026-10-20 19:30', '2026-10-20 21:50',
           {'Q': 11, 'V': 9})

        # —— 停留案例：PEK-XIY 后停留 26 小时 ——
        fl(mu, 2331, 'XIY', 'KWL', '2026-10-21 12:00', '2026-10-21 14:20',
           {'H': 5, 'Q': 6})

        # —— 往返：10/20 出发, 10/25 回（覆盖周六 10/24 过夜, 停留 5 日） ——
        fl(mu, 2308, 'KWL', 'XIY', '2026-10-25 11:40', '2026-10-25 14:00',
           {'M': 6, 'L': 8})
        fl(ca, 1208, 'XIY', 'PEK', '2026-10-25 18:00', '2026-10-25 20:30',
           {'M': 6, 'L': 9})
        # 早退往返：10/22 回，停留 2 日，且不含周六过夜
        fl(mu, 2306, 'KWL', 'XIY', '2026-10-22 11:40', '2026-10-22 14:00',
           {'M': 6, 'L': 8})
        fl(ca, 1206, 'XIY', 'PEK', '2026-10-22 18:00', '2026-10-22 20:30',
           {'M': 6, 'L': 9})

        # —— 改签目标航班：10/21 早班 PEK-XIY 与 10/21 XIY-KWL ——
        fl(ca, 1203, 'PEK', 'XIY', '2026-10-21 08:00', '2026-10-21 10:30',
           {'M': 4, 'Q': 3})
        fl(mu, 2318, 'XIY', 'KWL', '2026-10-21 11:40', '2026-10-21 14:00',
           {'M': 3, 'H': 2})

        created = {}
        for carrier_obj, no, o, d, dep, arr, cabins in F:
            flight = Flight.objects.create(
                carrier=carrier_obj,
                flight_no=no,
                dep_airport=airports[o], arr_airport=airports[d],
                dep_utc=utc(dep, airports[o].timezone),
                arr_utc=utc(arr, airports[d].timezone))
            created[(carrier_obj.code, no)] = flight
            for bc, seats in cabins.items():
                CabinInventory.objects.create(
                    flight=flight, booking_class=bc,
                    status=(CabinInventory.ClassStatus.OPEN if seats > 0
                            else CabinInventory.ClassStatus.CLOSED),
                    seats=seats)

        # —— 规则版本：v1 与 v2 ——
        v1 = RuleVersion.objects.create(
            version='RULE-2026-Q4-v1',
            published_at=utc('2026-09-01 10:00', 'UTC'),
            effective_from='2026-09-01',
            description='初版培训规则')
        v2 = RuleVersion.objects.create(
            version='RULE-2026-Q4-v2',
            published_at=utc('2026-09-15 10:00', 'UTC'),
            effective_from='2026-09-15',
            description='放宽转机时限；新增跨午夜限制（演示版本演进）')

        def fare(version, code, carrier_code, o, d, price, classes,
                 end_on_end=False, advance=0, change_fee='0.00',
                 ftype='OW'):
            f = Fare.objects.create(
                rule_version=version, fare_code=code,
                carrier=ca if carrier_code == 'CA' else mu,
                origin=airports[o], destination=airports[d],
                fare_type=ftype, price=Decimal(price),
                booking_classes=classes, end_on_end_allowed=end_on_end,
                advance_purchase_days=advance,
                change_fee=Decimal(change_fee))
            return f

        def legs(f, pairs):
            for i, (o, d) in enumerate(pairs):
                FareRouteLeg.objects.create(
                    fare=f, seq=i, origin=airports[o],
                    destination=airports[d])

        def rule(f, version, code, cat, expr, msg, hardcoded=False,
                 scope='INTERNAL'):
            Rule.objects.create(
                fare=f, rule_version=version, code=code, category=cat,
                expression=expr, message_zh=msg, hardcoded=hardcoded,
                scope=scope)

        # 联程运价 PEK-XIY-KWL（M/H），v1 转机 45-720 分钟，允许停留 1 次
        f_connex = fare(v1, 'PEKKWL-MX', 'CA', 'PEK', 'KWL', '680.00',
                        ['M', 'H'], end_on_end=True, advance=7,
                        change_fee='80.00')
        legs(f_connex, [('PEK', 'XIY'), ('XIY', 'KWL')])
        rule(f_connex, v1, 'TRF-01', Rule.Category.TRANSFER,
             '(transfer_count == 0) or (min_transfer_minutes >= 45 '
             'and transfer_count >= 1 and max_transfer_minutes < 1440)',
             '转机衔接（不含停留点）须在 45 分钟以上、24 小时以内')
        rule(f_connex, v1, 'STP-01', Rule.Category.STOPOVER,
             'stopover_count <= 1',
             '本运价最多允许 1 次中途停留')
        rule(f_connex, v1, 'ADV-01', Rule.Category.ADVANCE,
             'advance_purchase_days >= 7',
             '须提前 7 天购票')

        # v2 同一运价：转机放宽至 1500 分钟，但新增跨午夜限制
        f_connex2 = fare(v2, 'PEKKWL-MX', 'CA', 'PEK', 'KWL', '700.00',
                         ['M', 'H'], end_on_end=True, advance=7,
                         change_fee='100.00')
        legs(f_connex2, [('PEK', 'XIY'), ('XIY', 'KWL')])
        rule(f_connex2, v2, 'TRF-02', Rule.Category.TRANSFER,
             '(transfer_count == 0) or (transfer_count >= 1 and '
             'min_transfer_minutes >= 45 and max_transfer_minutes < 1500)',
             'v2：转机衔接（不含停留点）须在 45 分钟以上、25 小时以内')
        rule(f_connex2, v2, 'STP-01', Rule.Category.STOPOVER,
             'stopover_count <= 1', 'v2：最多允许 1 次中途停留')
        rule(f_connex2, v2, 'DATE-01', Rule.Category.DATE_CHANGE,
             'date_change_count == 0',
             'v2 新增：转机段不允许跨过中转地本地日期（不允许红眼中转）',
             scope='BOTH')
        rule(f_connex2, v2, 'ADV-01', Rule.Category.ADVANCE,
             'advance_purchase_days >= 7', '须提前 7 天购票')

        # 单段 PEK-XIY 便宜运价 Q：禁止 end-on-end
        f_cheap_p = fare(v2, 'PEKXIY-Q', 'CA', 'PEK', 'XIY', '300.00',
                         ['Q'], end_on_end=False, advance=3,
                         change_fee='150.00')
        legs(f_cheap_p, [('PEK', 'XIY')])
        rule(f_cheap_p, v2, 'CLS-Q', Rule.Category.BOOKING_CLASS,
             "booking_class in ['Q', 'V']", '仅适用 Q/V 舱')
        rule(f_cheap_p, v2, 'ADV-02', Rule.Category.ADVANCE,
             'advance_purchase_days >= 3', '须提前 3 天购票')

        # 单段 XIY-KWL 运价 Q：允许 end-on-end，但另一端禁止 => 整体仍拼不起来
        f_cheap_x = fare(v2, 'XIYKWL-Q', 'MU', 'XIY', 'KWL', '320.00',
                         ['Q'], end_on_end=True, advance=3,
                         change_fee='60.00')
        legs(f_cheap_x, [('XIY', 'KWL')])
        rule(f_cheap_x, v2, 'CLS-Q2', Rule.Category.BOOKING_CLASS,
             "booking_class in ['Q']", '仅适用 Q 舱')

        # 可正常拼的 PEK-XIY 单段 M（用于对比：能拼但更贵）
        f_p_m = fare(v2, 'PEKXIY-M', 'CA', 'PEK', 'XIY', '420.00',
                     ['M'], end_on_end=True, advance=5, change_fee='80.00')
        legs(f_p_m, [('PEK', 'XIY')])
        rule(f_p_m, v2, 'ADV-03', Rule.Category.ADVANCE,
             'advance_purchase_days >= 5', '须提前 5 天购票')
        rule(f_p_m, v2, 'DATE-CC', Rule.Category.DATE_CHANGE,
             'date_change_count == 0',
             '组件间衔接也不允许跨过中转地本地日期（红眼中转限制）',
             scope='BOTH')

        f_x_m = fare(v2, 'XIYKWL-M', 'MU', 'XIY', 'KWL', '360.00',
                     ['M', 'H'], end_on_end=True, advance=5,
                     change_fee='60.00')
        legs(f_x_m, [('XIY', 'KWL')])
        rule(f_x_m, v2, 'ADV-04', Rule.Category.ADVANCE,
             'advance_purchase_days >= 5', '须提前 5 天购票')

        # 往返运价（M/L）：最短 3 日、最长 14 日、含周六过夜
        f_rt = fare(v2, 'PEKKWL-RT', 'CA', 'PEK', 'KWL', '1180.00',
                    ['M', 'L'], end_on_end=False, advance=10,
                    change_fee='200.00', ftype='RT')
        legs(f_rt, [('PEK', 'XIY'), ('XIY', 'KWL'),
                    ('KWL', 'XIY'), ('XIY', 'PEK')])  # noqa
        rule(f_rt, v2, 'TRF-RT', Rule.Category.TRANSFER,
             '(transfer_count == 0) or (min_transfer_minutes >= 45 '
             'and transfer_count >= 1 and max_transfer_minutes < 1440)',
             '往返各转机点（不含停留点）45 分钟-24 小时')
        rule(f_rt, v2, 'MINS-01', Rule.Category.MIN_STAY,
             'stay_days >= 3', '折返点最短停留 3 天（按本地日历）')
        rule(f_rt, v2, 'MAXS-01', Rule.Category.MAX_STAY,
             'stay_days <= 14', '折返点最长停留 14 天（按本地日历）')
        rule(f_rt, v2, 'SUN-01', Rule.Category.STOPOVER,
             'has_saturday_night == true', '须含一个周六过夜')
        rule(f_rt, v2, 'ADV-RT', Rule.Category.ADVANCE,
             'advance_purchase_days >= 10', '往返须提前 10 天购票')

        # 税项：分列
        TaxRule.objects.create(
            code='CN-CN', name='民航发展基金(虚构)',
            kind=TaxRule.Kind.FIXED_PER_SEGMENT, amount=Decimal('50.00'))
        TaxRule.objects.create(
            code='CN-YQ', name='燃油附加费(虚构)',
            kind=TaxRule.Kind.FIXED_PER_COMPONENT, amount=Decimal('30.00'))
        TaxRule.objects.create(
            code='VAT-EX', name='增值税价外(虚构 1.5%)',
            kind=TaxRule.Kind.PERCENT_OF_BASE, amount=Decimal('1.50'))

        self.stdout.write(self.style.SUCCESS(
            f'已载入 {Flight.objects.count()} 个航班、'
            f'{Fare.objects.count()} 个运价、{Rule.objects.count()} 条规则、'
            f'{TaxRule.objects.count()} 项税'))
