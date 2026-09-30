"""
培训沙箱数据模型。

所有航班、舱位、运价、票号均为虚构数据；TrainingTicket / Coupon 只记录培训用的
票联状态机，永远不会对接真实订座（PNR/GDS）或出票/退款接口。
"""

from decimal import Decimal

from django.db import models


class Airport(models.Model):
    """机场。时间校验以机场本地时区为准（IANA tz）。"""

    code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=64)
    city = models.CharField(max_length=32)
    timezone = models.CharField('IANA 时区', max_length=48, default='Asia/Shanghai')

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f'{self.code} {self.city}'


class Airline(models.Model):
    code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=64)

    def __str__(self):
        return f'{self.code} {self.name}'


class Flight(models.Model):
    """
    虚构的、带具体日期的航段实例。
    dep_utc / arr_utc 统一存 UTC；本地时间由机场时区换算，
    禁止用日期字符串直接相减。
    """

    carrier = models.ForeignKey(Airline, on_delete=models.PROTECT, related_name='flights')
    flight_no = models.CharField(max_length=6)
    dep_airport = models.ForeignKey(Airport, on_delete=models.PROTECT,
                                    related_name='departures')
    arr_airport = models.ForeignKey(Airport, on_delete=models.PROTECT,
                                    related_name='arrivals')
    dep_utc = models.DateTimeField('UTC 起飞时刻')
    arr_utc = models.DateTimeField('UTC 到达时刻')

    class Meta:
        ordering = ['dep_utc']
        unique_together = [('carrier', 'flight_no', 'dep_utc')]

    def __str__(self):
        return f'{self.carrier_id}{self.flight_no} {self.dep_airport_id}-{self.arr_airport_id}'


class CabinInventory(models.Model):
    """某航班上某预订舱位的库存（虚构）。"""

    class ClassStatus(models.TextChoices):
        OPEN = 'OPEN', '可售'
        CLOSED = 'CLOSED', '关闭'
        WAITLIST = 'WAITLIST', '候补'

    flight = models.ForeignKey(Flight, on_delete=models.CASCADE, related_name='cabins')
    booking_class = models.CharField('预订舱位', max_length=2)
    cabin = models.CharField('物理舱位', max_length=16, default='经济舱')
    seats = models.IntegerField('剩余座位', default=0)
    status = models.CharField(max_length=8, choices=ClassStatus.choices,
                              default=ClassStatus.OPEN)

    class Meta:
        unique_together = [('flight', 'booking_class')]

    @property
    def available(self) -> bool:
        return self.status == self.ClassStatus.OPEN and self.seats > 0


class RuleVersion(models.Model):
    """规则版本。每一次试算都固定到一个版本，结果可追溯。"""

    version = models.CharField(max_length=32, unique=True)
    published_at = models.DateTimeField()
    effective_from = models.DateField()
    description = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-published_at']

    def __str__(self):
        return self.version


class Fare(models.Model):
    """
    运价（fare）。通过 FareRouteLeg 声明自己覆盖的城市对序列，可由多个
    航班段组合使用 —— 这正是"票价不是逐段相加"的核心：一个 PEK-XIY-KWL
    联程运价的价格覆盖整条路径。
    """

    class FareType(models.TextChoices):
        ONE_WAY = 'OW', '单程'
        ROUND_TRIP = 'RT', '往返'

    rule_version = models.ForeignKey(RuleVersion, on_delete=models.PROTECT,
                                     related_name='fares')
    fare_code = models.CharField(max_length=24)
    carrier = models.ForeignKey(Airline, on_delete=models.PROTECT, related_name='fares')
    origin = models.ForeignKey(Airport, on_delete=models.PROTECT, related_name='fares_from')
    destination = models.ForeignKey(Airport, on_delete=models.PROTECT,
                                    related_name='fares_to')
    fare_type = models.CharField(max_length=2, choices=FareType.choices,
                                 default=FareType.ONE_WAY)
    price = models.DecimalField('运价金额（不含税）', max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='CNY')
    booking_classes = models.JSONField('适用预订舱位', default=list)  # ["M","H","Q"]
    # 联程组合（end-on-end / side-trip）许可：False 时该运价只能单独使用
    end_on_end_allowed = models.BooleanField('允许与其他运价联程组合', default=False)
    advance_purchase_days = models.IntegerField('提前购票天数', default=0)
    change_fee = models.DecimalField('改签手续费', max_digits=10, decimal_places=2,
                                     default=Decimal('0.00'))
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('rule_version', 'fare_code')]

    def __str__(self):
        return f'{self.fare_code} {self.price}'


class FareRouteLeg(models.Model):
    """运价路由序列：seq=0 PEK-XIY, seq=1 XIY-KWL 表示该运价覆盖联程路径。"""

    fare = models.ForeignKey(Fare, on_delete=models.CASCADE, related_name='route_legs')
    seq = models.IntegerField()
    origin = models.ForeignKey(Airport, on_delete=models.PROTECT)
    destination = models.ForeignKey(Airport, on_delete=models.PROTECT, related_name='+')

    class Meta:
        ordering = ['fare', 'seq']
        unique_together = [('fare', 'seq')]


class Rule(models.Model):
    """
    运价规则。条件用沙箱表达式语言书写，示例：

        转机时间   min_layover_minutes >= 45 and max_layover_minutes < 1440
        停留次数   stopover_count <= 1
        最短停留   stay_days >= 3
        最长停留   stay_days <= 30
        跨日限制   date_change_count == 0
        舱位       booking_class in ['M', 'H']
        周六过夜   has_saturday_night == true
    """

    class Category(models.TextChoices):
        TRANSFER = 'TRANSFER', '转机'
        STOPOVER = 'STOPOVER', '停留'
        MIN_STAY = 'MIN_STAY', '最短停留'
        MAX_STAY = 'MAX_STAY', '最长停留'
        COMBINATION = 'COMBINATION', '联程组合'
        BOOKING_CLASS = 'BOOKING_CLASS', '舱位'
        ADVANCE = 'ADVANCE', '提前购票'
        DATE_CHANGE = 'DATE_CHANGE', '跨日期变更'
        AVAILABILITY = 'AVAILABILITY', '舱位可用性'
        ITINERARY = 'ITINERARY', '行程顺序'

    fare = models.ForeignKey(Fare, on_delete=models.CASCADE, related_name='rules')
    rule_version = models.ForeignKey(RuleVersion, on_delete=models.PROTECT, related_name='rules')
    code = models.CharField(max_length=24)
    category = models.CharField(max_length=16, choices=Category.choices)
    expression = models.TextField()
    message_zh = models.CharField(max_length=255)
    # AVAILABILITY/ITINERARY 类由引擎代码实现，不参与表达式求值
    hardcoded = models.BooleanField(default=False)
    # 规则求值位置：仅组件内部 / 仅组件间衔接点 / 两者都执行
    class RuleScope(models.TextChoices):
        INTERNAL = 'INTERNAL', '组件内部'
        BOUNDARY = 'BOUNDARY', '组件间衔接'
        BOTH = 'BOTH', '内部与衔接'
    scope = models.CharField(max_length=10, choices=RuleScope.choices,
                             default=RuleScope.INTERNAL)
    active = models.BooleanField(default=True)

    class Meta:
        unique_together = [('fare', 'code')]
        ordering = ['fare', 'code']


class TaxRule(models.Model):
    """税项。结果中分别列示，绝不并入运价只给一个总价。"""

    class Kind(models.TextChoices):
        FIXED_PER_COMPONENT = 'FIXED_PER_COMPONENT', '每运价组件固定额'
        FIXED_PER_SEGMENT = 'FIXED_PER_SEGMENT', '每航段固定额'
        PERCENT_OF_BASE = 'PERCENT_OF_BASE', '按运价基数百分比'

    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # PERCENT 时 amount=1.50 表示 1.50%；FIXED 时 amount 为金额
    active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.code} {self.name}'


class Quote(models.Model):
    """一次试算结果（报价单）。"""

    class Status(models.TextChoices):
        OK = 'OK', '试算成功'
        FAILED = 'FAILED', '无可用组合'

    class Purpose(models.TextChoices):
        PRICE = 'PRICE', '新建行程试算'
        CHANGE = 'CHANGE', '改签试算'

    created_at = models.DateTimeField(auto_now_add=True)
    purpose = models.CharField(max_length=8, choices=Purpose.choices,
                               default=Purpose.PRICE)
    scenario = models.CharField('教学场景标签', max_length=32, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices)
    rule_version = models.ForeignKey(RuleVersion, on_delete=models.PROTECT,
                                     null=True, related_name='quotes')
    request_payload = models.JSONField(default=dict)
    base_fare = models.DecimalField(max_digits=12, decimal_places=2,
                                    default=Decimal('0.00'))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2,
                                    default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2,
                                default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='CNY')
    failure_reason = models.CharField(max_length=255, blank=True)


class QuoteComponent(models.Model):
    """中选组合里的运价组件（一个组件可覆盖多个航段）。"""

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='components')
    seq = models.IntegerField()
    fare = models.ForeignKey(Fare, on_delete=models.PROTECT, related_name='+')
    segment_indexes = models.JSONField(default=list)  # [0, 1] —— 覆盖第 0、1 段
    base_fare = models.DecimalField(max_digits=10, decimal_places=2)
    tax_total = models.DecimalField(max_digits=10, decimal_places=2,
                                    default=Decimal('0.00'))


class QuoteTax(models.Model):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='taxes')
    component_seq = models.IntegerField(null=True)
    tax = models.ForeignKey(TaxRule, on_delete=models.PROTECT, related_name='+')
    amount = models.DecimalField(max_digits=10, decimal_places=2)


class RuleHit(models.Model):
    """
    规则命中记录：中选组合与被淘汰的组合都记录，表达式与取值现场一并保存，
    学员可以从试算结果点回规则版本与具体表达式。
    """

    class Result(models.TextChoices):
        PASS = 'PASS', '通过'
        FAIL = 'FAIL', '未通过'
        INFO = 'INFO', '说明'

    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='hits')
    component_seq = models.IntegerField(null=True)
    segment_indexes = models.JSONField(default=list)
    fare_code = models.CharField(max_length=24, blank=True)
    partition_key = models.CharField('组合切分方式', max_length=64)
    rule_code = models.CharField(max_length=24)
    rule_category = models.CharField(max_length=16, blank=True)
    result = models.CharField(max_length=8, choices=Result.choices)
    message = models.CharField(max_length=255)
    expression = models.TextField(blank=True)
    context = models.JSONField(default=dict)
    rule_version = models.CharField(max_length=32, blank=True)
    chosen = models.BooleanField('是否中选组合', default=False)


class TrainingTicket(models.Model):
    """
    培训用电子客票（TRN- 开头，虚构）。仅在沙箱数据库内流转；
    系统不提供、也不会生成任何真实购票/退款指令。
    """

    class Status(models.TextChoices):
        ISSUED = 'ISSUED', '已出票(培训)'
        EXCHANGED = 'EXCHANGED', '已改签(培训)'
        VOID = 'VOID', '作废(培训)'

    ticket_no = models.CharField(max_length=16, unique=True)
    quote = models.ForeignKey(Quote, on_delete=models.PROTECT, related_name='tickets')
    issued_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.ISSUED)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='CNY')


class Coupon(models.Model):
    """
    票联（flight coupon），一航段一张。改签必须先检查剩余票联状态再谈价格 ——
    USED / EXCHANGED 票联不可再次使用。
    """

    class Status(models.TextChoices):
        OPEN = 'OPEN', '未使用'
        USED = 'USED', '已使用'
        EXCHANGED = 'EXCHANGED', '已换开'

    ticket = models.ForeignKey(TrainingTicket, on_delete=models.CASCADE, related_name='coupons')
    seq = models.IntegerField()
    flight = models.ForeignKey(Flight, on_delete=models.PROTECT, related_name='+')
    fare = models.ForeignKey(Fare, on_delete=models.PROTECT, related_name='+')
    booking_class = models.CharField(max_length=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    class Meta:
        unique_together = [('ticket', 'seq')]
        ordering = ['ticket', 'seq']


class ChangeQuote(models.Model):
    """改签试算：先票联状态检查，再价差 + 手续费，税项分列在新报价单上。"""

    class Status(models.TextChoices):
        OK = 'OK', '可改签'
        BLOCKED = 'BLOCKED', '不可改签'
        COMMITTED = 'COMMITTED', '已换开(培训记录)'

    created_at = models.DateTimeField(auto_now_add=True)
    ticket = models.ForeignKey(TrainingTicket, on_delete=models.CASCADE,
                               related_name='changes')
    new_quote = models.ForeignKey(Quote, on_delete=models.PROTECT, related_name='+')
    status = models.CharField(max_length=10, choices=Status.choices)
    coupon_check = models.JSONField('票联状态检查明细', default=list)
    original_total = models.DecimalField(max_digits=12, decimal_places=2)
    new_total = models.DecimalField(max_digits=12, decimal_places=2)
    fare_diff = models.DecimalField('价差（正补收/负退还，均为模拟）',
                                    max_digits=12, decimal_places=2)
    change_fee = models.DecimalField(max_digits=12, decimal_places=2,
                                     default=Decimal('0.00'))
    collect_or_refund = models.DecimalField(max_digits=12, decimal_places=2,
                                            default=Decimal('0.00'))
    note = models.CharField(max_length=255, blank=True)
