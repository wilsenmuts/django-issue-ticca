"""
security.py

Shared-secret signature protection for the django-issue-ticca endpoints.

Configure an access key in your settings::

    ISSUE_TICCA = {"ACCESS_KEY": "a-long-random-string"}

Every request to an issue-ticca endpoint must then carry a signature header
whose value is ``hex(HMAC-SHA256(access_key, request_url))``, where
``request_url`` is the path **and** query string (no scheme/host)::

    GET /issue-ticca/monitoring/?page=2
    X-Issue-Ticca-Signature: 1f0c9a...   # hex HMAC-SHA256 of the line above

Callers can build the header with :func:`sign_url`::

    from django_issue_ticca.security import sign_url, signature_header

    url = "/issue-ticca/monitoring/?page=2"
    headers = {signature_header(): sign_url(url, key)}

Verification **fails closed**: if no access key is configured the endpoints
return ``503`` rather than serving incident data. Paths ending with one of the
``UNPROTECTED_PATHS`` suffixes skip verification (handy for health probes)::

    ISSUE_TICCA = {
        "ACCESS_KEY": "...",
        "UNPROTECTED_PATHS": ["/health/"],
    }
"""

import hashlib
import hmac
import logging
from functools import wraps

from django.http import JsonResponse

from .conf import get_setting

logger = logging.getLogger(__name__)

#: Header carrying the signature unless SIGNATURE_HEADER overrides it.
DEFAULT_SIGNATURE_HEADER = 'X-Issue-Ticca-Signature'


def access_key():
    """Return the configured access key, or ``None`` when unset."""
    key = get_setting('ACCESS_KEY')
    return str(key) if key else None


def signature_header() -> str:
    """Name of the header that carries the signature."""
    return get_setting('SIGNATURE_HEADER') or DEFAULT_SIGNATURE_HEADER


def signed_payload(request) -> str:
    """
    The string a caller must sign: the request URL (path + query string).

    Scheme and host are deliberately excluded so the signature stays valid
    behind proxies and load balancers.
    """
    return request.get_full_path()


def sign_url(url: str, key=None) -> str:
    """Return the hex signature for ``url`` (helper for callers and tests)."""
    key = key or access_key()
    if not key:
        raise ValueError('No issue-ticca access key is configured.')
    return hmac.new(
        key.encode('utf-8'), url.encode('utf-8'), hashlib.sha256
    ).hexdigest()


def sign_request(request, key=None) -> str:
    """Return the signature a caller should send for ``request``'s URL."""
    return sign_url(signed_payload(request), key)


def is_unprotected(path: str) -> bool:
    """True when ``path`` ends with one of the ``UNPROTECTED_PATHS`` suffixes."""
    suffixes = get_setting('UNPROTECTED_PATHS') or []
    return any(path.endswith(str(suffix)) for suffix in suffixes)


def provided_signature(request) -> str:
    """The signature the caller sent (empty string when absent)."""
    return (request.headers.get(signature_header()) or '').strip()


def verify_request(request):
    """
    Return ``None`` when the request may proceed, else a JSON error response.

    * ``503`` when no access key is configured (fail closed).
    * ``401`` when the signature is missing or does not match.
    """
    if is_unprotected(request.path):
        return None

    key = access_key()
    if not key:
        logger.error(
            "django-issue-ticca rejected %s: no ACCESS_KEY configured",
            request.path,
        )
        return JsonResponse(
            {'error': 'issue-ticca access key is not configured'},
            status=503,
        )

    provided = provided_signature(request)
    expected = sign_request(request, key)

    # Compare as bytes so non-ASCII input can't raise, and in constant time so a
    # signature can't be guessed byte by byte.
    if provided and hmac.compare_digest(
        provided.encode('utf-8'), expected.encode('utf-8')
    ):
        return None

    logger.warning(
        "django-issue-ticca rejected %s: invalid or missing signature",
        request.path,
    )
    return JsonResponse({'error': 'invalid or missing signature'}, status=401)


def signed(view):
    """
    Wrap a view so it only runs when the request carries a valid signature.

    Applied to every route in ``urls.py``; exemptions come from the
    ``UNPROTECTED_PATHS`` setting.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        rejection = verify_request(request)
        if rejection is not None:
            return rejection
        return view(request, *args, **kwargs)

    return wrapper
