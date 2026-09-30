from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .engine.pricing import price_itinerary
from .engine.rebooking import (
    commit_change, issue_training_ticket, quote_change,
)
from .models import (
    Airport, ChangeQuote, Fare, Flight, Quote, RuleVersion, TaxRule,
    TrainingTicket,
)
from .serializers import (
    AirportSerializer, ChangeQuoteSerializer, ChangeRequestSerializer,
    FareSerializer, FlightSerializer, PriceRequestSerializer,
    QuoteSerializer, RuleVersionSerializer, TaxSerializer,
    TicketSerializer,
)


class AirportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Airport.objects.all()
    serializer_class = AirportSerializer


class FlightViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FlightSerializer

    def get_queryset(self):
        qs = Flight.objects.select_related(
            'carrier', 'dep_airport', 'arr_airport').prefetch_related('cabins')
        params = self.request.query_params
        if params.get('from'):
            qs = qs.filter(dep_airport=params['from'])
        if params.get('to'):
            qs = qs.filter(arr_airport=params['to'])
        if params.get('date'):
            qs = qs.filter(dep_utc__date=params['date'])
        return qs


class FareViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Fare.objects.select_related('rule_version').prefetch_related(
        'rules', 'route_legs', 'route_legs__origin',
        'route_legs__destination')
    serializer_class = FareSerializer


class RuleVersionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RuleVersion.objects.all()
    serializer_class = RuleVersionSerializer


class TaxViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TaxRule.objects.filter(active=True)
    serializer_class = TaxSerializer


class QuoteViewSet(viewsets.GenericViewSet):
    queryset = Quote.objects.all()
    serializer_class = QuoteSerializer

    @action(detail=False, methods=['post'])
    def price(self, request):
        """多航段运价组合试算（不出票、不占座）。"""
        ser = PriceRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        quote, detail = price_itinerary(
            ser.validated_data['flight_ids'],
            ser.validated_data['booking_classes'],
            booking_date=ser.validated_data.get('booking_date'),
            scenario=ser.validated_data.get('scenario', ''),
            rule_version_tag=ser.validated_data.get('rule_version') or None)
        out = QuoteSerializer(quote).data
        out['trace'] = detail
        return Response(out, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def issue_training(self, request, pk=None):
        """从试算结果生成 TRN- 虚构培训票；不产生真实购票指令。"""
        ticket = issue_training_ticket(int(pk))
        return Response(TicketSerializer(ticket).data,
                        status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        quote = get_object_or_404(
            Quote.objects.prefetch_related(
                'components', 'components__fare', 'taxes', 'taxes__tax',
                'hits', 'rule_version'), pk=pk)
        return Response(QuoteSerializer(quote).data)


class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TrainingTicket.objects.prefetch_related('coupons')
    serializer_class = TicketSerializer
    lookup_field = 'ticket_no'


class ChangeViewSet(viewsets.GenericViewSet):
    queryset = ChangeQuote.objects.all()
    serializer_class = ChangeQuoteSerializer

    @action(detail=False, methods=['post'])
    def quote(self, request):
        """改签试算：票联状态检查 → 新行程试算 → 价差 + 手续费。"""
        ser = ChangeRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = quote_change(
            ser.validated_data['ticket_no'],
            ser.validated_data['new_flight_ids'],
            ser.validated_data['new_booking_classes'],
            booking_date=ser.validated_data.get('booking_date'))
        cq = result[0]
        data = ChangeQuoteSerializer(cq).data
        if len(result) == 2:
            data['trace'] = result[1]
        http = (status.HTTP_200_OK if cq.status == ChangeQuote.Status.OK
                else status.HTTP_409_CONFLICT)
        return Response(data, status=http)

    @action(detail=True, methods=['post'])
    def commit(self, request, pk=None):
        """培训换开：只在沙箱库内换票联状态，不发送真实出票/退款指令。"""
        new_ticket = commit_change(int(pk))
        return Response(TicketSerializer(new_ticket).data,
                        status=status.HTTP_201_CREATED)
