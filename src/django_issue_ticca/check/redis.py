"""
check/redis.py

Defensive Redis health check.

Returns ``not_configured`` when no URL is available or the ``redis`` package
is not installed, so the aggregate health endpoint never fails just because a
subsystem is absent.
"""

import time
from typing import Any, Optional

from django.conf import settings


def _redis_url() -> Optional[str]:
    from django_issue_ticca.conf import get_setting

    url = get_setting('REDIS_URL')
    if url:
        return url

    # Fall back to a Redis-backed Django cache if one is configured.
    try:
        default = settings.CACHES.get('default', {})
    except Exception:
        return None
    location = default.get('LOCATION')
    backend = default.get('BACKEND', '')
    if isinstance(location, (list, tuple)):
        location = location[0] if location else None
    if location and 'redis' in backend.lower():
        return str(location)
    return None


def check_redis() -> dict[str, Any]:
    """Ping Redis and report latency."""
    start = time.perf_counter()
    url = _redis_url()

    if not url:
        return {
            'status': 'not_configured',
            'detail': 'Set ISSUE_TICCA_REDIS_URL or a Redis Django cache backend.',
        }

    try:
        import redis  # noqa: PLC0415 - optional dependency
    except ImportError:
        return {
            'status': 'not_configured',
            'detail': 'The "redis" package is not installed.',
        }

    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return {
            'status': 'ok',
            'latency_ms': round((time.perf_counter() - start) * 1000, 2),
        }
    except Exception as exc:
        return {
            'status': 'error',
            'error': str(exc),
            'exception': type(exc).__name__,
        }
