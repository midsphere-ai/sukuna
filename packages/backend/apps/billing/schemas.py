"""Ninja API schemas for billing request and response serialization."""

from ninja import ModelSchema, NinjaAPI, Schema

from apps.billing.models import SubscriptionPlan, UserSubscription
from apps.users.adapters import NinjaAuthAdapter

api = NinjaAPI()
authenticated_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="billing")


class CreateOrderRequest(Schema):
    """Request schema for creating a new subscription order."""

    plan_id: str


class FetchPlanRequest(Schema):
    """Request schema for fetching a subscription plan by title."""

    title: str


class SubscriptionPlanModelSchema(ModelSchema):
    """Model schema for serializing SubscriptionPlan instances."""

    class Meta:
        model = SubscriptionPlan
        fields = "__all__"


class UserSubscriptionModelSchema(ModelSchema):
    """Model schema for serializing UserSubscription instances with nested plan."""

    subscription_type: SubscriptionPlanModelSchema

    class Meta:
        model = UserSubscription
        fields = "__all__"
