"""URL configuration for the billing app, routing to secured and unsecured API endpoints."""

from django.urls import path

from apps.billing.views import billing_api, unsecured_api

app_name = "billing"
urlpatterns = [
    path(f"{app_name}/", billing_api.urls),
    path(f"{app_name}/", unsecured_api.urls),
]
