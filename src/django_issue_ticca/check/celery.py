"""
check/celery.py

Defensive Celery health check: pings registered workers.

The Celery app is resolved from ``ISSUE_TICCA['CELERY_APP']`` (a dotted path)
then falls back to Celery's ``current_app``. Returns ``not_configured`` when
Celery is unavailable or no workers respond within the timeout.
"""

import time
from typing import Any

from django.utils.module_loading import import_string


def _celery_app():
    from django_issue_ticca.conf import get_setting

    dotted = get_setting('CELERY_APP')
    if dotted:
        return import_string(dotted)

    try:
        from celery import current_app  # noqa: PLC0415 - optional dependency
    except ImportError:
        return None

    # ``current_app`` is a lazy proxy; force it to resolve.
    try:
        if not getattr(current_app, 'conf', None):
            return None
        current_app.conf  # noqa: B018 - trigger proxy resolution
        return current_app
    except Exception:
        return None


def check_celery(timeout: float = 2.0) -> dict[str, Any]:
    """Ping Celery workers and report how many replied."""
    start = time.perf_counter()

    try:
        import celery  # noqa: F401,PLC0415 - optional dependency
    except ImportError:
        return {
            'status': 'not_configured',
            'detail': 'The "celery" package is not installed.',
        }

    try:
        app = _celery_app()
    except Exception as exc:
        return {
            'status': 'error',
            'error': str(exc),
            'exception': type(exc).__name__,
        }

    if app is None:
        return {
            'status': 'not_configured',
            'detail': 'Set ISSUE_TICCA_CELERY_APP or configure a Celery app.',
        }

    try:
        replies = app.control.ping(timeout=timeout) or []
        if not replies:
            return {
                'status': 'error',
                'error': 'No Celery workers responded to ping.',
                'workers_online': 0,
            }
        return {
            'status': 'ok',
            'workers_online': len(replies),
            'latency_ms': round((time.perf_counter() - start) * 1000, 2),
        }
    except Exception as exc:
        return {
            'status': 'error',
            'error': str(exc),
            'exception': type(exc).__name__,
        }
