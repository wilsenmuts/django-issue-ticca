"""Test configuration for django-issue-ticca.

Used by CI and by ``pytest`` (see ``[tool.pytest.ini_options]`` in pyproject.toml).
It is intentionally minimal: just enough to exercise the app's checks, models,
views and middleware against an in-memory SQLite database.
"""

from importlib.util import find_spec

SECRET_KEY = "django-issue-ticca-tests"
DEBUG = True
ALLOWED_HOSTS = ["*"]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF is an *optional* dependency, so only register it when it's importable.
# `pip install -e ".[dev]"` includes it, but a bare install must still work.
_HAS_DRF = find_spec("rest_framework") is not None

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_issue_ticca",
]

if _HAS_DRF:
    INSTALLED_APPS.append("rest_framework")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django_issue_ticca.middleware.ActiveUserTrackingMiddleware",
    "django_issue_ticca.middleware.ResponseTimeLoggingMiddleware",
    "django_issue_ticca.middleware.ExceptionLoggingMiddleware",
]

ROOT_URLCONF = "tests.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

STATIC_URL = "/static/"

# Signature protection is exercised by the tests, so configure an access key.
ISSUE_TICCA = {
    "ACCESS_KEY": "test-access-key",
}
