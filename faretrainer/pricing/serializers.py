from rest_framework import serializers

from .models import (
    Airport, CabinInventory, ChangeQuote, Coupon, Fare, Flight, Quote,
    RuleHit, RuleVersion, TaxRule, TrainingTicket,
)
from .engine import timeutils


class AirportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Airport
        fields = ['code', 'name', 'city', 'timezone']


class CabinSerializer(serializers.ModelSerializer):
    available = serializers.BooleanField(read_only=True)

    class Meta:
        model = CabinInventory
        fields = ['booking_class', 'cabin', 'seats', 'status', 'available']


class FlightSerializer(serializers.ModelSerializer):
    carrier = serializers.CharField(source='carrier_id')
    dep_local = serializers.SerializerMethodField()
    arr_local = serializers.SerializerMethodField()
    cabins = CabinSerializer(many=True, read_only=True)

    class Meta:
        model = Flight
        fields = ['id', 'carrier', 'flight_no', 'dep_airport', 'arr_airport',
                  'dep_utc', 'arr_utc', 'dep_local', 'arr_local', 'cabins']

    def _local(self, utc, airport):
        return timeutils.local_dt(utc, airport).strftime('%Y-%m-%d %H:%M %Z')

    def get_dep_local(self, obj):
        return self._local(obj.dep_utc, obj.dep_airport)

    def get_arr_local(self, obj):
        return self._local(obj.arr_utc, obj.arr_airport)


class RuleVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleVersion
        fields = ['version', 'published_at', 'effective_from',
                  'description', 'active']


class FareRuleSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source='get_category_display',
                                           read_only=True)

    class Meta:
        from .models import Rule
        model = Rule
        fields = ['code', 'category', 'category_label', 'expression',
                  'message_zh', 'hardcoded', 'scope', 'rule_version']


class FareSerializer(serializers.ModelSerializer):
    carrier = serializers.CharField(source='carrier_id')
    rules = FareRuleSerializer(many=True, read_only=True)
    route = serializers.SerializerMethodField()

    class Meta:
        model = Fare
        fields = ['id', 'fare_code', 'carrier', 'origin', 'destination',
                  'fare_type', 'price', 'currency', 'booking_classes',
                  'end_on_end_allowed', 'advance_purchase_days',
                  'change_fee', 'route', 'rules', 'rule_version']

    def get_route(self, obj):
        return [{'seq': l.seq, 'from': l.origin_id, 'to': l.destination_id}
                for l in obj.route_legs.all()]


class TaxSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source='get_kind_display')

    class Meta:
        model = TaxRule
        fields = ['code', 'name', 'kind', 'kind_label', 'amount']


class PriceRequestSerializer(serializers.Serializer):
    flight_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False, max_length=6)
    booking_classes = serializers.ListField(
        child=serializers.CharField(max_length=2), allow_empty=False, max_length=6)
    booking_date = serializers.DateField(required=False, allow_null=True)
    scenario = serializers.CharField(required=False, allow_blank=True)
    rule_version = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if len(attrs['flight_ids']) != len(attrs['booking_classes']):
            raise serializers.ValidationError(
                'flight_ids 与 booking_classes 必须等长（每段一个舱位）')
        return attrs


class RuleHitSerializer(serializers.ModelSerializer):
    result_label = serializers.CharField(source='get_result_display')

    class Meta:
        model = RuleHit
        fields = ['component_seq', 'segment_indexes', 'fare_code',
                  'partition_key', 'rule_code', 'rule_category',
                  'result', 'result_label', 'message', 'expression',
                  'context', 'rule_version', 'chosen']


class ComponentSerializer(serializers.ModelSerializer):
    fare_code = serializers.CharField(source='fare.fare_code')

    class Meta:
        from .models import QuoteComponent
        model = QuoteComponent
        fields = ['seq', 'fare_code', 'segment_indexes', 'base_fare',
                  'tax_total']


class QuoteTaxSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source='tax.code')
    name = serializers.CharField(source='tax.name')

    class Meta:
        from .models import QuoteTax
        model = QuoteTax
        fields = ['component_seq', 'code', 'name', 'amount']


class QuoteSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display')
    purpose_label = serializers.CharField(source='get_purpose_display')
    rule_version = serializers.CharField(source='rule_version.version')
    components = ComponentSerializer(many=True)
    taxes = QuoteTaxSerializer(many=True)
    hits = RuleHitSerializer(many=True)

    class Meta:
        model = Quote
        fields = ['id', 'created_at', 'purpose', 'purpose_label', 'scenario',
                  'status', 'status_label', 'rule_version', 'request_payload',
                  'base_fare', 'tax_total', 'total', 'currency',
                  'failure_reason', 'components', 'taxes', 'hits']


class CouponSerializer(serializers.ModelSerializer):
    flight = serializers.StringRelatedField()
    flight_id = serializers.IntegerField(source='flight.id', read_only=True)
    status_label = serializers.CharField(source='get_status_display')

    class Meta:
        model = Coupon
        fields = ['seq', 'flight', 'flight_id', 'booking_class', 'status',
                  'status_label']


class TicketSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display')
    coupons = CouponSerializer(many=True)

    class Meta:
        model = TrainingTicket
        fields = ['ticket_no', 'issued_at', 'status', 'status_label',
                  'total', 'currency', 'coupons', 'quote']


class ChangeRequestSerializer(serializers.Serializer):
    ticket_no = serializers.CharField(max_length=16)
    new_flight_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False, max_length=6)
    new_booking_classes = serializers.ListField(
        child=serializers.CharField(max_length=2), allow_empty=False, max_length=6)
    booking_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if len(attrs['new_flight_ids']) != len(attrs['new_booking_classes']):
            raise serializers.ValidationError(
                '新行程 flight_ids 与 new_booking_classes 必须等长')
        return attrs


class ChangeQuoteSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display')

    class Meta:
        model = ChangeQuote
        fields = ['id', 'created_at', 'ticket', 'new_quote', 'status',
                  'status_label', 'coupon_check', 'original_total',
                  'new_total', 'fare_diff', 'change_fee',
                  'collect_or_refund', 'note']
