"""
check/rabbitmq.py

Defensive RabbitMQ/broker health check.

Uses ``kombu`` (already a Celery dependency) or ``pika`` if available; returns
``not_configured`` when no broker URL is set or no client library is present.
"""

import time
from typing import Any

from django.conf import settings


def _broker_url() -> str | None:
    from django_issue_ticca.conf import get_setting

    url = get_setting('RABBITMQ_URL')
    if url:
        return url
    # Fall back to the Celery broker settings.
    for name in ('CELERY_BROKER_URL', 'BROKER_URL'):
        value = getattr(settings, name, None)
        if value:
            return value
    return None


def check_rabbitmq() -> dict[str, Any]:
    """Open (and immediately close) a connection to the broker."""
    start = time.perf_counter()
    url = _broker_url()

    if not url:
        return {
            'status': 'not_configured',
            'detail': 'Set ISSUE_TICCA_RABBITMQ_URL or CELERY_BROKER_URL.',
        }

    try:
        import kombu  # noqa: PLC0415 - optional dependency
    except ImportError:
        kombu = None

    if kombu is not None:
        try:
            with kombu.Connection(url, connect_timeout=2) as connection:
                connection.ensure_connection(max_retries=0, timeout=2)
                connection.release()
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

    try:
        import pika  # noqa: PLC0415 - optional dependency
    except ImportError:
        return {
            'status': 'not_configured',
            'detail': 'Neither "kombu" nor "pika" is installed.',
        }

    try:
        params = pika.URLParameters(url)
        params.socket_timeout = 2
        connection = pika.BlockingConnection(params)
        connection.close()
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
