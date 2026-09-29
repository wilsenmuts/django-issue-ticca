"""
signals.py

Lightweight hooks so host projects can react to incident lifecycle events
without patching the package (e.g. send a Slack alert, open a ticket).

Receivers are connected in ``AppConfig.ready()``; importing this module here
is just what makes the signals importable.
"""

from django.dispatch import Signal

#: Sent when a *new* incident row is created.  kwargs: ``incident``, ``created``.
incident_logged = Signal()

#: Sent when an open incident is closed.  kwargs: ``incident``.
incident_resolved = Signal()
