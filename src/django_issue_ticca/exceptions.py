"""
exceptions.py

``TrackedException`` -- an ``Exception`` subclass that records itself in the
incident log as soon as it is created.

Subclass it and raise it anywhere in your project::

    from django_issue_ticca.exceptions import TrackedException

    class PaymentGatewayError(TrackedException):
        pass

    raise PaymentGatewayError("gateway timeout", code="gw_timeout", context={"order": 42})

Each instance records **exactly once** (guarded by ``_incident_logged``), so
re-raising or re-catching it does not double-count. Recording goes through the
same incident table as the middleware, so repeated failures increment
``calls_before_closure`` on one incident and it is closed once the URL is
healthy again.

You can also record exceptions raised by code you don't control::

    try:
        third_party_call()
    except Exception as exc:
        TrackedException.capture(exc)   # no-op if it already recorded itself
        raise

Recording can be disabled globally with ``ISSUE_TICCA["TRACK_EXCEPTIONS"] = False``
(or ``ISSUE_TICCA["ENABLED"] = False``), or per instance with ``log=False``.
"""

import logging
import traceback

from .conf import get_setting
from .context import get_current_request
from .incidents import log_incident
from .models import IncidentKind

logger = logging.getLogger(__name__)

UNKNOWN_METHOD = 'unknown'


def _request_path():
    """The path of the request being handled in this thread, if any."""
    request = get_current_request()
    if request is None:
        return None
    path = getattr(request, 'path', None)
    if not path:
        try:
            path = request.get_full_path()
        except Exception:
            path = None
    return path or None


def _caller_location(skip_file: str) -> str:
    """Return ``file:line`` for the first stack frame outside this module."""
    for frame in reversed(traceback.extract_stack()[:-1]):
        if frame.filename != skip_file:
            return f"{frame.filename}:{frame.lineno}"
    return UNKNOWN_METHOD


def _should_record() -> bool:
    return bool(get_setting('ENABLED', True) and get_setting('TRACK_EXCEPTIONS', True))


class TrackedException(Exception):
    """
    An ``Exception`` that records itself in the incident log when created.

    Subclass it, then raise it like any other exception::

        class InventoryError(TrackedException):
            pass

        raise InventoryError("out of stock", code="no_stock")
    """

    #: Incident kind used when recording.
    incident_kind = IncidentKind.EXCEPTION

    def __init__(self, message='', *, code=None, context=None, log=None):
        super().__init__(message)
        self.message = str(message) if message else type(self).__name__
        self.code = code
        self.context = dict(context) if context else {}
        self._caller = _caller_location(__file__)
        self._traceback = ''.join(traceback.format_stack()[:-1])
        self._incident_logged = False
        self._incident = None

        if _should_record() if log is None else log:
            self.record()

    # ------------------------------------------------------------------ public
    def affected_method(self) -> str:
        """URL of the current request, else the code location that raised this."""
        return _request_path() or self._caller or UNKNOWN_METHOD

    def incident_message(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"code={self.code}")
        if self.context:
            parts.append(f"context={self.context}")
        return ' | '.join(parts)

    def traceback_text(self) -> str:
        """Best-effort traceback captured where the exception was created."""
        return self._traceback

    def record(self):
        """Record this exception in the incident log. Idempotent."""
        if self._incident_logged:
            return self._incident
        try:
            incident, _created = log_incident(
                kind=self.incident_kind,
                exception_type=type(self).__name__,
                affected_method=self.affected_method(),
                message=self.incident_message(),
                traceback_text=self.traceback_text(),
            )
            self._incident = incident
            self._incident_logged = True
        except Exception:
            # Recording must never mask the original exception.
            logger.exception("TrackedException failed to record an incident")
        return self._incident

    #: Alias for when the class is used inside an ``except`` block.
    log = record

    @classmethod
    def capture(cls, exception, *, affected_method=None):
        """
        Record an arbitrary exception, e.g. inside an ``except Exception`` block.

        A no-op when ``exception`` is a ``TrackedException`` that already
        recorded itself. Returns the incident, or ``None`` on failure.
        """
        if getattr(exception, '_incident_logged', False):
            return getattr(exception, '_incident', None)

        try:
            incident, _created = log_incident(
                kind=cls.incident_kind,
                exception_type=type(exception).__name__,
                affected_method=(
                    affected_method
                    or _request_path()
                    or _caller_location(__file__)
                ),
                message=str(exception) or type(exception).__name__,
                traceback_text=traceback.format_exc(),
            )
        except Exception:
            logger.exception("TrackedException.capture failed to record an incident")
            return None
        return incident

    def __str__(self):
        return self.incident_message()
