"""
tracking/exceptions.py

Custom DRF exception handler so exceptions that DRF *catches itself* (i.e. that
never reach Django's ``process_exception``) are still recorded as incidents.

Wire it up with::

    REST_FRAMEWORK = {
        'EXCEPTION_HANDLER':
            'django_issue_ticca.tracking.exceptions.issue_ticca_exception_handler',
    }

Only server-side failures (HTTP 5xx) are recorded, so expected 4xx validation
responses don't flood the incident log.
"""

import logging

logger = logging.getLogger(__name__)

try:  # DRF is an optional dependency.
    from rest_framework.views import exception_handler as _drf_exception_handler
except ImportError:  # pragma: no cover
    _drf_exception_handler = None


def issue_ticca_exception_handler(exc, context):
    """
    Record 5xx exceptions as incidents, then defer to DRF's default handler.

    Returns the same response DRF would have produced.
    """
    response = _drf_exception_handler(exc, context) if _drf_exception_handler else None

    is_server_error = response is None or getattr(response, 'status_code', 500) >= 500
    if is_server_error:
        request = context.get('request') if isinstance(context, dict) else None
        if request is not None:
            try:
                from ..conf import get_setting
                from ..incidents import log_exception

                if get_setting('ENABLED', True) and not getattr(
                    exc, '_incident_logged', False
                ):
                    log_exception(request, exc)
                # Tell ResponseTimeLoggingMiddleware not to auto-resolve /
                # slow-log this request.
                request._issue_ticca_exception = True
            except Exception:  # never let bookkeeping mask the real error
                logger.exception("Failed to record DRF exception incident")

    return response
