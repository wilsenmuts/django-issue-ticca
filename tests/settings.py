"""Test configuration for django-issue-ticca.

Used by CI and by ``pytest`` (see ``[tool.pytest.ini_options]`` in pyproject.toml).
It is intentionally minimal: just enough to exercise the app's checks, models,
views and middleware against an in-memory SQLite database.
"""

SECRET_KEY = "django-issue-ticca-tests"
DEBUG = True
ALLOWED_HOSTS = ["*"]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_issue_ticca",
]

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
