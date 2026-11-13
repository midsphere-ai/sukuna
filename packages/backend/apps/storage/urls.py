"""URL configuration for the storage app, mapping API routers to the memory namespace."""

from django.urls import path

from apps.storage.views import memory_api, memory_public_api, storage_stream_api

app_name = "memory"
urlpatterns = [
    path(f"{app_name}/", memory_api.urls),
    path(f"{app_name}/", memory_public_api.urls),
    path(f"{app_name}/", storage_stream_api.urls),
]
