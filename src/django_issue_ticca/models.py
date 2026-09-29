"""
models.py

Two models:

* ``database_probe``  - a tiny table the DB health check round-trips against.
* ``monitoring_table`` - the incident log: exceptions and slow responses.

Incident lifecycle (see ``incidents.py``):
  - one open row per ``(kind, exception_type, affected_method)``,
  - ``calls_before_closure`` counts occurrences while the incident is open,
  - the row is closed once the URL succeeds again.

Note: model class names are kept in their original snake_case form for
backwards compatibility with existing imports/migrations. New code should
prefer PascalCase (``MonitoringTable``); a rename is safe as long as
``db_table`` is preserved.
"""

import uuid

from django.db import models
from django.utils import timezone


def generate_incident_id() -> str:
    """
    Return a unique, sortable, human-readable incident id.

    Format: ``INC-YYYYMMDD-XXXXXXXX`` (8 upper-case hex chars from a UUID4).
    Used as the ``default`` for ``monitoring_table.incident_id`` so ids are
    generated automatically on create.
    """
    return f"INC-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


class IncidentKind(models.TextChoices):
    EXCEPTION = 'exception', 'Exception'
    SLOW_RESPONSE = 'slow_response', 'Slow response'


class IncidentStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    CLOSED = 'closed', 'Closed'


class MonitoringTableManager(models.Manager):
    """Query helpers for the incident log."""

    def open(self):
        return self.get_queryset().filter(status=IncidentStatus.OPEN)

    def closed(self):
        return self.get_queryset().filter(status=IncidentStatus.CLOSED)

    def for_method(self, affected_method: str):
        return self.get_queryset().filter(affected_method=affected_method)


class database_probe(models.Model):
    """A single row the database health check writes and reads back."""

    probe_name = models.CharField(max_length=100, db_index=True)
    probe_status = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.probe_name

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Database Probe'
        verbose_name_plural = 'Database Probes'
        db_table = 'issue_ticca_database_probe_x'


class monitoring_table(models.Model):
    """Incident log for exceptions and slow responses."""

    kind = models.CharField(
        max_length=20,
        choices=IncidentKind.choices,
        default=IncidentKind.EXCEPTION,
        db_index=True,
    )
    exception_type = models.CharField(max_length=200, db_index=True)
    # The affected "method" is the request URL (path only, no query string).
    affected_method = models.CharField(max_length=255, db_index=True)
    exception_message = models.CharField(max_length=500, blank=True, default='')
    incident_id = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        default=generate_incident_id,
    )
    status = models.CharField(
        max_length=20,
        choices=IncidentStatus.choices,
        default=IncidentStatus.OPEN,
        db_index=True,
    )
    exception_traceback = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    last_noticed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    #: Number of times the incident was seen before it was closed.
    calls_before_closure = models.IntegerField(default=0)

    objects = MonitoringTableManager()

    def __str__(self):
        return (
            f"[{self.incident_id}] {self.get_kind_display()}: "
            f"{self.exception_type} @ {self.affected_method} ({self.status})"
        )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Monitoring Table'
        verbose_name_plural = 'Monitoring Tables'
        db_table = 'issue_ticca_monitoring_table_x'

    # ------------------------------------------------------------------ helpers
    @property
    def is_open(self) -> bool:
        return self.status == IncidentStatus.OPEN

    def occurrence(self) -> int:
        """Increment the occurrence counter and stamp ``last_noticed_at``."""
        self.calls_before_closure = (self.calls_before_closure or 0) + 1
        self.last_noticed_at = timezone.now()
        self.save(update_fields=['calls_before_closure', 'last_noticed_at'])
        return self.calls_before_closure

    def close(self):
        """Close the incident (idempotent)."""
        if self.status == IncidentStatus.CLOSED:
            return self
        self.status = IncidentStatus.CLOSED
        self.closed_at = timezone.now()
        self.save(update_fields=['status', 'closed_at'])
        return self


class hourly_user_stat(models.Model):
    """
    One row per ``(hour, user)``.

    Each row counts how many requests a user made during that hour, which lets
    the stats endpoint report unique users and request volume per hour over the
    retention window (default 7 days). Older rows are pruned whenever the
    hourly stats endpoint is called.
    """

    hour_start = models.DateTimeField()
    user_key = models.CharField(max_length=128)
    requests = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.hour_start:%Y-%m-%d %H:00} {self.user_key} ({self.requests})"

    class Meta:
        ordering = ['-hour_start']
        verbose_name = 'Hourly User Stat'
        verbose_name_plural = 'Hourly User Stats'
        db_table = 'issue_ticca_hourly_user_stat_x'
        constraints = [
            models.UniqueConstraint(
                fields=['hour_start', 'user_key'],
                name='issue_ticca_hourly_unique',
            ),
        ]

