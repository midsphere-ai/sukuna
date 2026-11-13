"""Ninja API views for the billing app.

Defines endpoints for subscription management, payment processing, refunds,
promo code validation, credit purchases, and customer support ticket CRUD operations.
"""

import logging
from datetime import datetime
from typing import Any, List, Optional, Union

from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.shortcuts import render
from ninja import Field, ModelSchema, NinjaAPI, Schema
from ninja.pagination import PageNumberPagination, paginate

from apps.billing.models import Payment, SubscriptionPlan, UserSubscription
from apps.billing.service import BillingService
from apps.users.adapters import NinjaAuthAdapter
from config.errors.common import NotFoundError
from config.errors.handlers import ErrorResponseSchema, register_error_handlers
from config.schemas.responses import ActionResponse

logger = logging.getLogger(__name__)


# Helper to get services
def get_billing_service():
    """Create and return a new BillingService instance."""
    return BillingService()


unsecured_api = NinjaAPI(urls_namespace="unsecured_billing")
billing_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="billing")

register_error_handlers(unsecured_api)
register_error_handlers(billing_api)


# Schemas
class SubscriptionPlanSchema(ModelSchema):
    """Response schema for subscription plan details."""

    class Config:
        model = SubscriptionPlan
        model_fields = ["id", "name", "tier", "price", "features", "is_active"]


class SubscriptionUsageSchema(Schema):
    """Response schema for subscription usage metrics across features."""

    tasks_remaining_week: Union[List[int], Any] = Field(
        ..., alias="Tasks Remaining This Week"
    )
    sandbox_time_remaining_month: Union[List[int], Any] = Field(
        ..., alias="Sandbox Time Remaining This Month"
    )
    addons_used: Union[List[int], Any] = Field(..., alias="Addons Used")
    mcp_servers_added: Union[List[int], Any] = Field(..., alias="MCP Servers Added")
    concurrent_tasks: Union[List[int], Any] = Field(..., alias="Concurrent Tasks")

    class Config:
        populate_by_name = True


class UserSubscriptionSchema(ModelSchema):
    """Response schema for user subscription with plan and usage details."""

    plan: Optional[SubscriptionPlanSchema]
    usage_schema: Optional[SubscriptionUsageSchema] = Field(None, alias="usage_schema")

    class Config:
        model = UserSubscription
        model_fields = [
            "id",
            "status",
            "start_date",
            "end_date",
            "auto_renew",
            "dodo_subscription_id",
        ]


class PaymentSchema(ModelSchema):
    """Response schema for payment record details."""

    class Config:
        model = Payment
        model_fields = [
            "id",
            "dodo_payment_id",
            "amount",
            "currency",
            "status",
            "created_at",
        ]


class ChangePlanRequest(Schema):
    """Request schema for changing a subscription plan."""

    plan_id: str
    immediate: bool = False


class RefundRequest(Schema):
    """Request schema for initiating a payment refund."""

    payment_id: str
    reason: str = ""


class CreateSubscriptionRequest(Schema):
    """Request schema for creating a new subscription."""

    plan_id: str


class SubscriptionCreationResponse(Schema):
    """Response schema returned after creating a Dodo checkout session."""

    checkout_url: Optional[str] = None
    subscription_id: Optional[str] = None
    message: Optional[str] = None


class FailedPaymentRetryResponse(Schema):
    """Response schema for a failed payment retry."""

    payment_link: Optional[str] = None
    message: str = ""


class GracePeriodStatus(Schema):
    """Response schema for subscription grace period status."""

    status: str
    days_remaining: Optional[int]
    in_grace_period: bool
    grace_ends: Optional[datetime]


class SubscriptionHistorySchema(Schema):
    """Response schema for subscription history events."""

    event_type: str
    plan_name: Optional[str] = None
    date: datetime
    details: str

    @staticmethod
    def resolve_event_type(obj):
        return obj.action

    @staticmethod
    def resolve_plan_name(obj):
        if obj.new_plan:
            return obj.new_plan.name
        if obj.old_plan:
            return obj.old_plan.name
        return None

    @staticmethod
    def resolve_date(obj):
        return obj.created_at

    @staticmethod
    def resolve_details(obj):
        if obj.old_plan and obj.new_plan:
            details = f"{obj.old_plan.name} \u2192 {obj.new_plan.name}"
            if obj.notes:
                details += f". {obj.notes}"
            return details
        return obj.notes or ""


# ═══════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════


@billing_api.get("/payment/success", auth=None)
def payment_success(request: WSGIRequest):
    """Render the payment success page."""
    return render(request, "billing/payment_success.html")


@billing_api.get("/plans", response=List[SubscriptionPlanSchema])
@paginate(PageNumberPagination)
def get_plans(request: WSGIRequest):
    """Get all active subscription plans."""
    service = get_billing_service()
    return service.get_subscription_plans()


@billing_api.get("/subscription", response=Optional[UserSubscriptionSchema])
def get_my_subscription(request: WSGIRequest):
    """Get current user's subscription."""
    service = get_billing_service()
    try:
        return service.get_user_subscription_plan(request)
    except NotFoundError:
        return None


@billing_api.post("/subscription/cancel-pending", response=ActionResponse)
def cancel_pending_subscription(request: WSGIRequest):
    """Cancel a pending subscription."""
    service = get_billing_service()
    return service.cancel_pending_subscription(request)


@billing_api.post("/subscription/change", response=ActionResponse)
def change_subscription_plan(request: WSGIRequest, data: ChangePlanRequest):
    """Change subscription plan."""
    service = get_billing_service()
    return service.change_subscription_plan(request, data.plan_id, data.immediate)


@billing_api.post(
    "/payment/retry",
    response={200: FailedPaymentRetryResponse, 404: ErrorResponseSchema},
)
def retry_failed_payment(request: WSGIRequest):
    """Retry a failed payment."""
    service = get_billing_service()
    return service.retry_failed_payment(request)


class CancelSubscription(Schema):
    """Request schema for cancelling a subscription."""

    immediate: bool = False


@billing_api.post("/subscription/cancel", response=ActionResponse)
def cancel_subscription(request: WSGIRequest, data: CancelSubscription):
    """Cancel active subscription."""
    service = get_billing_service()
    return service.cancel_subscription(request, immediate=data.immediate)


@billing_api.post("/subscription/pause", response=ActionResponse)
def pause_subscription(request: WSGIRequest):
    """Pause an active subscription."""
    service = get_billing_service()
    return service.pause_subscription(request)


@billing_api.post("/subscription/resume", response=ActionResponse)
def resume_subscription(request: WSGIRequest):
    """Resume a paused subscription."""
    service = get_billing_service()
    return service.resume_subscription(request)


@billing_api.post("/subscription/reactivate", response=ActionResponse)
def reactivate_subscription(request: WSGIRequest):
    """Reactivate a cancelled subscription."""
    service = get_billing_service()
    return service.reactivate_subscription(request)


@billing_api.post(
    "/subscription/create",
    response={200: SubscriptionCreationResponse, 400: ErrorResponseSchema},
)
def create_subscription(request: WSGIRequest, data: CreateSubscriptionRequest):
    """Create a new subscription."""
    service = get_billing_service()
    return service.create_subscription_with_checks(request, data.plan_id)


@billing_api.post("/refund", response=ActionResponse)
def request_refund(request: WSGIRequest, data: RefundRequest):
    """Request a refund for a payment."""
    service = get_billing_service()
    return service.request_refund(request, data.payment_id, data.reason)


@billing_api.get("/payments", response=List[PaymentSchema])
@paginate(PageNumberPagination)
def get_payment_history(request: WSGIRequest):
    """Get payment history."""
    service = get_billing_service()
    return service.get_payment_history(request)


@billing_api.get(
    "/subscription/grace-period",
    response={200: GracePeriodStatus, 404: ErrorResponseSchema},
)
def check_grace_period(request: WSGIRequest):
    """Check subscription grace period status."""
    service = get_billing_service()
    return service.check_subscription_grace_period(request)


@billing_api.get("/subscription/history", response=List[SubscriptionHistorySchema])
@paginate(PageNumberPagination)
def get_subscription_history(request: WSGIRequest):
    """Get subscription event history."""
    service = get_billing_service()
    return service.get_subscription_history(request)


@unsecured_api.post("/webhook", response=ActionResponse)
def dodo_webhook(request: WSGIRequest):
    """Dodo Payments webhook handler."""
    service = get_billing_service()
    return service.handle_dodo_webhook(request)


# ═══════════════════════════════════════════════════════════════════════
# Promo Code Validation
# ═══════════════════════════════════════════════════════════════════════


class ValidatePromoRequest(Schema):
    """Request schema for validating a promotional code."""

    code: str


class ValidatePromoResponse(Schema):
    """Response schema for promo code validation results."""

    valid: bool
    discount_percent: int
    message: str


@billing_api.post("/promo/validate", response=ValidatePromoResponse)
def validate_promo_code(request: WSGIRequest, data: ValidatePromoRequest):
    """Validate a promo code and return discount info."""
    service = get_billing_service()
    return service.validate_promo_code(data.code)


# ═══════════════════════════════════════════════════════════════════════
# Customer Support
# ═══════════════════════════════════════════════════════════════════════

from apps.billing.models import CustomerSupportTicket  # noqa: E402
from apps.billing.service import CustomerSupportService  # noqa: E402


def get_support_service():
    """Create and return a new CustomerSupportService instance."""
    return CustomerSupportService()


# Customer Support Schemas
class CustomerSupportTicketSchema(ModelSchema):
    """Response schema for customer support ticket details."""

    class Config:
        model = CustomerSupportTicket
        model_fields = ["id", "title", "message", "status", "created_at", "updated_at"]


class CreateTicketRequest(Schema):
    """Request schema for creating a new support ticket."""

    title: str
    message: str


class UpdateTicketRequest(Schema):
    """Request schema for updating an existing support ticket."""

    title: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None


# Customer Support Endpoints
@billing_api.post("/support/tickets", response=CustomerSupportTicketSchema)
def create_support_ticket(request: WSGIRequest, data: CreateTicketRequest):
    """Create a new support ticket."""
    service = get_support_service()
    return service.create_ticket(request, data.title, data.message)


@billing_api.get("/support/tickets", response=List[CustomerSupportTicketSchema])
@paginate(PageNumberPagination)
def list_support_tickets(request: WSGIRequest):
    """List all support tickets for the authenticated user."""
    service = get_support_service()
    return service.list_tickets(request)


@billing_api.get(
    "/support/tickets/{ticket_id}",
    response={200: CustomerSupportTicketSchema, 404: ErrorResponseSchema},
)
def get_support_ticket(request: WSGIRequest, ticket_id: str):
    """Get a specific support ticket."""
    service = get_support_service()
    return service.get_ticket(request, ticket_id)


@billing_api.put(
    "/support/tickets/{ticket_id}",
    response={200: CustomerSupportTicketSchema, 404: ErrorResponseSchema},
)
def update_support_ticket(
    request: WSGIRequest, ticket_id: str, data: UpdateTicketRequest
):
    """Update a support ticket."""
    service = get_support_service()
    return service.update_ticket(
        request, ticket_id, title=data.title, message=data.message, status=data.status
    )


@billing_api.delete(
    "/support/tickets/{ticket_id}",
    response={200: ActionResponse, 404: ErrorResponseSchema},
)
def delete_support_ticket(request: WSGIRequest, ticket_id: str):
    """Delete a support ticket."""
    service = get_support_service()
    return service.delete_ticket(request, ticket_id)


# ═══════════════════════════════════════════════════════════════════════
# Credits
# ═══════════════════════════════════════════════════════════════════════

from apps.billing.models import CreditTransaction  # noqa: E402


class CreditBalanceSchema(Schema):
    """Response schema for credit wallet balance."""

    total_available: int
    monthly_credits: int
    monthly_credits_remaining: int
    addon_credits: int
    free_credits: int
    daily_credits_remaining: int
    active_grants: int
    active_holds: int


class CreditTransactionSchema(ModelSchema):
    """Response schema for credit transactions."""

    class Config:
        model = CreditTransaction
        model_fields = [
            "id",
            "amount",
            "balance_after",
            "category",
            "source_type",
            "description",
            "created_at",
        ]


class CreditTransactionFilterSchema(Schema):
    """Query params for filtering credit transactions."""

    category: Optional[str] = None
    page: int = 1


class PurchaseCreditsRequest(Schema):
    """Request schema for purchasing an add-on credit pack."""

    packs: int = 1  # Number of 1000-credit packs


class PurchaseCreditsResponse(Schema):
    """Response schema after initiating a credit purchase."""

    checkout_url: Optional[str] = None
    credits: int = 0


@billing_api.get("/credits/balance", response=CreditBalanceSchema)
def get_credit_balance(request: WSGIRequest):
    """Get the current user's credit wallet balance."""
    from apps.billing.credit_service import CreditService
    from apps.billing.models import CreditGrant, CreditHold

    wallet = CreditService.get_or_create_wallet(request.auth)
    active_grants = CreditGrant.objects.filter(
        wallet=wallet,
        remaining__gt=0,
        expires_at__gt=__import__("django.utils", fromlist=["timezone"]).timezone.now(),
    ).count()
    active_holds = CreditHold.objects.filter(wallet=wallet, status="active").count()

    return CreditBalanceSchema(
        total_available=wallet.total_available,
        monthly_credits=wallet.monthly_credits,
        monthly_credits_remaining=wallet.monthly_credits_remaining,
        addon_credits=wallet.addon_credits,
        free_credits=wallet.free_credits,
        daily_credits_remaining=wallet.daily_credits_remaining,
        active_grants=active_grants,
        active_holds=active_holds,
    )


@billing_api.get("/credits/transactions", response=List[CreditTransactionSchema])
@paginate(PageNumberPagination, page_size=25)
def get_credit_transactions(
    request: WSGIRequest, filters: CreditTransactionFilterSchema = None
):
    """Get paginated credit transaction history."""
    from apps.billing.credit_service import CreditService

    wallet = CreditService.get_or_create_wallet(request.auth)
    category = filters.category if filters else None
    qs = CreditTransaction.objects.filter(wallet=wallet)
    if category:
        qs = qs.filter(category=category)
    return qs


@billing_api.get("/credits/usage", response=dict)
def get_credit_usage_summary(request: WSGIRequest):
    """Get aggregated credit usage by category over the last 30 days."""
    from apps.billing.credit_service import CreditService

    wallet = CreditService.get_or_create_wallet(request.auth)
    return CreditService.get_usage_summary(wallet, days=30)


@billing_api.post("/credits/purchase", response=PurchaseCreditsResponse)
def purchase_credits(request: WSGIRequest, data: PurchaseCreditsRequest):
    """Initiate a Dodo checkout for purchasing add-on credit packs."""
    from dodopayments import DodoPayments

    packs = max(1, data.packs)
    credits_amount = packs * 1000

    try:
        client = DodoPayments(
            bearer_token=settings.DODO_PAYMENTS_API_KEY,
            environment=settings.DODO_PAYMENTS_ENVIRONMENT,
        )
        session = client.checkout_sessions.create(
            product_cart=[
                {
                    "product_id": settings.DODO_ADDON_PACK_PRODUCT_ID,
                    "quantity": packs,
                }
            ],
            customer={
                "email": request.auth.email,
                "name": request.auth.name or request.auth.email,
            },
            return_url=f"{settings.FRONTEND_URL}/billing?addon_purchase=success",
            metadata={
                "user_id": str(request.auth.id),
                "type": "credit_purchase",
                "credits": str(credits_amount),
                "packs": str(packs),
            },
        )
        return PurchaseCreditsResponse(
            checkout_url=session.checkout_url,
            credits=credits_amount,
        )
    except Exception as e:
        logger.error("Failed to create credit purchase checkout: %s", e)
        return PurchaseCreditsResponse(credits=credits_amount)
