"""DRF 接口（培训用，只读 + 两个试算动作，不接任何真实订座/出票）。"""
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import engine
from .models import Airport, Fare, FareRuleVersion, Flight, Rule
from .timeutils import local_str


class AirportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Airport
        fields = ["code", "name", "city", "tz"]


class FlightSerializer(serializers.ModelSerializer):
    dep_airport = serializers.SlugRelatedField(slug_field="code", read_only=True)
    arr_airport = serializers.SlugRelatedField(slug_field="code", read_only=True)
    dep_local = serializers.SerializerMethodField()
    arr_local = serializers.SerializerMethodField()
    cabins = serializers.SerializerMethodField()

    class Meta:
        model = Flight
        fields = [
            "id", "carrier", "number", "dep_airport", "arr_airport",
            "dep_utc", "arr_utc", "dep_local", "arr_local", "cabins",
        ]

    def get_dep_local(self, obj):
        return local_str(obj.dep_utc, obj.dep_airport.tz)

    def get_arr_local(self, obj):
        return local_str(obj.arr_utc, obj.arr_airport.tz)

    def get_cabins(self, obj):
        return [
            {"rbd": c.rbd, "cabin_name": c.cabin_name, "seats": c.seats}
            for c in obj.cabins.all()
        ]


class RuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rule
        fields = ["id", "code", "description", "expression", "fee_cny"]


class RuleVersionSerializer(serializers.ModelSerializer):
    rules = RuleSerializer(many=True)
    fare_code = serializers.CharField(source="fare.fare_code")
    fare_od = serializers.SerializerMethodField()
    active_fare_uses_this = serializers.SerializerMethodField()

    class Meta:
        model = FareRuleVersion
        fields = [
            "id", "fare_id", "fare_code", "fare_od", "version", "note",
            "published_at", "active", "active_fare_uses_this", "rules",
        ]

    def get_fare_od(self, obj):
        return f"{obj.fare.origin}-{obj.fare.destination} {obj.fare.direction}"

    def get_active_fare_uses_this(self, obj):
        return obj.fare.current_rule_version_id == obj.id


@method_decorator(csrf_exempt, name="dispatch")
class FlightViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Flight.objects.select_related(
        "dep_airport", "arr_airport"
    ).prefetch_related("cabins").all()
    serializer_class = FlightSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("origin"):
            qs = qs.filter(dep_airport_id=params["origin"].upper())
        if params.get("destination"):
            qs = filter_destination(qs, params["destination"].upper())
        if params.get("date"):
            qs = qs.filter(dep_utc__date=params["date"])
        return qs


def filter_destination(qs, code):
    return qs.filter(arr_airport_id=code)


@method_decorator(csrf_exempt, name="dispatch")
class AirportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Airport.objects.all()
    serializer_class = AirportSerializer
    pagination_class = None


@method_decorator(csrf_exempt, name="dispatch")
class FareViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Fare.objects.select_related("current_rule_version")
    pagination_class = None

    def list(self, request):
        data = [
            {
                "id": f.id,
                "carrier": f.carrier,
                "origin": f.origin,
                "destination": f.destination,
                "rbd": f.rbd,
                "fare_code": f.fare_code,
                "direction": f.direction,
                "amount_cny": str(f.amount_cny),
                "current_rule_version_id": f.current_rule_version_id,
            }
            for f in self.get_queryset()
        ]
        return Response(data)

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        fare = self.get_object()
        versions = fare.rule_versions.prefetch_related("rules").all()
        return Response(RuleVersionSerializer(versions, many=True).data)


@method_decorator(csrf_exempt, name="dispatch")
class QuoteViewSet(viewsets.ViewSet):
    """POST /api/quote/  试算多航段运价组合。"""

    def create(self, request):
        segments = request.data.get("segments")
        if not isinstance(segments, list):
            return Response(
                {"ok": False, "error": {"code": "BAD_REQUEST",
                                        "message": "segments 必须为数组"}},
                status=400,
            )
        result = engine.quote(segments)
        return Response(result, status=200 if result.get("ok") else 422)


@method_decorator(csrf_exempt, name="dispatch")
class RebookViewSet(viewsets.ViewSet):
    """POST /api/rebook/  改签试算：票联状态 -> 舱位 -> 价差/手续费/税。"""

    def create(self, request):
        pnr = request.data.get("pnr")
        changes = request.data.get("changes")
        if not pnr or not isinstance(changes, list):
            return Response(
                {"ok": False, "error": {"code": "BAD_REQUEST",
                                        "message": "需要 pnr 与 changes 数组"}},
                status=400,
            )
        result = engine.rebook(pnr, changes)
        return Response(result, status=200 if result.get("ok") else 422)
