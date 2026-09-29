"""
stats.py

Hourly active-user statistics.

One row is stored per ``(hour, user)`` in the ``hourly_user_stat`` table, so the
stats endpoint can report unique users and request volume per hour. Rows older
than the retention window (default 7 days) are pruned whenever the endpoint is
called -- see ``prune_hourly_stats``.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

from .conf import get_setting
from .models import hourly_user_stat

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 7


def retention_days() -> int:
    """Return the configured retention window in days (always >= 1)."""
    value = get_setting('HOURLY_STATS_RETENTION_DAYS', DEFAULT_RETENTION_DAYS)
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS
    return max(1, days)


def hour_bucket(when=None):
    """Truncate a datetime down to the start of its hour."""
    when = when or timezone.now()
    return when.replace(minute=0, second=0, microsecond=0)


def user_key(user, session_key=None) -> str:
    """Stable identifier for a user: ``u:<pk>`` when signed in, else ``s:<session>``."""
    if user is not None and getattr(user, 'is_authenticated', False):
        return f'u:{user.pk}'
    if session_key:
        return f's:{session_key}'
    return 's:anonymous'


def record_hourly_user(user, session_key=None, when=None) -> None:
    """
    Increment the ``(hour, user)`` bucket for the current hour.

    Best-effort: failures are logged and swallowed so tracking can never break
    a request. Disable with ``ISSUE_TICCA["TRACK_HOURLY_USERS"] = False``.
    """
    if not get_setting('TRACK_HOURLY_USERS', True):
        return

    when = when or timezone.now()
    bucket = hour_bucket(when)
    key = user_key(user, session_key)[:128]

    try:
        with transaction.atomic():
            _obj, created = hourly_user_stat.objects.get_or_create(
                hour_start=bucket,
                user_key=key,
                defaults={'requests': 1, 'last_seen_at': when},
            )
            if not created:
                hourly_user_stat.objects.filter(
                    hour_start=bucket, user_key=key
                ).update(requests=F('requests') + 1, last_seen_at=when)
    except IntegrityError:
        # A concurrent request created the row first; just increment it.
        try:
            hourly_user_stat.objects.filter(
                hour_start=bucket, user_key=key
            ).update(requests=F('requests') + 1, last_seen_at=when)
        except Exception:
            logger.exception("Failed to increment hourly user stat")
    except Exception:
        logger.exception("Failed to record hourly user stat")


def prune_hourly_stats(days=None) -> int:
    """Delete hourly rows older than the retention window. Returns rows deleted."""
    days = retention_days() if days is None else max(1, int(days))
    cutoff = hour_bucket() - timedelta(days=days)
    deleted, _details = hourly_user_stat.objects.filter(hour_start__lt=cutoff).delete()
    return deleted


def hourly_user_stats(days=None, prune=True) -> dict:
    """
    Return unique users per hour (and request counts) for the retention window.

    When ``prune`` is True (default) rows older than the window are deleted
    first, so calling the endpoint keeps the table trimmed to the last N days.
    """
    days = retention_days() if days is None else max(1, int(days))

    pruned = prune_hourly_stats(days) if prune else 0

    now = timezone.now()
    current_hour = hour_bucket(now)
    start = current_hour - timedelta(days=days)

    window = hourly_user_stat.objects.filter(
        hour_start__gte=start, hour_start__lte=current_hour
    )

    buckets = [
        {
            'hour': row['hour_start'].isoformat(),
            'unique_users': row['unique_users'],
            'requests': row['requests'],
        }
        for row in (
            window.values('hour_start')
            .annotate(unique_users=Count('user_key'), requests=Sum('requests'))
            .order_by('hour_start')
        )
    ]

    return {
        'retention_days': days,
        'window': {'start': start.isoformat(), 'end': now.isoformat()},
        'pruned': pruned,
        'totals': {
            'unique_users': window.values('user_key').distinct().count(),
            'requests': sum(bucket['requests'] for bucket in buckets),
        },
        'buckets': buckets,
    }
