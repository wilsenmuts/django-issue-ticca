from django.urls import path

from .views import (
    DatabaseProbeView,
    HourlyUserStatsView,
    MonitoringTableView,
    OpenByMethodView,
    OpenByTypeView,
    SystemHealthView,
    UserStatsView,
)

urlpatterns = [
    # Overall ("final") health check for the whole system.
    path('health/', SystemHealthView.as_view(), name='system-health'),
    # Single-subsystem database check (kept for backwards compatibility).
    path('database-probe/', DatabaseProbeView.as_view(), name='database-probe'),
    path('monitoring/', MonitoringTableView.as_view(), name='monitoring-list'),
    path('monitoring/open-by-type/', OpenByTypeView.as_view(), name='open-by-type'),
    path('monitoring/open-by-method/', OpenByMethodView.as_view(), name='open-by-method'),
    path('stats/users/', UserStatsView.as_view(), name='user-stats'),
    path('stats/users/hourly/', HourlyUserStatsView.as_view(), name='user-stats-hourly'),
]