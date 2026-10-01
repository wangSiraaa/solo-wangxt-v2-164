"""灌入虚构培训数据（可重复执行，按业务键 upsert，不产生重复行）。

数据日期固定在 2026-10，保证案例可复现。全部为虚构：航司代号、航班号、
运价和税费均用于教学，与真实订座/出票系统无任何连接。
"""
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand
from zoneinfo import ZoneInfo

from pricing.models import (
    Airport,
    CabinInventory,
    Fare,
    FareRuleVersion,
    Flight,
    Order,
    Rule,
    TaxDefinition,
    TicketCoupon,
)

UTC = ZoneInfo("UTC")

AIRPORTS = [
    ("SHA", "上海虹桥（虚构）", "上海", "Asia/Shanghai"),
    ("PEK", "北京首都（虚构）", "北京", "Asia/Shanghai"),
    ("NRT", "东京成田（虚构）", "东京", "Asia/Tokyo"),
    ("URC", "乌鲁木齐地窝堡（虚构）", "乌鲁木齐", "Asia/Urumqi"),
    ("CAN", "广州白云（虚构）", "广州", "Asia/Shanghai"),
]


def dt(y, mo, d, h, mi, tz="UTC"):
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).astimezone(UTC)


# (carrier, number, dep, arr, dep_local, arr_local)
def _f(*args):
    return args


FLIGHTS = [
    # ---- SHA <-> NRT（跨时区：上海 UTC+8 / 东京 UTC+9）----
    _f("MU", "521", "SHA", "NRT", dt(2026, 10, 5, 9, 0, "Asia/Shanghai"),
       dt(2026, 10, 5, 13, 0, "Asia/Tokyo")),
    _f("MU", "522", "NRT", "SHA", dt(2026, 10, 6, 14, 0, "Asia/Tokyo"),
       dt(2026, 10, 6, 16, 30, "Asia/Shanghai")),
    _f("MU", "524", "NRT", "SHA", dt(2026, 10, 9, 14, 0, "Asia/Tokyo"),
       dt(2026, 10, 9, 16, 30, "Asia/Shanghai")),
    _f("MU", "526", "NRT", "SHA", dt(2026, 10, 24, 18, 0, "Asia/Tokyo"),
       dt(2026, 10, 24, 20, 30, "Asia/Shanghai")),
    # ---- SHA <-> URC（同国跨时区：上海 UTC+8 / 乌鲁木齐 UTC+6）----
    _f("MU", "5601", "SHA", "URC", dt(2026, 10, 5, 23, 0, "Asia/Shanghai"),
       dt(2026, 10, 6, 3, 30, "Asia/Urumqi")),
    _f("MU", "5602", "URC", "SHA", dt(2026, 10, 6, 9, 0, "Asia/Urumqi"),
       dt(2026, 10, 6, 13, 0, "Asia/Shanghai")),
    _f("MU", "5604", "URC", "SHA", dt(2026, 10, 12, 9, 0, "Asia/Urumqi"),
       dt(2026, 10, 12, 13, 0, "Asia/Shanghai")),
    # ---- SHA <-> PEK ----
    _f("MU", "5101", "SHA", "PEK", dt(2026, 10, 5, 8, 0, "Asia/Shanghai"),
       dt(2026, 10, 5, 10, 20, "Asia/Shanghai")),
    _f("MU", "5103", "SHA", "PEK", dt(2026, 10, 8, 8, 0, "Asia/Shanghai"),
       dt(2026, 10, 8, 10, 20, "Asia/Shanghai")),
    _f("MU", "5102", "PEK", "SHA", dt(2026, 10, 5, 18, 0, "Asia/Shanghai"),
       dt(2026, 10, 5, 20, 10, "Asia/Shanghai")),
    _f("MU", "5104", "PEK", "SHA", dt(2026, 10, 8, 18, 0, "Asia/Shanghai"),
       dt(2026, 10, 8, 20, 10, "Asia/Shanghai")),
    _f("MU", "5106", "PEK", "SHA", dt(2026, 10, 12, 12, 0, "Asia/Shanghai"),
       dt(2026, 10, 12, 14, 10, "Asia/Shanghai")),
    # ---- 三角程 SHA->PEK->URC->SHA（全部 MU）----
    _f("MU", "5107", "SHA", "PEK", dt(2026, 10, 5, 7, 30, "Asia/Shanghai"),
       dt(2026, 10, 5, 9, 50, "Asia/Shanghai")),
    _f("MU", "5605", "PEK", "URC", dt(2026, 10, 5, 11, 30, "Asia/Shanghai"),
       dt(2026, 10, 5, 15, 40, "Asia/Urumqi")),
    _f("MU", "5608", "URC", "SHA", dt(2026, 10, 6, 20, 0, "Asia/Urumqi"),
       dt(2026, 10, 7, 0, 5, "Asia/Shanghai")),
    # 改签用的后续航班
    _f("MU", "524B", "NRT", "SHA", dt(2026, 10, 12, 14, 0, "Asia/Tokyo"),
       dt(2026, 10, 12, 16, 30, "Asia/Shanghai")),
]

# 每个航班投放的舱位（rbd, 名称, 座位）。Q 为低价限制舱，J 为商务。
DEFAULT_CABINS = [
    ("Y", "经济舱全价", 20),
    ("B", "经济舱", 15),
    ("Q", "经济舱特价", 6),
    ("J", "商务舱", 4),
]
# 个别航班某舱 0 座，用于“某段舱位不可用”案例。
ZERO_SEATS = {
    ("MU", "5107", "Q"),   # 三角程第一段没有 Q
    ("MU", "526", "Q"),    # 超长停留回程没有 Q
}

# 运价：(carrier, o, d, rbd, code, direction, amount)
FARES = [
    ("MU", "SHA", "NRT", "Y", "YRT", "RT", "3200.00"),
    ("MU", "SHA", "NRT", "Q", "QLEISURE", "RT", "2400.00"),
    ("MU", "SHA", "NRT", "Y", "YOW", "OW", "2100.00"),
    ("MU", "SHA", "NRT", "Q", "QOW", "OW", "1300.00"),
    ("MU", "SHA", "URC", "Y", "YRTU", "RT", "2800.00"),
    ("MU", "SHA", "URC", "Y", "YOWU", "OW", "1800.00"),
    ("MU", "SHA", "PEK", "Y", "YRTP", "RT", "2200.00"),
    ("MU", "SHA", "PEK", "Y", "YOWP", "OW", "1300.00"),
    ("MU", "SHA", "PEK", "Q", "QLOWP", "OW", "450.00"),
    ("MU", "PEK", "SHA", "Y", "YOWP", "OW", "1300.00"),
    ("MU", "PEK", "URC", "Y", "YOWPU", "OW", "1100.00"),
    ("MU", "PEK", "URC", "Q", "QLOWPU", "OW", "380.00"),
    ("MU", "URC", "SHA", "Y", "YOWPU", "OW", "1700.00"),
    ("MU", "URC", "SHA", "Q", "QLOWPU", "OW", "520.00"),
]

TAXES = [
    ("CN", "民航发展基金（虚构）", "经济舱全价", "50.00"),
    ("CN", "民航发展基金（虚构）", "经济舱", "50.00"),
    ("CN", "民航发展基金（虚构）", "经济舱特价", "50.00"),
    ("YQ", "燃油附加（虚构）", "经济舱全价", "120.00"),
    ("YQ", "燃油附加（虚构）", "经济舱", "120.00"),
    ("YQ", "燃油附加（虚构）", "经济舱特价", "90.00"),
    ("YQ", "燃油附加（虚构）", "商务舱", "200.00"),
    ("XT", "国际联运杂费（虚构）", "经济舱全价", "80.00"),
    ("XT", "国际联运杂费（虚构）", "经济舱特价", "60.00"),
]

# 规则版本内容。键为 fare_code:direction:od。
def _rules_v1_yrt():
    return [
        ("ELIGIBILITY", "仅 MU 承运、Y/B 舱", 'same_carrier and component.rbd in ["Y", "B"]', None),
        ("STOPOVERS", "来回程折返点停留按最短/最长停留计，不另计中途停留", "stopovers <= 0", None),
        ("TRANSFERS", "最多 1 次转机", "transfers <= 1", None),
        ("MIN_STAY", "折返点最短停留 3 个当地日历日", "stay_days == None or stay_days >= 3", None),
        ("MAX_STAY", "折返点最长停留 14 个当地日历日", "stay_days == None or stay_days <= 14", None),
        ("COMBINABILITY", "YRT 允许与单程 Y 运价联程组合", "components_count <= 3", None),
        ("CHANGE_FEE", "起飞前 7 天以上改签手续费 300", "days_before_departure >= 7 and same_cabin", "300.00"),
        ("CHANGE_FEE", "7 天内或换舱等改签手续费 800", "days_before_departure < 7 or not same_cabin", "800.00"),
    ]


def _rules_v2_yrt():
    return [
        ("ELIGIBILITY", "仅 MU 承运、Y/B 舱", 'same_carrier and component.rbd in ["Y", "B"]', None),
        ("STOPOVERS", "来回程折返点停留按最短/最长停留计，不另计中途停留", "stopovers <= 0", None),
        ("TRANSFERS", "最多 1 次转机", "transfers <= 1", None),
        ("MIN_STAY", "折返点最短停留 3 个当地日历日", "stay_days == None or stay_days >= 3", None),
        ("MAX_STAY", "折返点最长停留 14 个当地日历日", "stay_days == None or stay_days <= 14", None),
        ("COMBINABILITY", "YRT 允许与单程 Y 运价联程组合", "components_count <= 3", None),
        ("CHANGE_FEE", "v2：起飞前 7 天以上改签手续费 500", "days_before_departure >= 7 and same_cabin", "500.00"),
        ("CHANGE_FEE", "v2：7 天内或换舱等改签手续费 1000", "days_before_departure < 7 or not same_cabin", "1000.00"),
    ]


def _ow_standard_rules(min_stay=False):
    return [
        ("ELIGIBILITY", "仅 MU 承运、Y/B 舱", 'same_carrier and component.rbd in ["Y", "B"]', None),
        ("STOPOVERS", "单程允许至多 1 次停留", "stopovers <= 1", None),
        ("TRANSFERS", "单程允许至多 2 次转机", "transfers <= 2", None),
        ("COMBINABILITY", "Y/B 舱单程可与其他 Y/RT 运价组合（最多 3 个组件）",
         "components_count <= 3", None),
    ]


def _q_ow_rules(desc):
    return [
        ("ELIGIBILITY", "特价舱仅限 Q", 'component.rbd == "Q" and same_carrier', None),
        ("STOPOVERS", desc, "stopovers <= 0", None),
        ("TRANSFERS", "特价舱仅限直飞，不得转机", "transfers <= 0", None),
        ("COMBINABILITY", "特价单程不得与任何运价组合（单段便宜但不能拼）",
         "components_count == 1", None),
    ]


def _q_rt_rules():
    return [
        ("ELIGIBILITY", "特价来回程仅限 Q", 'component.rbd == "Q" and same_carrier', None),
        ("MIN_STAY", "特价票最短停留 3 个当地日历日", "stay_days == None or stay_days >= 3", None),
        ("MAX_STAY", "特价票最长停留 14 个当地日历日", "stay_days == None or stay_days <= 14", None),
        ("COMBINABILITY", "特价来回程不得再与其他运价组合", "components_count == 1", None),
    ]


def _yrtu_rules():
    return [
        ("ELIGIBILITY", "仅 MU 承运 Y 舱", 'same_carrier and component.rbd in ["Y", "B"]', None),
        ("MIN_STAY", "乌鲁木齐线最短停留 2 个当地日历日", "stay_days == None or stay_days >= 2", None),
        ("MAX_STAY", "乌鲁木齐线最长停留 30 个当地日历日", "stay_days == None or stay_days <= 30", None),
        ("COMBINABILITY", "允许与单程 Y 运价组合", "components_count <= 3", None),
        ("CHANGE_FEE", "改签手续费 400", "days_before_departure >= 0", "400.00"),
    ]


def _yrtp_rules():
    return [
        ("ELIGIBILITY", "仅 MU 承运 Y 舱", 'same_carrier and component.rbd in ["Y", "B"]', None),
        ("MIN_STAY", "京沪线最短停留 3 个当地日历日", "stay_days == None or stay_days >= 3", None),
        ("MAX_STAY", "京沪线最长停留 14 个当地日历日", "stay_days == None or stay_days <= 14", None),
        ("COMBINABILITY", "允许与单程 Y 运价组合", "components_count <= 3", None),
    ]


# fare_code -> [(version, note, published_at, rules_fn)]
RULES_PLAN = {
    ("YRT", "RT", "SHA", "NRT"): [
        (1, "2026 夏秋版", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _rules_v1_yrt),
        (2, "2026 冬春版（手续费上调）", datetime(2026, 9, 20, 0, 0, tzinfo=UTC), _rules_v2_yrt),
    ],
    ("QLEISURE", "RT", "SHA", "NRT"): [
        (1, "特价来回程限制", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _q_rt_rules),
    ],
    ("YOW", "OW", "SHA", "NRT"): [
        (1, "单程标准", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _ow_standard_rules),
    ],
    ("QOW", "OW", "SHA", "NRT"): [
        (1, "特价单程不可组合", datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
         lambda: _q_ow_rules("国际特价单程不允许停留")),
    ],
    ("YRTU", "RT", "SHA", "URC"): [
        (1, "乌鲁木齐来回程", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _yrtu_rules),
    ],
    ("YOWU", "OW", "SHA", "URC"): [
        (1, "单程标准", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _ow_standard_rules),
    ],
    ("YRTP", "RT", "SHA", "PEK"): [
        (1, "京沪来回程", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _yrtp_rules),
    ],
    ("YOWP", "OW", "SHA", "PEK"): [
        (1, "单程标准", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _ow_standard_rules),
    ],
    ("YOWP", "OW", "PEK", "SHA"): [
        (1, "单程标准", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _ow_standard_rules),
    ],
    ("QLOWP", "OW", "SHA", "PEK"): [
        (1, "特价单程不可组合", datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
         lambda: _q_ow_rules("京沪特价单程不允许停留")),
    ],
    ("YOWPU", "OW", "PEK", "URC"): [
        (1, "单程标准", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _ow_standard_rules),
    ],
    ("YOWPU", "OW", "URC", "SHA"): [
        (1, "单程标准", datetime(2026, 3, 1, 0, 0, tzinfo=UTC), _ow_standard_rules),
    ],
    ("QLOWPU", "OW", "PEK", "URC"): [
        (1, "特价单程不可组合", datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
         lambda: _q_ow_rules("中转特价单程不允许停留")),
    ],
    ("QLOWPU", "OW", "URC", "SHA"): [
        (1, "特价单程不可组合", datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
         lambda: _q_ow_rules("中转特价单程不允许停留")),
    ],
}


class Command(BaseCommand):
    help = "灌入/刷新虚构培训数据（幂等）"

    def handle(self, *args, **options):
        self._airports()
        flight_pk = self._flights()
        self._fares_and_rules()
        self._taxes()
        self._orders(flight_pk)
        self.stdout.write(self.style.SUCCESS("种子数据就绪（全部为虚构数据）"))

    def _airports(self):
        for code, name, city, tz in AIRPORTS:
            Airport.objects.update_or_create(
                code=code, defaults={"name": name, "city": city, "tz": tz}
            )

    def _flights(self):
        pk = {}
        for carrier, number, dep, arr, dep_utc, arr_utc in FLIGHTS:
            flight, _ = Flight.objects.update_or_create(
                carrier=carrier, number=number, dep_utc=dep_utc,
                defaults={
                    "dep_airport_id": dep,
                    "arr_airport_id": arr,
                    "arr_utc": arr_utc,
                },
            )
            pk[(carrier, number, dep_utc.date().isoformat())] = flight
            for rbd, cabin_name, seats in DEFAULT_CABINS:
                actual_seats = 0 if (carrier, number, rbd) in ZERO_SEATS else seats
                CabinInventory.objects.update_or_create(
                    flight=flight, rbd=rbd,
                    defaults={"cabin_name": cabin_name, "seats": actual_seats},
                )
        return pk

    def _fares_and_rules(self):
        for carrier, origin, dest, rbd, code, direction, amount in FARES:
            fare, _ = Fare.objects.update_or_create(
                carrier=carrier, origin=origin, destination=dest,
                rbd=rbd, fare_code=code, direction=direction,
                defaults={"amount_cny": Decimal(amount), "active": True,
                          "current_rule_version": None},
            )
            plan = RULES_PLAN.get((code, direction, origin, dest), [])
            current = None
            for version_no, note, published_at, rules_fn in plan:
                version, created = FareRuleVersion.objects.update_or_create(
                    fare=fare, version=version_no,
                    defaults={"note": note, "published_at": published_at, "active": True},
                )
                if not created:
                    version.rules.all().delete()
                for code_, desc, expr, fee in rules_fn():
                    Rule.objects.create(
                        version=version, code=code_, description=desc,
                        expression=expr,
                        fee_cny=Decimal(fee) if fee is not None else None,
                    )
                current = version
            if current is not None:
                fare.current_rule_version = current
                fare.save(update_fields=["current_rule_version"])

    def _taxes(self):
        TaxDefinition.objects.all().delete()
        for code, name, cabin, amount in TAXES:
            TaxDefinition.objects.create(
                code=code, name=name, cabin_name=cabin, amount_cny=Decimal(amount)
            )

    def _orders(self, flight_pk):
        # 可改签客票：SHA-NRT 来回程 Y，2026-10-05 去 / 10-09 回（停留 4 天）。
        out1 = Flight.objects.get(carrier="MU", number="521", dep_utc__date="2026-10-05")
        ret1 = Flight.objects.get(carrier="MU", number="524", dep_utc__date="2026-10-09")
        fare = Fare.objects.get(fare_code="YRT", direction="RT", origin="SHA")
        self._make_order(
            pnr="TST101",
            passenger="张培训",
            issued_at=datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
            coupons=[(out1, "Y"), (ret1, "Y")],
            fare=fare,
            # 教学简化：RT 净额 3200 按组件均摊到两张票联；税 50+120+80 每段。
            per_coupon_base="1600.00",
            per_coupon_tax="250.00",
        )

        # 已部分乘机的客票：改签会在票联检查阶段被拦下。
        out2 = Flight.objects.get(carrier="MU", number="5101", dep_utc__date="2026-10-05")
        ret2 = Flight.objects.get(carrier="MU", number="5104", dep_utc__date="2026-10-08")
        fare2 = Fare.objects.get(fare_code="YRTP", direction="RT", origin="SHA")
        self._make_order(
            pnr="TST202",
            passenger="李演练",
            issued_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
            coupons=[(out2, "Y"), (ret2, "Y")],
            fare=fare2,
            per_coupon_base="1100.00",
            per_coupon_tax="170.00",
            used_seqs=[1],
        )

        # 在 v2 生效前出票的客票：快照冻结 v1，改签手续费却按现行 v2 判定。
        ret3 = Flight.objects.get(carrier="MU", number="522", dep_utc__date="2026-10-06")
        self._make_order(
            pnr="TST303",
            passenger="王版本",
            issued_at=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
            coupons=[(out1, "Y"), (ret3, "Y")],
            fare=fare,
            per_coupon_base="1600.00",
            per_coupon_tax="250.00",
            force_rule_version=1,
        )

    def _make_order(self, pnr, passenger, issued_at, coupons, fare,
                    per_coupon_base, per_coupon_tax, used_seqs=None,
                    force_rule_version=None):
        used_seqs = used_seqs or []
        base = Decimal(per_coupon_base) * len(coupons)
        tax = Decimal(per_coupon_tax) * len(coupons)
        if force_rule_version is not None:
            version = fare.rule_versions.get(version=force_rule_version)
        else:
            version = fare.current_rule_version
        snapshot = {
            "rule_version_id": version.id,
            "rule_version_number": version.version,
            "rule_note": version.note,
            "components": [
                {
                    "fare_id": fare.id,
                    "fare_code": fare.fare_code,
                    "direction": fare.direction,
                    "amount": str(fare.amount_cny),
                    "coupon_seqs": [seq for seq in range(1, len(coupons) + 1)],
                }
            ],
            "coupons": [
                {
                    "seq": seq,
                    "flight": f"{flight.carrier}{flight.number}",
                    "rbd": rbd,
                    "base": per_coupon_base,
                    "tax": per_coupon_tax,
                }
                for seq, (flight, rbd) in enumerate(coupons, start=1)
            ],
        }
        order, _ = Order.objects.update_or_create(
            pnr=pnr,
            defaults={
                "passenger": passenger,
                "issued_at": issued_at,
                "fare_snapshot": snapshot,
                "base_amount_cny": base,
                "tax_amount_cny": tax,
                "total_cny": base + tax,
            },
        )
        order.coupons.all().delete()
        for i, (f, rbd) in enumerate(coupons):
            TicketCoupon.objects.create(
                order=order, seq=i + 1, flight=f, rbd=rbd,
                status=TicketCoupon.Status.USED if (i + 1) in used_seqs
                else TicketCoupon.Status.OPEN,
            )
