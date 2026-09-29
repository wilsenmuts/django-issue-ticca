"""Root URLconf used by the test settings."""

from django.urls import include, path

urlpatterns = [
    path("", include("django_issue_ticca.urls")),
]
