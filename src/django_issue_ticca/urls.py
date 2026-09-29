from django.urls import path

from .security import signed
from .views import (
    DatabaseProbeView,
    HourlyUserStatsView,
    MonitoringTableView,
    OpenByMethodView,
    OpenByTypeView,
    SystemHealthView,
    UserStatsView,
)

# Every route is wrapped in ``signed``: callers must send a valid signature
# header (HMAC-SHA256 of the request URL, keyed by the ISSUE_TICCA access key).
# Add path suffixes to ISSUE_TICCA['UNPROTECTED_PATHS'] to exempt a route.
urlpatterns = [
    # Overall ("final") health check for the whole system.
    path('health/', signed(SystemHealthView.as_view()), name='system-health'),
    # Single-subsystem database check (kept for backwards compatibility).
    path('database-probe/', signed(DatabaseProbeView.as_view()), name='database-probe'),
    path('monitoring/', signed(MonitoringTableView.as_view()), name='monitoring-list'),
    path(
        'monitoring/open-by-type/',
        signed(OpenByTypeView.as_view()),
        name='open-by-type',
    ),
    path(
        'monitoring/open-by-method/',
        signed(OpenByMethodView.as_view()),
        name='open-by-method',
    ),
    path('stats/users/', signed(UserStatsView.as_view()), name='user-stats'),
    path(
        'stats/users/hourly/',
        signed(HourlyUserStatsView.as_view()),
        name='user-stats-hourly',
    ),
]