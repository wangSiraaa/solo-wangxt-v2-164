"""URL 配置：/api/ 为 DRF JSON 接口；其余路径交给 Vue 单页（frontend/dist）。"""

from pathlib import Path

from django.urls import include, path, re_path
from django.views.static import serve
from django.conf import settings
from rest_framework.routers import DefaultRouter

from pricing import views

DIST = settings.BASE_DIR / 'frontend' / 'dist'

router = DefaultRouter()
router.register('airports', views.AirportViewSet, basename='airport')
router.register('flights', views.FlightViewSet, basename='flight')
router.register('fares', views.FareViewSet, basename='fare')
router.register('rule-versions', views.RuleVersionViewSet,
                basename='ruleversion')
router.register('taxes', views.TaxViewSet, basename='tax')
router.register('quotes', views.QuoteViewSet, basename='quote')
router.register('tickets', views.TicketViewSet, basename='ticket')
router.register('changes', views.ChangeViewSet, basename='change')

urlpatterns = [
    path('api/', include(router.urls)),
    # Vite 构建产物（含 hash 的 /assets/...）与 SPA 入口
    re_path(r'^assets/(?P<path>.*)$', serve,
            kwargs={'document_root': str(DIST / 'assets')}),
    re_path(r'^favicon.ico$', serve,
            kwargs={'path': 'favicon.ico', 'document_root': str(DIST)}),
    re_path(r'^(?!api/).*$', serve,
            kwargs={'path': 'index.html', 'document_root': str(DIST)}),
]
