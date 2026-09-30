# Contributing to django-issue-ticca

First off — thank you for considering a contribution! 🎉

`django-issue-ticca` is an **open source project with a single goal: making monitoring
simple in Django projects.** It grows through community contributions, and every kind of
help counts — code, docs, bug reports, ideas, or simply sharing it with other Django
developers.

This guide explains how to get involved. It's meant to be helpful, not gate-keeping:
if anything is unclear, just open an issue and ask.

## Ways to contribute

You don't need to be a Django expert to help.

- 🐛 **Report bugs** — open an issue with the traceback, your versions, and steps to reproduce.
- 💡 **Suggest a feature** — new health checks, notification backends, reporting endpoints…
- 📖 **Improve the docs** — README fixes, examples, and real-world usage recipes are very welcome.
- 🔌 **Add a health check** — implement a defensive check in `src/django_issue_ticca/check/`
  (e.g. MongoDB, S3, SMTP, Elasticsearch) and register it in `check/health.py`.
- 🔔 **Build integrations** — connect `incident_logged` / `incident_resolved` to Slack, email,
  PagerDuty, or your ticketing system.
- 🧪 **Write tests** — more coverage for the middleware, hourly stats, and checks.
- 📝 **Triage issues** — help reproduce and confirm reports.
- ⭐ **Spread the word** — star the repo and tell other Django developers about it.

All contributions are made under the project's [MIT License](LICENSE).

## Development setup

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/wilsenmuts/django-issue-ticca.git
cd django-issue-ticca

# 2. Create a virtualenv and install with dev dependencies
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Point Django at the test project shipped in this repo
export DJANGO_SETTINGS_MODULE=tests.settings
export PYTHONPATH=src
```

There is deliberately **no `manage.py`**: the app ships a tiny Django project under
`tests/` (`tests/settings.py`, `tests/urls.py`) so the suite runs with plain `django`.

## Running the checks and tests

Please run these before opening a pull request:

```bash
python -m django test django_issue_ticca      # test suite
python -m django check                        # system checks
python -m django makemigrations --check --dry-run   # migrations match the models
ruff check src tests                          # lint (line length 100)
pytest                                        # optional; uses the same settings
```

## Where things live

| Path | What it does |
| --- | --- |
| `models.py` | `database_probe`, `monitoring_table` (incidents), `hourly_user_stat`. |
| `exceptions.py` | `TrackedException` — an `Exception` subclass that logs itself when created. |
| `security.py` | Signature verification and the `sign_url` helper for the access key. |
| `incidents.py` | Incident lifecycle: `log_incident`, `log_exception`, `log_slow_response`, `resolve_method`. |
| `middleware.py` | Active-user tracking, exception logging, slow-response logging. |
| `stats.py` | Hourly user stats: `record_hourly_user`, `prune_hourly_stats`, `hourly_user_stats`. |
| `conf.py` | Settings accessors (`ISSUE_TICCA = {...}` and `ISSUE_TICCA_*`). |
| `views.py` / `urls.py` | Health + reporting endpoints. |
| `check/` | Subsystem health checks and the `health.py` aggregator. |
| `tracking/` | Isolated SQLite active-user store and the DRF exception handler. |

## Adding a new health check

Adding a subsystem is a great first contribution. Every check is a function that returns a
status dictionary and **never raises**.

1. Create `src/django_issue_ticca/check/<name>.py`:

```python
import time
from typing import Any


def check_mongodb() -> dict[str, Any]:
    start = time.perf_counter()

    url = ...  # read from settings (e.g. ISSUE_TICCA["MONGODB_URL"])
    if not url:
        return {
            "status": "not_configured",
            "detail": 'Set ISSUE_TICCA["MONGODB_URL"].',
        }

    try:
        import pymongo  # optional dependency
        client = pymongo.MongoClient(url, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "exception": type(exc).__name__,
        }
```

2. Register it in `check/health.py`:

```python
from .mongodb import check_mongodb

CHECKS = {
    # ...existing checks...
    "mongodb": check_mongodb,
}
```

3. Add tests in `src/django_issue_ticca/tests.py`.

### Status vocabulary

| Status | Meaning | Affects overall health? |
| --- | --- | --- |
| `ok` | Component is healthy. | No |
| `not_configured` | Missing URL or optional library — not a failure. | No |
| `skipped` | Intentionally not run. | No |
| `error` | A real failure. | **Yes** (system becomes `unhealthy`) |

Status words are normalised, so `healthy` counts as `ok` and `unhealthy`/`failed` count as
`error` (that's why `check_database()`'s `healthy`/`unhealthy` pair works).

If your check runs several sub-probes, list the failed ones in a `failing` array so the report
can name the probe as well as the error (`check_database()` does this):

```python
return {
    "status": "unhealthy",
    "checks": {
        "read": {"status": "error", "error": "...", "exception": "..."},
    },
    "failing": ["read"],       # -> failing_checks: ["<component>.read"]
    "skipped": [],
    "error": "read: OperationalError: ...",
}
```

Optional integrations must degrade to `not_configured` rather than raising, so the health
endpoint never fails just because a subsystem isn't installed.

## Coding guidelines

- **Python 3.9+**, **Django 4.2+**. Type-hint public functions.
- Match the surrounding style; keep lines to **100 characters** and run `ruff check src tests`.
- **Never let bookkeeping break a request.** Tracking code (middleware, hourly stats) must
  wrap its work in `try/except` and log failures instead of raising.
- Prefer **defensive checks** that return a status dict over raising exceptions.
- Keep **model and field conventions** consistent with existing models; preserve `db_table`
  names so upgrades don't move data.
- Keep **migrations in sync** with the models (`makemigrations --check` must report no changes).
- Update the **README** when you add or change settings, endpoints, or behaviour.

## Commit & pull request guidelines

1. Create a branch from `main`: `feature/…`, `fix/…`, or `docs/…`.
2. Keep each PR focused on **one** logical change.
3. Add or update tests for any behaviour change.
4. Run the checks and tests above and make sure they pass.
5. Update the README/docs when relevant.
6. Open the PR with a clear description of **what** changed and **why**. Reference issues with
   `Fixes #123` where applicable.

Write commit messages in the imperative mood, for example:

```
Add MongoDB health check
Fix KeyError when a check omits its status
Document hourly user stats endpoint
```

Be responsive to review comments — maintainers are volunteers, so a little patience goes a
long way. 🙏

## Reporting bugs

A good bug report includes:

- **What you did**, **what you expected**, and **what actually happened**.
- The **full traceback** (the part before "During handling of the above exception…" is enough).
- **Versions**: Python, Django, `django-issue-ticca`, database/broker, and whether DRF is used.
- Relevant **`ISSUE_TICCA` settings**.
- A **minimal reproduction** if you can produce one.

## Requesting features

Open an issue describing the problem you're trying to solve, not just the solution. Concrete
use cases help a lot. If you'd like to implement it yourself, say so and we'll help you land it.

## Good first issues

New to the project? These are usually approachable:

- Add a subsystem health check (MongoDB, S3, SMTP, Elasticsearch, Memcached…).
- Add a notification backend that listens to `incident_logged` / `incident_resolved`.
- Improve test coverage for the middleware or hourly stats.
- Improve the docs with a real-world example or recipe.

Look for issues labelled **good first issue**, or open your own and ask.

## Code of conduct

Be respectful, assume good intent, and keep discussion constructive and on-topic. Harassment,
personal attacks, and discriminatory language aren't tolerated. Maintainers may edit or remove
comments and reject contributions that violate this. If you experience or witness unacceptable
behaviour, please contact the maintainer.

## Support the project

If this package saves you time and you'd like to support continued development:

[![Support via Flutterwave](https://img.shields.io/badge/Support-Flutterwave-8a2be2.svg)](https://flutterwave.com/pay/reconnawdaq)

**[https://flutterwave.com/pay/reconnawdaq](https://flutterwave.com/pay/reconnawdaq)**

Thank you! ❤️
