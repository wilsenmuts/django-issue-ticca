"""
incidents.py

The single place where incidents are written to the ``monitoring_table``.

Lifecycle
---------
1. First time an issue is seen for ``(kind, exception_type, affected_method)``
   a row is created (see ``models.generate_incident_id`` for the auto id).
2. Every *subsequent* occurrence is **not** inserted as a new row. Instead
   ``calls_before_closure`` is incremented and ``last_noticed_at`` updated.
3. When the same URL later completes successfully (and is not slow) the open
   incident is closed and ``closed_at`` is stamped.

That gives you: logged once, counted while it keeps happening, auto-closed once
it stops. See ``middleware.ResponseTimeLoggingMiddleware`` for step 3.
"""

import logging
import traceback

from django.db import transaction
from django.utils import timezone

from .models import IncidentKind, IncidentStatus, monitoring_table
from .signals import incident_logged, incident_resolved

logger = logging.getLogger(__name__)

# Defensive truncation limits, kept in sync with the model field sizes.
METHOD_MAX = 255
TYPE_MAX = 200
MESSAGE_MAX = 500


def _clip(value, limit: int) -> str:
    value = '' if value is None else str(value)
    return value if len(value) <= limit else value[: limit - 1] + '\u2026'


def _affected_method(request) -> str:
    """The URL a request hit, without the query string (stable grouping key)."""
    if request is None:
        return 'unknown'
    path = getattr(request, 'path', None)
    if not path:
        try:
            path = request.get_full_path()
        except Exception:
            path = None
    return _clip(path or 'unknown', METHOD_MAX)


def log_incident(
    *,
    kind: str,
    exception_type: str,
    affected_method: str,
    message: str = '',
    traceback_text: str = '',
):
    """
    Create or update the open incident for this ``(kind, type, url)`` tuple.

    Returns ``(incident, created)`` where ``created`` tells you whether a new
    row was inserted (True) or an existing one was incremented (False).
    """
    exception_type = _clip(exception_type, TYPE_MAX)
    affected_method = _clip(affected_method, METHOD_MAX)
    message = _clip(message, MESSAGE_MAX)
    now = timezone.now()

    with transaction.atomic():
        incident = (
            monitoring_table.objects
            .select_for_update()
            .filter(
                kind=kind,
                exception_type=exception_type,
                affected_method=affected_method,
                status=IncidentStatus.OPEN,
            )
            .order_by('-created_at')
            .first()
        )

        if incident is None:
            incident = monitoring_table.objects.create(
                kind=kind,
                exception_type=exception_type,
                affected_method=affected_method,
                exception_message=message,
                exception_traceback=traceback_text or '',
                status=IncidentStatus.OPEN,
                last_noticed_at=now,
                calls_before_closure=1,
            )
            created = True
        else:
            incident.exception_message = message or incident.exception_message
            if traceback_text:
                incident.exception_traceback = traceback_text
            incident.last_noticed_at = now
            incident.calls_before_closure = (incident.calls_before_closure or 0) + 1
            incident.save(update_fields=[
                'exception_message',
                'exception_traceback',
                'last_noticed_at',
                'calls_before_closure',
            ])
            created = False

    try:
        incident_logged.send(
            sender=monitoring_table,
            incident=incident,
            created=created,
        )
    except Exception:  # pragma: no cover - receivers must never break logging
        logger.exception("incident_logged receiver failed")

    if created:
        logger.error(
            "New incident %s [%s] %s @ %s",
            incident.incident_id, kind, exception_type, affected_method,
        )
    else:
        logger.warning(
            "Incident %s recurred (x%d) [%s] %s @ %s",
            incident.incident_id, incident.calls_before_closure, kind,
            exception_type, affected_method,
        )

    return incident, created


def log_exception(request, exception):
    """Record an unhandled exception escaping a view. Returns (incident, created)."""
    return log_incident(
        kind=IncidentKind.EXCEPTION,
        exception_type=type(exception).__name__,
        affected_method=_affected_method(request),
        message=str(exception) or type(exception).__name__,
        traceback_text=traceback.format_exc(),
    )


def log_slow_response(request, duration: float, threshold: float):
    """Record a request whose duration exceeded ``threshold`` seconds."""
    return log_incident(
        kind=IncidentKind.SLOW_RESPONSE,
        exception_type='SlowResponse',
        affected_method=_affected_method(request),
        message=(
            f"Response took {duration:.2f}s "
            f"(threshold {threshold:.2f}s)"
        ),
    )


def resolve_method(affected_method: str, kind: str | None = None):
    """
    Close every open incident for ``affected_method`` (optionally filtered by
    ``kind``). Returns the list of incidents that were closed.
    """
    qs = monitoring_table.objects.filter(
        affected_method=_clip(affected_method, METHOD_MAX),
        status=IncidentStatus.OPEN,
    )
    if kind is not None:
        qs = qs.filter(kind=kind)

    now = timezone.now()
    resolved = []
    for incident in qs:
        incident.status = IncidentStatus.CLOSED
        incident.closed_at = now
        incident.save(update_fields=['status', 'closed_at'])
        resolved.append(incident)
        try:
            incident_resolved.send(sender=monitoring_table, incident=incident)
        except Exception:  # pragma: no cover
            logger.exception("incident_resolved receiver failed")

    return resolved
