# django-issue-ticca

[![PyPI version](https://img.shields.io/pypi/v/django-issue-ticca.svg)](https://pypi.org/project/django-issue-ticca/)
[![Python versions](https://img.shields.io/pypi/pyversions/django-issue-ticca.svg)](https://pypi.org/project/django-issue-ticca/)
[![Django versions](https://img.shields.io/badge/django-4.2%20%7C%205.2-092E20.svg)](https://pypi.org/project/django-issue-ticca/)
[![CI](https://github.com/wilsenmuts/django-issue-ticca/actions/workflows/ci.yml/badge.svg)](https://github.com/wilsenmuts/django-issue-ticca/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Support via Flutterwave](https://img.shields.io/badge/Support-Flutterwave-8a2be2.svg)](https://flutterwave.com/pay/reconnawdaq)

A reusable Django app for **tracking issues/incidents** and **health-checking a system**.

It gives you two things out of the box:

1. **An incident log** that records unhandled exceptions and slow responses, then
   de-duplicates them (one row per problem) and counts how many times they recur.
2. **A health-check endpoint** that aggregates every subsystem (database, Redis,
   RabbitMQ, Celery) into a single overall system status.

It is designed to be dropped into any Django (and optionally DRF) project with
minimal wiring, and to degrade gracefully when optional subsystems are absent.

It's **open source and community-driven** — the goal is to make monitoring Django
projects simple. Contributions of every kind are welcome; see
[Contributing](#contributing) to get started.

---

## Features

- 🧾 **Incident log** (`monitoring_table`) for exceptions and slow responses.
- 🆔 **Auto-generated incident ids** — `INC-YYYYMMDD-XXXXXXXX` (unique, sortable, human-readable).
- 🔁 **Log once, count recurrences** — the first time an issue is seen a row is created;
  every later occurrence increments `calls_before_closure` instead of inserting a new row.
- ✅ **Auto-close on recovery** — when the URL succeeds again (not slow, status < 500) the
  open incident is closed; a later failure opens a **new** incident.
- 🐌 **Slow-response logging** — requests slower than a configurable threshold (default **10s**)
  are recorded with the request URL as the affected method.
- ❤️ **Overall health endpoint** — aggregates `database`, `redis`, `rabbitmq`, `celery`
  and returns `healthy` / `unhealthy` with a per-component breakdown.
- 📈 **Hourly user stats** — unique users and request counts per hour for the last 7 days,
  with older rows pruned automatically whenever the stats endpoint is called.
- 🧩 **Optional DRF support** — a custom exception handler so DRF-caught 5xx errors are logged too.
- 📣 **Signals** — `incident_logged` / `incident_resolved` hooks for alerts and tickets.
- 🧷 **Self-logging exceptions** — subclass `TrackedException` and it records itself in the incident log.
- 🛠️ **Admin integration** — filtered/searchable incident list with a "close selected" action.

---

## Requirements

- Python 3.10+
- Django 4.2+ (developed against Django 5.2)
- Optional: `djangorestframework`, `redis`, `kombu`/`pika`, `celery`

---

## Installation

Install from PyPI:

```bash
pip install django-issue-ticca

# with optional integrations (DRF logging, Redis/Celery/RabbitMQ health checks)
pip install "django-issue-ticca[drf,redis,celery]"
```

Then add it to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ... other apps ...
    'django_issue_ticca',
]
```

Apply the migrations:

```bash
python manage.py migrate
```

> If your database already contains the `issue_ticca_*` tables (for example they were created
> earlier with `migrate --run-syncdb`), run `python manage.py migrate --fake-initial` so the
> initial migration does not try to re-create them.

---

## Wiring it up

### 1. Settings

```python
# settings.py
INSTALLED_APPS += ['django_issue_ticca']

MIDDLEWARE += [
    # ... your existing middleware ...
    'django_issue_ticca.middleware.ResponseTimeLoggingMiddleware',
    'django_issue_ticca.middleware.ExceptionLoggingMiddleware',
]
```

`ResponseTimeLoggingMiddleware` measures request duration and closes resolved incidents.
`ExceptionLoggingMiddleware` records uncaught exceptions. The order between the two does not
matter, but they must sit outside your views — and **after**
`django.contrib.auth.middleware.AuthenticationMiddleware` so `request.user` is available for
hourly user stats.

### 2. URLs

Mount the app's routes wherever you like:

```python
# urls.py
from django.urls import include, path

urlpatterns = [
    path('issue-ticca/', include('django_issue_ticca.urls')),
]
```

### 3. Optional configuration

All settings are optional and can be written either as a namespaced dict or with flat names:

```python
# settings.py
ISSUE_TICCA = {
    'SLOW_RESPONSE_THRESHOLD': 10.0,   # seconds; 0 or None disables slow-response logging
    'AUTO_RESOLVE_ON_SUCCESS': True,   # close open incidents when the URL is healthy again
    'ENABLED': True,                   # master on/off switch for the middlewares
    'TRACK_HOURLY_USERS': True,        # record unique users / requests per hour
    'HOURLY_STATS_RETENTION_DAYS': 7,  # keep 7 days; older rows pruned on endpoint call

    # Optional subsystem connection details (used by the health checks)
    'REDIS_URL': 'redis://localhost:6379/0',
    'RABBITMQ_URL': 'amqp://guest:guest@localhost:5672//',
    'CELERY_APP': 'myproject.celery.app',
}
```

Flat equivalent (any of these override the defaults):

```python
ISSUE_TICCA_SLOW_RESPONSE_THRESHOLD = 10.0
ISSUE_TICCA_AUTO_RESOLVE_ON_SUCCESS = True
```

| Setting | Default | Purpose |
| --- | --- | --- |
| `SLOW_RESPONSE_THRESHOLD` | `10.0` | Seconds before a request is logged as slow. `0`/`None` disables. |
| `AUTO_RESOLVE_ON_SUCCESS` | `True` | Close open incidents for a URL when it succeeds and is not slow. |
| `ENABLED` | `True` | Master switch for the logging middlewares. |
| `TRACK_EXCEPTIONS` | `True` | Let `TrackedException` subclasses record themselves on creation. |
| `TRACK_HOURLY_USERS` | `True` | Record one row per user per hour (unique users / requests). |
| `HOURLY_STATS_RETENTION_DAYS` | `7` | Days of hourly stats to keep; older rows are pruned on endpoint call. |
| `REDIS_URL` | `None` | Redis URL for the Redis health check (falls back to a Redis cache backend). |
| `RABBITMQ_URL` | `None` | Broker URL (falls back to `CELERY_BROKER_URL` / `BROKER_URL`). |
| `CELERY_APP` | `None` | Dotted path to a Celery app (falls back to Celery's `current_app`). |

### 4. Optional: DRF exception logging

DRF catches most exceptions itself and turns them into responses, so they never reach Django's
`process_exception`. To record those too, install the handler:

```python
REST_FRAMEWORK = {
    'EXCEPTION_HANDLER':
        'django_issue_ticca.tracking.exceptions.issue_ticca_exception_handler',
}
```

Only server-side failures (HTTP 5xx) are recorded, so expected `4xx` validation responses do
not flood the incident log.

---

## Endpoints

| Method | URL | Description |
| --- | --- | --- |
| `GET` | `/issue-ticca/health/` | **Overall system health** (aggregated). `200` healthy, `503` unhealthy. |
| `GET` | `/issue-ticca/health/?component=database` | Health for a single component. |
| `GET` | `/issue-ticca/health/?component=redis,celery` | Health for several components. |
| `GET` | `/issue-ticca/database-probe/` | Database-only check (`200`/`503`). |
| `GET` | `/issue-ticca/monitoring/` | Paginated incident list. Filters: `status`, `kind`, `method`, `page`, `page_size`. |
| `GET` | `/issue-ticca/monitoring/open-by-type/` | Open incident counts grouped by exception type. |
| `GET` | `/issue-ticca/monitoring/open-by-method/` | Open incident counts grouped by affected method (URL). |
| `GET` | `/issue-ticca/stats/users/` | In-process active-user counters. |
| `GET` | `/issue-ticca/stats/users/hourly/` | Unique users per hour for the last 7 days. Use `?days=1..90` for a shorter window. |

Example health response:

```json
{
  "status": "healthy",
  "components": {
    "database": { "status": "healthy", "latency_ms": 3.1 },
    "redis":    { "status": "ok", "latency_ms": 1.4 },
    "rabbitmq": { "status": "ok", "latency_ms": 2.0 },
    "celery":   { "status": "ok", "workers_online": 2, "latency_ms": 5.6 }
  },
  "failing": [],
  "summary": { "ok": 3, "healthy": 1 },
  "latency_ms": 12.3,
  "timestamp": "2026-09-29T10:00:00+00:00"
}
```

A component that is absent or unconfigured reports `not_configured` and does **not** make the
system unhealthy. Only a real `error` does. Status words are normalised, so `healthy` counts
as `ok` and `unhealthy`/`failed` as `error`.

### Hourly user stats

`GET /issue-ticca/stats/users/hourly/` (optionally `?days=1..90`) returns unique users and
request counts per hour for the retention window:

```json
{
  "retention_days": 7,
  "window": { "start": "2026-09-22T10:00:00+00:00", "end": "2026-09-29T10:41:00+00:00" },
  "pruned": 0,
  "totals": { "unique_users": 12, "requests": 340 },
  "buckets": [
    { "hour": "2026-09-29T09:00:00+00:00", "unique_users": 4, "requests": 21 },
    { "hour": "2026-09-29T10:00:00+00:00", "unique_users": 7, "requests": 33 }
  ]
}
```

`ActiveUserTrackingMiddleware` records one row per user per hour (with a request counter):
`u:<pk>` for authenticated users and `s:<session>` for anonymous ones. **Rows older than the
retention window are deleted on every call** and the number removed is returned as `pruned`,
so the table always stays trimmed to the last N days.

---

## How incidents work

The `monitoring_table` model records one row per open problem, keyed on
`(kind, exception_type, affected_method)` where `affected_method` is the request URL
(path only, so query strings are not stored).

```
1st failure  -> new row, status=open,  calls_before_closure=1
2nd failure  -> same row,              calls_before_closure=2
3rd failure  -> same row,              calls_before_closure=3
...          -> ...
next success -> row closed, status=closed, closed_at set
next failure -> NEW row (new incident_id)
```

Fields of note:

| Field | Meaning |
| --- | --- |
| `incident_id` | Auto-generated unique id (`INC-YYYYMMDD-XXXXXXXX`). |
| `kind` | `exception` or `slow_response`. |
| `exception_type` | Exception class name, or `SlowResponse`. |
| `affected_method` | The request URL (path). |
| `calls_before_closure` | Number of times the incident was seen before it was closed. |
| `status` / `closed_at` | Lifecycle state and when it was resolved. |
| `last_noticed_at` | When the incident was most recently seen. |

`exception_traceback` stores the full traceback (as text); `exception_message` stores a short
summary.

### Signals

```python
from django.dispatch import receiver
from django_issue_ticca.signals import incident_logged, incident_resolved

@receiver(incident_logged)
def on_incident(sender, incident, created, **kwargs):
    if created:
        notify_slack(incident)

@receiver(incident_resolved)
def on_resolved(sender, incident, **kwargs):
    close_ticket(incident)
```

### Custom tracked exceptions

Subclass `TrackedException` and the exception records itself in the incident log as soon as it
is created — nothing extra to do in the `except` block:

```python
from django_issue_ticca.exceptions import TrackedException

class PaymentGatewayError(TrackedException):
    pass

raise PaymentGatewayError("gateway timeout", code="gw_timeout", context={"order": 42})
```

Each instance records **exactly once**, so re-raising or re-catching it doesn't double count.
Repeated failures increment the same incident's `calls_before_closure`, and the incident is
closed when the URL is healthy again. The affected method is the current request's URL when
available, otherwise the code location that raised it.

Already have exceptions you don't control? Record them from an `except` block:

```python
try:
    third_party.call()
except Exception as exc:
    TrackedException.capture(exc)   # no-op if it already recorded itself
    raise
```

| Argument | Meaning |
| --- | --- |
| `code` | Short machine-readable code (included in the incident message). |
| `context` | Dict of extra details (included in the incident message). |
| `log=False` | Don't record on creation; call `exc.record()` yourself later. |

Disable globally with `ISSUE_TICCA["TRACK_EXCEPTIONS"] = False` (or `ENABLED = False`).

---

## Package layout

```
src/django_issue_ticca/
├── admin.py            # Admin for probes + incidents (with "close selected" action)
├── apps.py             # AppConfig (loads signals)
├── conf.py             # Settings accessors (ISSUE_TICCA[...] and ISSUE_TICCA_*)
├── context.py          # Per-thread current request (for URL attribution)
├── exceptions.py       # TrackedException (self-logging exception base class)
├── incidents.py        # log_incident / log_exception / log_slow_response / resolve_method
├── middleware.py       # ActiveUserTracking, ExceptionLogging, ResponseTimeLogging
├── models.py           # database_probe, monitoring_table, generate_incident_id
├── signals.py          # incident_logged, incident_resolved
├── stats.py            # hourly user stats (record / prune / report)
├── urls.py             # Routes (health, monitoring, stats)
├── views.py            # SystemHealthView, HourlyUserStatsView and reporting views
├── check/              # database / redis / rabbitmq / celery checks + health aggregator
├── migrations/         # 0001_initial, 0002_hourly_user_stat
└── tracking/           # Isolated SQLite active-user store + DRF exception handler
```

---

## Development & testing

The repository ships the app plus a minimal test project under `tests/` (no `manage.py`).
Create a virtualenv, install the dev extras, and run the suite:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export DJANGO_SETTINGS_MODULE=tests.settings
export PYTHONPATH=src

python -m django test django_issue_ticca
pytest                            # optional, uses the same settings
```

Useful checks:

```bash
python -m django makemigrations --check --dry-run   # migrations match the models
python -m django check                              # system checks
ruff check src tests                                # lint
```

---

## Releasing to PyPI

The package is published as **`django-issue-ticca`** using [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(no API tokens or secrets). One-time setup on PyPI:

1. Create the project on PyPI, then **Publishing → Add a new pending publisher**:
   - **Owner:** your GitHub username/org
   - **Repository:** `django-issue-ticca`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`

To cut a release:

```bash
# 1. Bump the version (single source of truth)
#    src/django_issue_ticca/__init__.py -> __version__ = "0.2.0"
# 2. Commit and push
# 3. Tag and publish a GitHub Release
git tag v0.2.0
git push origin v0.2.0
```

> **PyPI never allows re-uploading a version.** If a publish run fails after some files were
> uploaded, don't retry the same version — bump `__version__` and release again.

Publishing a GitHub Release triggers `.github/workflows/publish.yml`, which builds the sdist
and wheel and uploads them to PyPI. `CI` (`.github/workflows/ci.yml`) lints, runs system
checks, verifies migrations are current, and runs the tests on every push/PR.

Manual/local build (optional):

```bash
python -m pip install build twine
python -m build            # creates dist/*.tar.gz and dist/*.whl
python -m twine check dist/*
```

---

## Contributing

`django-issue-ticca` is an **open source project with one goal: making monitoring simple in
Django projects.** It grows through community contributions, and there are many ways to help —
you don't have to be a Django expert.

- 🐛 **Report bugs** and 💡 **suggest features** by opening an issue.
- 📖 **Improve the docs** — fixes, examples, and usage recipes are very welcome.
- 🔌 **Add a health check** — implement a defensive check in `src/django_issue_ticca/check/`
  (MongoDB, S3, SMTP, Elasticsearch…) and register it in `check/health.py`.
- 🔔 **Build integrations** — hook `incident_logged` / `incident_resolved` to Slack, email, or
  your ticketing system.
- 🧪 **Write tests**, triage issues, or ⭐ **star and share** the project.

The full guide — development setup, coding guidelines, adding a health check, and the PR
checklist — lives in **[CONTRIBUTING.md](CONTRIBUTING.md)**. In short:

```bash
git clone https://github.com/wilsenmuts/django-issue-ticca.git
cd django-issue-ticca
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export DJANGO_SETTINGS_MODULE=tests.settings
export PYTHONPATH=src

python -m django test django_issue_ticca   # tests
ruff check src tests                       # lint
```

New here? Look for issues labelled **good first issue**, or just open an issue and ask —
questions are welcome. Please be respectful and constructive; we want this to be a friendly
place to contribute.

---

## Support the project

If this package saves you time, you can support continued development here:

[![Support via Flutterwave](https://img.shields.io/badge/Support-Flutterwave-8a2be2.svg)](https://flutterwave.com/pay/reconnawdaq)

**[https://flutterwave.com/pay/reconnawdaq](https://flutterwave.com/pay/reconnawdaq)**

Thank you! ❤️

---

## License

Released under the [MIT License](LICENSE).
