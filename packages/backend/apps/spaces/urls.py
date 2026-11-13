"""URL configuration for the spaces API endpoints."""

from django.urls import path

from apps.spaces.views import spaces_api

app_name = "spaces"
urlpatterns = [
    path(f"{app_name}/", spaces_api.urls),
]
