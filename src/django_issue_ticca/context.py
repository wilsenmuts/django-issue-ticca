"""
context.py

Per-thread access to the request currently being handled.

The tracking middleware stores the request here so code that isn't handed the
request directly (for example ``TrackedException``) can still attribute an
incident to the URL that triggered it.
"""

import threading

_local = threading.local()


def set_current_request(request) -> None:
    """Remember ``request`` as the current request for this thread."""
    _local.request = request


def get_current_request():
    """Return the current request for this thread, or ``None``."""
    return getattr(_local, 'request', None)


def clear_current_request() -> None:
    """Forget the current request for this thread."""
    _local.request = None
