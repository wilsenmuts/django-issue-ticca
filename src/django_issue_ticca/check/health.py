"""
check/health.py

Aggregates every subsystem check into a single overall health report.

Status vocabulary
-----------------
Component checks return one of ``ok``, ``not_configured``, ``skipped`` or
``error``. Status words are normalised, so ``healthy`` counts as ``ok`` and
``unhealthy``/``failed`` count as ``error`` (``check_database`` uses the
``healthy``/``unhealthy`` pair).

* ``healthy``   - every *configured* component is ok.
* ``unhealthy`` - at least one configured component errored.
* ``not_configured`` / ``skipped`` components never make the system unhealthy.

This is what ``views.SystemHealthView`` serves at ``/health/``.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from django.utils import timezone

from .celery import check_celery
from .database import check_database
from .rabbitmq import check_rabbitmq
from .redis import check_redis

logger = logging.getLogger(__name__)

#: Registry of component name -> zero-arg callable returning a status dict.
CHECKS: dict[str, Callable[[], dict[str, Any]]] = {
    'database': check_database,
    'redis': check_redis,
    'rabbitmq': check_rabbitmq,
    'celery': check_celery,
}

#: Statuses that do not make the overall system unhealthy.
NON_FATAL_STATUSES = {'ok', 'not_configured', 'skipped'}

#: Checks don't always use the same word for the same outcome (``check_database``
#: returns ``healthy``/``unhealthy``). Map them onto the canonical vocabulary so
#: a healthy component is never reported as failing. Unknown values are treated
#: as errors, so genuine problems are never silently ignored.
STATUS_ALIASES = {
    'ok': 'ok',
    'healthy': 'ok',
    'up': 'ok',
    'pass': 'ok',
    'passed': 'ok',
    'error': 'error',
    'unhealthy': 'error',
    'failed': 'error',
    'fail': 'error',
    'down': 'error',
    'not_configured': 'not_configured',
    'unconfigured': 'not_configured',
    'skipped': 'skipped',
    'ignored': 'skipped',
}


def normalize_status(status) -> str:
    """Map a check's status onto the canonical vocabulary (defaults to error)."""
    return STATUS_ALIASES.get(str(status).strip().lower(), 'error')


def available_components() -> list[str]:
    return list(CHECKS)


def _selected_components(components=None) -> list[str]:
    if components is None:
        return available_components()
    return [name for name in components if name in CHECKS]


def run_health_checks(components=None) -> dict[str, Any]:
    """
    Run the requested checks (all by default) and return a report::

        {
          "status": "healthy" | "unhealthy",
          "components": {"database": {...}, ...},
          "failing": [...],
          "summary": {"ok": 2, "error": 1, "not_configured": 1},
          "latency_ms": 12.3,
          "timestamp": "2026-09-29T10:00:00+00:00",
        }
    """
    start = time.perf_counter()
    selected = _selected_components(components)

    results: dict[str, Any] = {}
    for name in selected:
        check = CHECKS[name]
        try:
            result = check()
            if not isinstance(result, dict) or 'status' not in result:
                result = {
                    'status': 'error',
                    'error': 'Check returned an unexpected result.',
                }
        except Exception as exc:  # a broken check must not break the report
            logger.exception("Health check %r raised", name)
            result = {
                'status': 'error',
                'error': str(exc),
                'exception': type(exc).__name__,
            }
        results[name] = result

    summary: dict[str, int] = {}
    failing: list[str] = []
    for name, result in results.items():
        # Normalise first: ``healthy`` must count as a pass.
        status = normalize_status(result.get('status', 'error'))
        summary[status] = summary.get(status, 0) + 1
        if status not in NON_FATAL_STATUSES:
            failing.append(name)

    return {
        'status': 'unhealthy' if failing else 'healthy',
        'components': results,
        'failing': failing,
        'summary': summary,
        'latency_ms': round((time.perf_counter() - start) * 1000, 2),
        'timestamp': timezone.now().isoformat(),
    }
