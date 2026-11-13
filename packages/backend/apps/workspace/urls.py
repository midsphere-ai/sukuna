"""URL routing for workspace public and authenticated API endpoints."""

from django.urls import path

from apps.workspace.invitation_api import invitation_api
from apps.workspace.notification_api import notification_api
from apps.workspace.org_api import org_api
from apps.workspace.scim_api import scim_api
from apps.workspace.template_api import template_api
from apps.workspace.views import api, authenticated_api

app_name = "workspace"
urlpatterns = [
    path(f"{app_name}/", api.urls),
    path(f"{app_name}/", authenticated_api.urls),
    path(f"{app_name}/organizations/", org_api.urls),
    path(f"{app_name}/organizations/templates/", template_api.urls),
    path(f"{app_name}/invitations/", invitation_api.urls),
    path("notifications/", notification_api.urls),
    path("scim/v2/", scim_api.urls),
]
