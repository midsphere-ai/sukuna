"""URL configuration for the agents app — maps to authenticated and public API instances."""

from django.urls import path

from apps.agents.views import agent_api, agent_public_api

app_name = "chat"
urlpatterns = [
    path(f"{app_name}/", agent_api.urls),
    path(f"{app_name}/", agent_public_api.urls),
]
