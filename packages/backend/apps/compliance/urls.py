"""URL configuration for the compliance app."""

from django.urls import path

from apps.compliance.api import compliance_api

app_name = "compliance"
urlpatterns = [
    path("compliance/", compliance_api.urls),
]
