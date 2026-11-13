"""URL configuration for the blogs app, mounting authenticated and public API endpoints."""

from django.urls import path

from apps.blogs.views import api, authenticated_api

app_name = "cms"
urlpatterns = [
    path(f"{app_name}/", authenticated_api.urls),
    path(f"{app_name}/", api.urls),
]
