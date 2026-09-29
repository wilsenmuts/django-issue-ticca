"""
middleware.py

Contains:
  - TrackingStore lifecycle helpers (start_store / get_store).
  - UserCounter: in-process, thread-safe counter for fast local stats.
  - ActiveUserTrackingMiddleware: records enter/exit for both Django and DRF.
  - ExceptionLoggingMiddleware: logs any uncaught exception escaping a view and
    records it as an incident (logged once, counted while it recurs).
  - ResponseTimeLoggingMiddleware: records slow responses (> threshold) as
    incidents and closes incidents once a URL is healthy again.

Add both logging middlewares to ``MIDDLEWARE`` (order between them does not
matter, but they must sit *outside* the views):

    MIDDLEWARE = [
        # ...
        'django_issue_ticca.middleware.ActiveUserTrackingMiddleware',
        'django_issue_ticca.middleware.ResponseTimeLoggingMiddleware',
        'django_issue_ticca.middleware.ExceptionLoggingMiddleware',
    ]
"""

import logging
import threading
import time

from .conf import get_setting, slow_response_threshold
from .context import clear_current_request, set_current_request
from .incidents import log_exception, log_slow_response, resolve_method
from .stats import record_hourly_user
from .tracking.store import TrackingStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tracking store lifecycle
# ---------------------------------------------------------------------------
_store: TrackingStore | None = None


def get_store() -> TrackingStore | None:
    return _store


def start_store(path: str, app_name: str, domain: str) -> None:
    """Start the background SQLite writer once per process."""
    global _store
    if _store is None:
        _store = TrackingStore(path=path, app_name=app_name, domain=domain)
        _store.start()


# ---------------------------------------------------------------------------
# In-process counter (cheap, thread-safe, per-process only)
# ---------------------------------------------------------------------------
class UserCounter:
    """
    Tracks *active requests* by user type in this process only.

    This is a fast local view — for global numbers across processes read the
    SQLite store instead. Kept deliberately simple:
      - authenticated_requests / anonymous_requests: in-flight counts
      - authenticated_users: distinct pks seen (grows monotonically in a
        long-running process; reset via `reset()` if you need to)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.authenticated_requests = 0
        self.anonymous_requests = 0
        self.authenticated_users: set[int] = set()
        self.total_authenticated_seen = 0
        self.total_anonymous_seen = 0

    def enter(self, user, session_key: str | None = None) -> str:
        """Increment counters and return the category ('authenticated'|'anonymous')."""
        is_auth = user is not None and getattr(user, 'is_authenticated', False)
        with self._lock:
            if is_auth:
                self.authenticated_requests += 1
                self.authenticated_users.add(user.pk)
                self.total_authenticated_seen += 1
                return 'authenticated'
            self.anonymous_requests += 1
            self.total_anonymous_seen += 1
            return 'anonymous'

    def exit(self, category: str) -> None:
        with self._lock:
            if category == 'authenticated':
                self.authenticated_requests = max(0, self.authenticated_requests - 1)
            else:
                self.anonymous_requests = max(0, self.anonymous_requests - 1)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'active_authenticated_requests': self.authenticated_requests,
                'active_anonymous_requests': self.anonymous_requests,
                'active_unique_authenticated_users': len(self.authenticated_users),
                'total_authenticated_requests_seen': self.total_authenticated_seen,
                'total_anonymous_requests_seen': self.total_anonymous_seen,
            }

    def reset(self) -> None:
        with self._lock:
            self.authenticated_requests = 0
            self.anonymous_requests = 0
            self.authenticated_users.clear()
            self.total_authenticated_seen = 0
            self.total_anonymous_seen = 0


user_counter = UserCounter()


# ---------------------------------------------------------------------------
# Middleware 1: active user tracking
# ---------------------------------------------------------------------------
class ActiveUserTrackingMiddleware:
    """
    Records every request as enter/exit against:
      - the in-process `user_counter` (instant, local), and
      - the isolated SQLite store (cross-process, persistent).

    Works for plain Django views and DRF views. For DRF token/JWT requests,
    `request.user` is still AnonymousUser here (DRF authenticates inside the
    view), so `tracking.patches` reclassifies the request once DRF's
    `initial()` has run. See `tracking/patches.py`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Expose the request to thread-local helpers (e.g. TrackedException) so
        # incidents raised deeper in the stack can be attributed to this URL.
        set_current_request(request)
        store = get_store()

        # --- classify ------------------------------------------------------
        user = getattr(request, 'user', None)
        is_auth = user is not None and getattr(user, 'is_authenticated', False)
        user_id = user.pk if is_auth else None

        session = getattr(request, 'session', None)
        session_key = session.session_key if session is not None else None
        # Anonymous with no session yet: give the request its own bucket so
        # unrelated users don't get merged.
        if user_id is None and session_key is None:
            session_key = f'_nosession_{id(request)}'

        # --- enter ---------------------------------------------------------
        category = user_counter.enter(user, session_key)
        request._active_user_category = category

        # Persistent per-user hourly stats (best-effort; never breaks a request).
        record_hourly_user(user, session_key)

        if store is not None:
            store.enter(user_id, session_key)

        # --- dispatch ------------------------------------------------------
        try:
            return self.get_response(request)
        finally:
            # If DRF reclassified us, undo the anonymous side and close out
            # the authenticated side.
            swap = getattr(request, '_tracking_swap', None)
            if swap is not None and store is not None:
                # swap = (old_user_id, old_session_key, real_user_id)
                _, old_session_key, real_user_id = swap
                store.exit(None, old_session_key)
                store.exit(real_user_id, None)

                # Mirror in the in-process counter.
                user_counter.exit(category)
                user_counter.exit('authenticated')
            else:
                user_counter.exit(category)
                if store is not None:
                    store.exit(user_id, session_key)

            clear_current_request()


# ---------------------------------------------------------------------------
# Middleware 2: uncaught exception logger
# ---------------------------------------------------------------------------
class ExceptionLoggingMiddleware:
    """
    Logs every exception that escapes the view layer. Works for Django and DRF.

    The exception is written to the log **and** recorded in the incident table:
    a new row on first sight, then ``calls_before_closure`` is incremented on
    each recurrence (see ``incidents.log_incident``).

    Note: DRF catches most exceptions inside `dispatch` and turns them into
    Response objects, so they never reach `process_exception`. To record those
    too, install the custom DRF EXCEPTION_HANDLER in `tracking.exceptions`:

        REST_FRAMEWORK = {
            'EXCEPTION_HANDLER':
                'django_issue_ticca.tracking.exceptions.issue_ticca_exception_handler',
        }
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # Flag the request so ResponseTimeLoggingMiddleware skips slow-response
        # logging / auto-resolve for this failed request.
        request._issue_ticca_exception = True

        user = getattr(request, 'user', None)
        user_repr = (
            f'{user.__class__.__name__}(pk={user.pk})'
            if user is not None and getattr(user, 'is_authenticated', False)
            else 'AnonymousUser'
        )
        logger.exception(
            "Unhandled exception on %s %s | user=%s | ip=%s",
            request.method,
            request.get_full_path(),
            user_repr,
            self._client_ip(request),
            exc_info=exception,
        )

        if get_setting('ENABLED', True) and not getattr(exception, '_incident_logged', False):
            try:
                log_exception(request, exception)
            except Exception:
                # Never let bookkeeping break the response cycle.
                logger.exception("Failed to record incident for exception")

        # Return None so Django's default handling (500 page / DRF handler) runs.
        return None

    @staticmethod
    def _client_ip(request) -> str:
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        if xff:
            return xff.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')


# ---------------------------------------------------------------------------
# Middleware 3: slow-response logging + incident auto-resolution
# ---------------------------------------------------------------------------
class ResponseTimeLoggingMiddleware:
    """
    Measures how long each request takes and, when it exceeds the configured
    threshold (default 10s), records a slow-response incident against the URL.

    When a request completes successfully and is *not* slow, any open incidents
    for that URL are closed - this is what ends the "calls_before_closure" loop.

    Configure with::

        ISSUE_TICCA = {
            "SLOW_RESPONSE_THRESHOLD": 10.0,   # seconds; 0/None disables
            "AUTO_RESOLVE_ON_SUCCESS": True,
            "ENABLED": True,
        }
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not get_setting('ENABLED', True):
            return self.get_response(request)

        start = time.monotonic()
        response = self.get_response(request)
        duration = time.monotonic() - start

        # A raising view is handled by ExceptionLoggingMiddleware; don't treat
        # it as a slow-response success and don't auto-resolve.
        if getattr(request, '_issue_ticca_exception', False):
            return response

        try:
            self._record(request, response, duration)
        except Exception:
            logger.exception("Response-time logging failed")

        return response

    def _record(self, request, response, duration: float) -> None:
        threshold = slow_response_threshold()
        status_code = getattr(response, 'status_code', 200)
        failed = status_code >= 500

        if threshold is not None and duration >= threshold and not failed:
            log_slow_response(request, duration, threshold)
            return

        if (
            get_setting('AUTO_RESOLVE_ON_SUCCESS', True)
            and not failed
            and (threshold is None or duration < threshold)
        ):
            resolve_method(request.path)