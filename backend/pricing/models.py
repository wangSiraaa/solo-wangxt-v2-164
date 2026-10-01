from django.db import models


class Airport(models.Model):
    """机场（全部为虚构培训数据）。tz 用于把航班 UTC 时刻还原成机场当地日历。"""

    code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=64)
    city = models.CharField(max_length=32)
    tz = models.CharField(max_length=40, help_text="IANA 时区，如 Asia/Shanghai")

    class Meta:
        db_table = "airport"

    def __str__(self):
        return self.code


class Flight(models.Model):
    """某一天实际执行的虚构航班。

    dep_utc / arr_utc 存 UTC（USE_TZ=True），当地时刻由起降机场的 tz 推导。
    跨日、跨时区绝不靠字符串日期相减，统一用 aware datetime 计算。
    """

    carrier = models.CharField(max_length=2)
    number = models.CharField(max_length=5)
    dep_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="departures"
    )
    arr_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="arrivals"
    )
    dep_utc = models.DateTimeField()
    arr_utc = models.DateTimeField()

    class Meta:
        db_table = "flight"
        ordering = ["dep_utc", "carrier", "number"]
        unique_together = ("carrier", "number", "dep_utc")

    def __str__(self):
        return f"{self.carrier}{self.number} {self.dep_airport}-{self.arr_airport}"


class CabinInventory(models.Model):
    """某航班某个订座舱位（RBD，booking class）的虚构可占座数。"""

    flight = models.ForeignKey(
        Flight, on_delete=models.CASCADE, related_name="cabins"
    )
    rbd = models.CharField(max_length=1)
    cabin_name = models.CharField(max_length=16)
    seats = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "cabin_inventory"
        verbose_name_plural = "cabin inventories"
        unique_together = ("flight", "rbd")

    def __str__(self):
        return f"{self.flight_id}/{self.rbd}:{self.seats}"


class Fare(models.Model):
    """公布运价。OW = 单程；RT = 来回程票价（覆盖去+回两个运价组件）。

    价格是“每个票价组件”的净额：RT 价格本身同时约束两个组件，而不是两段
    单价相加。组合限制决定它能否和其他运价拼接成更大的行程。
    """

    class Direction(models.TextChoices):
        OW = "OW", "One way 单程"
        RT = "RT", "Round trip 来回程"

    carrier = models.CharField(max_length=2)
    origin = models.CharField(max_length=3)
    destination = models.CharField(max_length=3)
    rbd = models.CharField(max_length=1, verbose_name="订座舱位 RBD")
    fare_code = models.CharField(max_length=12)
    direction = models.CharField(max_length=2, choices=Direction.choices)
    amount_cny = models.DecimalField(max_digits=10, decimal_places=2)
    # 引用当前生效规则版本；历史版本保留在 FareRuleVersion 中供试算追溯。
    current_rule_version = models.ForeignKey(
        "FareRuleVersion",
        on_delete=models.PROTECT,
        related_name="active_fares",
        null=True,
        blank=True,
    )
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "fare"
        ordering = ["carrier", "origin", "destination", "rbd"]

    def __str__(self):
        return f"{self.carrier} {self.origin}-{self.destination} {self.fare_code} {self.rbd} {self.direction} {self.amount_cny}"


class FareRuleVersion(models.Model):
    """规则版本头。任何试算结果都回链到具体 version，做到可追溯。"""

    fare = models.ForeignKey(
        Fare, on_delete=models.PROTECT, related_name="rule_versions"
    )
    version = models.PositiveIntegerField()
    note = models.CharField(max_length=200, blank=True)
    published_at = models.DateTimeField()
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "fare_rule_version"
        unique_together = ("fare", "version")
        ordering = ["fare_id", "-version"]

    def __str__(self):
        return f"{self.fare_id} rules v{self.version}"


class Rule(models.Model):
    """单条规则。code 决定引擎喂给表达式的上下文与失败语义。

    expression 是受限表达式（见 pricing/rules_lang.py），只读、无函数副作用，
    由 AST 白名单求值，不使用 eval/exec。
    """

    CODE_CHOICES = [
        ("ELIGIBILITY", "适用舱位/航司/航段"),
        ("STOPOVERS", "停留次数限制"),
        ("TRANSFERS", "转机次数限制"),
        ("MIN_STAY", "最短停留（当地日历日）"),
        ("MAX_STAY", "最长停留（当地日历日）"),
        ("COMBINABILITY", "联程/运价组合限制"),
        ("CHANGE_FEE", "改签手续费（命中即生效）"),
        ("CUSTOM", "自定义表达式"),
    ]

    version = models.ForeignKey(
        FareRuleVersion, on_delete=models.CASCADE, related_name="rules"
    )
    code = models.CharField(max_length=16, choices=CODE_CHOICES)
    description = models.CharField(max_length=200)
    expression = models.TextField(
        help_text="受限布尔/数值表达式，例如 min_stay_days >= 3"
    )
    # CHANGE_FEE 命中后收的固定手续费（人民币，Decimal 核算）。
    fee_cny = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    class Meta:
        db_table = "rule"

    def __str__(self):
        return f"v{self.version_id} {self.code}"


class TaxDefinition(models.Model):
    """按舱等适用的虚构税费，逐段计收、分别列示，绝不揉进票价。"""

    code = models.CharField(max_length=8)
    name = models.CharField(max_length=64)
    cabin_name = models.CharField(max_length=16)
    amount_cny = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "tax_definition"

    def __str__(self):
        return f"{self.code} {self.cabin_name} {self.amount_cny}"


class Order(models.Model):
    """虚构订单/客票。仅为改签流程演示，不产生真实购票/退款指令。"""

    pnr = models.CharField(max_length=6, unique=True)
    passenger = models.CharField(max_length=32)
    issued_at = models.DateTimeField()
    # 出票时把运价、规则版本、价格快照冻结，后续规则改版不影响老票。
    fare_snapshot = models.JSONField(default=dict)
    base_amount_cny = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount_cny = models.DecimalField(max_digits=10, decimal_places=2)
    total_cny = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "order"


class TicketCoupon(models.Model):
    """票联：一个航段一张。改签必须先逐张检查票联状态。"""

    class Status(models.TextChoices):
        OPEN = "OPEN", "未使用"
        USED = "USED", "已乘机"
        EXCHANGED = "EXCHANGED", "已换开"
        REFUNDED = "REFUNDED", "已退"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="coupons")
    seq = models.PositiveSmallIntegerField()
    flight = models.ForeignKey(Flight, on_delete=models.PROTECT)
    rbd = models.CharField(max_length=1)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )

    class Meta:
        db_table = "ticket_coupon"
        unique_together = ("order", "seq")
        ordering = ["order_id", "seq"]
