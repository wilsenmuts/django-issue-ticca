"""
conf.py

Central place for reading ``django-issue-ticca`` configuration from Django
settings, with sensible defaults.

Two styles are supported so you can pick whichever you prefer:

    # 1) Namespaced dict
    ISSUE_TICCA = {
        "SLOW_RESPONSE_THRESHOLD": 10.0,
        "AUTO_RESOLVE_ON_SUCCESS": True,
    }

    # 2) Flat, prefixed names
    ISSUE_TICCA_SLOW_RESPONSE_THRESHOLD = 10.0
    ISSUE_TICCA_AUTO_RESOLVE_ON_SUCCESS = True
"""

from django.conf import settings

#: Default values for every supported setting.
DEFAULTS = {
    # Requests slower than this many seconds are recorded as slow-response
    # incidents. Set to ``None`` or ``0`` to disable slow-response logging.
    'SLOW_RESPONSE_THRESHOLD': 10.0,
    # When a request to a tracked URL succeeds and is not slow, close the open
    # incidents recorded against that URL.
    'AUTO_RESOLVE_ON_SUCCESS': True,
    # Master switch. When False the middleware becomes a no-op.
    'ENABLED': True,
    # Let ``TrackedException`` subclasses record themselves when created.
    'TRACK_EXCEPTIONS': True,
    # Record per-user hourly stats (unique users / requests per hour).
    'TRACK_HOURLY_USERS': True,
    # How many days of hourly user stats to keep. Older rows are pruned whenever
    # the hourly stats endpoint is called.
    'HOURLY_STATS_RETENTION_DAYS': 7,
    # Optional connection strings used by the subsystem health checks.
    'REDIS_URL': None,
    'RABBITMQ_URL': None,
    'CELERY_APP': None,
    # Subsystems that must be 'ok' for the overall system to be 'healthy'.
    # Missing/ignored subsystems report 'not_configured' and are not fatal.
    'HEALTH_COMPONENTS': None,
}


def get_setting(name: str, default=None):
    """Return a setting, preferring ``ISSUE_TICCA[name]`` then the flat name."""
    namespace = getattr(settings, 'ISSUE_TICCA', None)
    if isinstance(namespace, dict) and name in namespace:
        return namespace[name]

    flat = f'ISSUE_TICCA_{name}'
    if hasattr(settings, flat):
        return getattr(settings, flat)

    if name in DEFAULTS:
        return DEFAULTS[name]

    return default


def slow_response_threshold():
    """Return the slow-response threshold in seconds, or ``None`` if disabled."""
    value = get_setting('SLOW_RESPONSE_THRESHOLD', 10.0)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None
