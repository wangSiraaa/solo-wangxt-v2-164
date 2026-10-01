from rest_framework.routers import DefaultRouter

from .views import AirportViewSet, FareViewSet, FlightViewSet, QuoteViewSet, RebookViewSet

router = DefaultRouter()
router.register("airports", AirportViewSet, basename="airport")
router.register("flights", FlightViewSet, basename="flight")
router.register("fares", FareViewSet, basename="fare")
router.register("quote", QuoteViewSet, basename="quote")
router.register("rebook", RebookViewSet, basename="rebook")

urlpatterns = router.urls
