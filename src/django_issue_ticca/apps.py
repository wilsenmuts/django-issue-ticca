from django.apps import AppConfig


class DjangoIssueTiccaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'django_issue_ticca'
    verbose_name = 'Django Issue Ticca'

    def ready(self):
        # Importing the module makes the incident signals importable/discoverable
        # by host projects that want to connect receivers.
        from . import signals  # noqa: F401
