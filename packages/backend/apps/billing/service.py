"""Service layer for billing operations.

Contains BillingService for subscription lifecycle management, Dodo Payments integration,
webhook handling, and refunds, plus CustomerSupportService for tickets.
"""

import json
import logging
from datetime import timedelta
from functools import cached_property
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.utils import timezone
from dodopayments import DodoPayments

from apps.billing.models import (
    FailedPayment,
    Payment,
    SubscriptionHistory,
    SubscriptionPlan,
    UserSubscription,
    WebhookEvent,
)
from config.errors.common import (
    FileProcessingError,
    InvalidInputError,
    NotFoundError,
    UnauthorizedAccessError,
)
from config.services.base import BaseService

logger = logging.getLogger(__name__)


class BillingException(Exception):
    """Exception raised for billing-related errors."""

    pass


class BillingService(BaseService):
    """Service handling subscription lifecycle, payments, and Dodo Payments integration."""

    SERVICE_NAME = "billing_service"
    SERVICE_VERSION = "2.0.0"

    def __init__(self, **kwargs):
        """Initialize BillingService with Dodo Payments client."""
        super().__init__(**kwargs)
        self.dodo_client = DodoPayments(
            bearer_token=settings.DODO_PAYMENTS_API_KEY,
            environment=settings.DODO_PAYMENTS_ENVIRONMENT,
            webhook_key=settings.DODO_PAYMENTS_WEBHOOK_SECRET,
        )

    @cached_property
    def config(self):
        """Service configuration."""
        return {
            "version": "2.0.0",
            "item_limit": getattr(settings, "BILLING_ITEM_LIMIT", 50),
        }

    def _map_and_log_error(self, e: Exception, context: str) -> Exception:
        """Map raw exceptions to domain-specific errors."""
        known_exceptions = (
            BillingException,
            UnauthorizedAccessError,
            InvalidInputError,
            FileProcessingError,
            NotFoundError,
        )
        if isinstance(e, known_exceptions):
            self._logger.info(f"BillingError in {context}: {e}")
            return e

        if isinstance(e, ValidationError):
            self._logger.warning(f"Validation error in {context}: {e}")
            return InvalidInputError(str(e))

        self._logger.error(f"Unexpected error in {context}: {e}", exc_info=True)
        return BillingException(f"An unexpected error occurred: {e}")

    # ── Plan Queries ──────────────────────────────────────────────────────

    def get_subscription_plans(self):
        """Retrieve all active subscription plans."""
        with self._handle_service_errors():
            return SubscriptionPlan.objects.active()

    # ── Subscription Lifecycle ────────────────────────────────────────────

    @transaction.atomic
    def get_user_subscription_plan(
        self, request: WSGIRequest
    ) -> Optional[UserSubscription]:
        """Get the authenticated user's subscription with usage statistics."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                subscription = UserSubscription.objects.select_related("plan").get(
                    user=user
                )
            except UserSubscription.DoesNotExist:
                raise NotFoundError("User has no subscription plan")

            from apps.agents.models import UserCustomMCPConfig
            from apps.storage.models import AgentRun, UserMarketplaceAddons

            tasks_limit = subscription.get_weekly_task_limit()
            tasks_used = subscription.get_tasks_used_this_week()
            sandbox_limit = subscription.get_feature_info("max_sandbox_time") or 0
            sandbox_used = subscription.get_sandbox_time()
            addons_limit = subscription.get_feature_info("max_addons") or 0
            addons_used = UserMarketplaceAddons.objects.filter(owner=user).count()
            mcp_limit = subscription.get_feature_info("max_mcp_per_task") or 0
            mcp_added = UserCustomMCPConfig.objects.filter(user=user).count()
            concurrent_limit = (
                subscription.get_feature_info("max_concurrent_tasks") or 0
            )
            concurrent_used = AgentRun.objects.filter(
                user=user, status__in=["pending", "running"]
            ).count()

            subscription.usage_schema = {
                "tasks_remaining_week": {
                    "limit": tasks_limit,
                    "used": tasks_used,
                    "label": "Task remaining this week",
                },
                "sandbox_time_remaining_month": {
                    "limit": sandbox_limit,
                    "used": sandbox_used,
                    "label": "Sandbox time remaining",
                },
                "addons_used": {
                    "limit": addons_limit,
                    "used": addons_used,
                    "label": "Addons used",
                },
                "mcp_servers_added": {
                    "limit": mcp_limit,
                    "used": mcp_added,
                    "label": "MCP servers added",
                },
                "concurrent_tasks": {
                    "limit": concurrent_limit,
                    "used": concurrent_used,
                    "label": "Concurrent tasks active",
                },
            }

            return subscription

    @transaction.atomic
    def create_subscription_with_checks(
        self, request: WSGIRequest, plan_id: str, return_as_bool: bool = False
    ):
        """Create a new subscription after checking for and resolving existing ones."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            SubscriptionPlan.objects.get(id=plan_id, is_active=True)
            existing = (
                UserSubscription.objects.select_for_update()
                .filter(user=user, status__in=["active", "pending"])
                .first()
            )
            if existing:
                self._logger.info("Subscription exists - trying to delete")
                if existing.status == "pending":
                    self._logger.debug("Cancelling pending subscription")
                    cancellation_status = self.cancel_pending_subscription(
                        request=request, return_as_bool=return_as_bool
                    )
                    if not cancellation_status:
                        self._logger.warning("Failed to cancel pending subscription")
                        raise BillingException(
                            f"Failed to cancel subscription: {cancellation_status}"
                        )
                else:
                    raise BillingException("Subscription already active")

            response = self._create_subscription(request, plan_id)
            if return_as_bool:
                return True

            return response

    @transaction.atomic
    def _create_subscription(self, request: WSGIRequest, plan_id: str):
        """Create a subscription, returning checkout URL for paid plans."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                raise BillingException(f"Subscription plan {plan_id} does not exist")

            if plan.tier == "free":
                subscription, created = UserSubscription.objects.get_or_create(
                    user=user
                )
                subscription.plan = plan
                subscription.status = "active"
                subscription.start_date = timezone.now()
                subscription.auto_renew = True
                subscription.end_date = None
                subscription.save()
                subscription.refresh_from_db()

                return {
                    "message": "Free plan activated",
                    "subscription_id": str(subscription.id),
                }

            # Ensure Dodo customer exists
            subscription, created = UserSubscription.objects.get_or_create(user=user)
            if not subscription.dodo_customer_id:
                try:
                    customer = self.dodo_client.customers.create(
                        email=user.email,
                        name=user.name or user.email,
                    )
                    subscription.dodo_customer_id = customer.customer_id
                    subscription.save()
                    subscription.refresh_from_db()
                except Exception as e:
                    self._logger.error(f"Failed to create Dodo customer: {e}")
                    raise BillingException(f"Failed to create customer: {e}")

            # Create Dodo checkout session
            try:
                session = self.dodo_client.checkout_sessions.create(
                    product_cart=[{"product_id": plan.dodo_product_id, "quantity": 1}],
                    customer={"customer_id": subscription.dodo_customer_id},
                    return_url=f"{settings.FRONTEND_URL}/billing?status=success",
                    metadata={
                        "user_id": str(user.id),
                        "plan_id": str(plan.id),
                    },
                )
            except Exception as e:
                self._logger.error(f"Dodo checkout session creation failed: {e}")
                raise BillingException(f"Failed to create checkout session: {e}")

            subscription.plan = plan
            subscription.status = "pending"
            subscription.save()

            return {
                "checkout_url": session.checkout_url,
                "subscription_id": str(subscription.id),
            }

    @transaction.atomic
    def cancel_pending_subscription(self, request: WSGIRequest, return_as_bool=False):
        """Cancel a pending (not yet active) subscription."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            subscription = UserSubscription.objects.filter(
                user=user, status="pending"
            ).first()

            if not subscription:
                self._logger.info("No pending subscription found")
                if return_as_bool:
                    return True
                return {"message": "No pending subscription found"}

            if subscription.dodo_subscription_id:
                try:
                    self.dodo_client.subscriptions.update(
                        subscription.dodo_subscription_id,
                        cancel_at_next_billing_date=True,
                    )
                except Exception as e:
                    self._logger.error(f"Error cancelling Dodo subscription: {e}")
                    raise BillingException(f"Error cancelling Dodo subscription: {e}")

            subscription.status = "cancelled"
            subscription.save()
            if return_as_bool:
                return True

            return {"message": "Pending subscription cancelled"}

    @transaction.atomic
    def change_subscription_plan(
        self, request: WSGIRequest, new_plan_id: str, immediate: bool
    ):
        """Change the user's subscription to a different plan."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            new_plan = SubscriptionPlan.objects.get(id=new_plan_id, is_active=True)
            subscription = UserSubscription.objects.get(user=user)
            if subscription.plan and str(subscription.plan.id) == str(new_plan_id):
                raise BillingException("Already subscribed to this plan")

            if new_plan.tier == "free":
                # Cancel Dodo subscription if exists
                if subscription.dodo_subscription_id:
                    try:
                        self.dodo_client.subscriptions.update(
                            subscription.dodo_subscription_id,
                            cancel_at_next_billing_date=True,
                        )
                    except Exception as e:
                        self._logger.error(f"Error cancelling subscription: {e}")

                if immediate:
                    subscription.plan = new_plan
                    subscription.status = "active"
                    subscription.dodo_subscription_id = None
                    subscription.end_date = None
                    subscription.save()
                    return {"message": "Plan downgraded to free"}
                else:
                    subscription.auto_renew = False
                    subscription.save()
                    return {"message": "Plan will be downgraded at the period end"}

            # Paid plan change
            if immediate and subscription.dodo_subscription_id:
                try:
                    self.dodo_client.subscriptions.change_plan(
                        subscription_id=subscription.dodo_subscription_id,
                        product_id=new_plan.dodo_product_id,
                        proration_billing_mode="do_not_bill",
                        quantity=1,
                    )
                    return {"message": f"Plan changed to {new_plan.name}"}
                except Exception as e:
                    self._logger.error(f"Error changing plan: {e}")
                    raise BillingException(f"Failed to change plan: {e}")
            else:
                subscription.scheduled_plan_change = new_plan
                subscription.scheduled_change_date = subscription.end_date
                subscription.save()
                return {"message": f"Plan change scheduled for {subscription.end_date}"}

    @transaction.atomic
    def retry_failed_payment(self, request: WSGIRequest):
        """Provide a payment method update link for failed payments."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                subscription = UserSubscription.objects.get(user=user)
            except UserSubscription.DoesNotExist:
                raise NotFoundError("User has no subscription plan")

            if not subscription.dodo_subscription_id:
                raise NotFoundError("No subscription found")

            try:
                result = self.dodo_client.subscriptions.update_payment_method(
                    subscription_id=subscription.dodo_subscription_id,
                    type="new",
                    return_url=f"{settings.FRONTEND_URL}/billing?payment_updated=true",
                )
                return {
                    "payment_link": getattr(result, "payment_link", None),
                    "message": "Update your payment method to retry",
                }
            except Exception as e:
                self._logger.error(f"Failed to create payment method update: {e}")
                raise NotFoundError("Unable to create payment update link")

    @transaction.atomic
    def cancel_subscription(
        self, request: WSGIRequest, immediate=False, return_as_bool: bool = False
    ):
        """Cancel an active subscription, optionally immediately."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                subscription = UserSubscription.objects.get(user=user, status="active")
            except UserSubscription.DoesNotExist:
                if return_as_bool:
                    return True
                raise NotFoundError("No subscription found")

            if subscription.dodo_subscription_id:
                try:
                    if immediate:
                        self.dodo_client.subscriptions.update(
                            subscription.dodo_subscription_id,
                            status="cancelled",
                        )
                    else:
                        self.dodo_client.subscriptions.update(
                            subscription.dodo_subscription_id,
                            cancel_at_next_billing_date=True,
                        )
                except Exception as e:
                    self._logger.error(f"Failed to cancel subscription: {e}")
                    if return_as_bool:
                        return False
                    raise BillingException(f"Failed to cancel subscription: {e}")

            if immediate:
                subscription.status = "cancelled"
                subscription.auto_renew = False
                subscription.end_date = timezone.now()
            else:
                subscription.auto_renew = False

            subscription.save()
            if return_as_bool:
                return True

            message = (
                "Subscription cancelled immediately"
                if immediate
                else f"Subscription will cancel at {subscription.end_date}"
            )

            return {"message": message}

    @transaction.atomic
    def reactivate_subscription(self, request: WSGIRequest):
        """Reactivate a cancelled subscription."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            subscription = UserSubscription.objects.get(
                user=user, status__in=["cancelled", "active"]
            )

            if subscription.end_date and subscription.end_date < timezone.now():
                raise BillingException(
                    "Subscription has expired. Please create a new one."
                )

            subscription.status = "active"
            subscription.auto_renew = True
            subscription.save()

            return {"message": "Subscription re-activated"}

    @transaction.atomic
    def pause_subscription(self, request: WSGIRequest):
        """Pause an active subscription (local state only — Dodo does not support native pause)."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                subscription = UserSubscription.objects.get(user=user, status="active")
            except UserSubscription.DoesNotExist:
                raise NotFoundError("No active subscription found")

            if subscription.paused:
                raise BillingException("Subscription is already paused")

            subscription.paused = True
            subscription.paused_at = timezone.now()
            subscription.save()

            from apps.billing.models import SubscriptionPause

            SubscriptionPause.objects.create(
                subscription=subscription,
                user=user,
            )

            return {
                "message": "Subscription paused",
                "paused_at": str(subscription.paused_at),
            }

    @transaction.atomic
    def resume_subscription(self, request: WSGIRequest):
        """Resume a paused subscription (local state only)."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                subscription = UserSubscription.objects.get(user=user, status="active")
            except UserSubscription.DoesNotExist:
                raise NotFoundError("No active subscription found")

            if not subscription.paused:
                raise BillingException("Subscription is not paused")

            subscription.paused = False
            subscription.paused_at = None
            subscription.save()

            from apps.billing.models import SubscriptionPause

            active_pause = SubscriptionPause.objects.filter(
                subscription=subscription, user=user, is_active=True
            ).first()
            if active_pause:
                active_pause.is_active = False
                active_pause.resumed_at = timezone.now()
                active_pause.save()

            return {"message": "Subscription resumed"}

    # ── Payments & Refunds ────────────────────────────────────────────────

    @transaction.atomic
    def request_refund(self, request: WSGIRequest, payment_id: str, reason: str = ""):
        """Initiate a refund for a captured payment via Dodo Payments."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                payment = Payment.objects.get(dodo_payment_id=payment_id, user=user)
            except Payment.DoesNotExist:
                raise BillingException(f"Payment {payment_id} does not exist")

            if payment.status in ("refunded", "refund_pending"):
                return {"message": "Already refunded or refund pending"}

            try:
                refund = self.dodo_client.refunds.create(
                    payment_id=payment.dodo_payment_id,
                    reason=reason or None,
                )
                payment.status = "refund_pending"
                payment.dodo_refund_id = refund.refund_id
                payment.save()

                return {"message": "Refund initiated", "refund_id": refund.refund_id}
            except Exception as e:
                raise BillingException(f"Error processing refund: {e}")

    @transaction.atomic
    def get_payment_history(self, request: WSGIRequest):
        """Retrieve all payments for the authenticated user."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            return Payment.objects.for_user(user)

    def get_subscription_history(self, request: WSGIRequest):
        """Retrieve subscription change history for the authenticated user."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            return SubscriptionHistory.objects.for_user(user)

    def check_subscription_grace_period(self, request: WSGIRequest):
        """Check the grace period status for the authenticated user's subscription."""
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            try:
                subscription = UserSubscription.objects.get(user=user)
            except UserSubscription.DoesNotExist:
                raise NotFoundError("No subscription found")

            now = timezone.now()
            if subscription.status == "active" and subscription.end_date:
                days_remaining = (subscription.end_date - now).days

                if not subscription.grace_period_end:
                    subscription.grace_period_end = subscription.end_date + timedelta(
                        days=7
                    )
                    subscription.save(update_fields=["grace_period_end"])

                in_grace = (
                    now > subscription.end_date and subscription.in_grace_period()
                )
                return {
                    "status": subscription.status,
                    "days_remaining": days_remaining if days_remaining > 0 else 0,
                    "in_grace_period": in_grace,
                    "grace_ends": subscription.grace_period_end if in_grace else None,
                }

            return {
                "status": subscription.status,
                "days_remaining": None,
                "in_grace_period": False,
                "grace_ends": None,
            }

    # ── Dodo Webhook Handler ──────────────────────────────────────────────

    def handle_dodo_webhook(self, request: WSGIRequest):
        """Handle incoming Dodo Payments webhook events.

        Verifies signature, checks idempotency, and dispatches to event-specific handlers.
        """
        with self._handle_service_errors():
            payload = request.body
            headers = {
                "webhook-id": request.headers.get("webhook-id", ""),
                "webhook-signature": request.headers.get("webhook-signature", ""),
                "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
            }

            try:
                event = self.dodo_client.webhooks.unwrap(payload, headers=headers)
            except Exception:
                raise BillingException("Invalid webhook signature")

            # Idempotency check
            event_id = headers["webhook-id"]
            if WebhookEvent.objects.filter(event_id=event_id, processed=True).exists():
                return {"message": "Already processed"}

            event_type = event.get("type", "")
            webhook_record = WebhookEvent.objects.create(
                event_id=event_id,
                event_type=event_type,
                payload=event if isinstance(event, dict) else json.loads(str(event)),
            )

            handler_map = {
                "subscription.active": self._handle_sub_active,
                "subscription.renewed": self._handle_sub_renewed,
                "subscription.cancelled": self._handle_sub_cancelled,
                "subscription.on_hold": self._handle_sub_on_hold,
                "subscription.plan_changed": self._handle_sub_plan_changed,
                "subscription.expired": self._handle_sub_expired,
                "payment.succeeded": self._handle_payment_succeeded,
                "payment.failed": self._handle_payment_failed,
                "refund.succeeded": self._handle_refund_succeeded,
            }

            data = event.get("data", {})
            handler = handler_map.get(event_type)
            if handler:
                handler(data)
            else:
                self._logger.warning(f"Unhandled webhook event type: {event_type}")

            webhook_record.processed = True
            webhook_record.processed_at = timezone.now()
            webhook_record.save()

            return {"message": "Success"}

    @transaction.atomic
    def _handle_sub_active(self, data):
        """Subscription activated — set active, record payment."""
        subscription_id = data.get("subscription_id", "")
        subscription = UserSubscription.objects.filter(
            dodo_subscription_id=subscription_id
        ).first() or self._find_subscription_by_metadata(data)
        if not subscription:
            self._logger.warning(
                f"No subscription found for activation: {subscription_id}"
            )
            return

        subscription.status = "active"
        subscription.dodo_subscription_id = subscription_id
        subscription.auto_renew = True
        subscription.start_date = timezone.now()
        subscription.end_date = timezone.now() + timedelta(days=30)
        subscription.save()

        # Create payment record
        payment_id = data.get("payment_id", "")
        if payment_id:
            Payment.objects.create(
                user=subscription.user,
                subscription=subscription,
                dodo_payment_id=payment_id,
                amount=subscription.plan.price if subscription.plan else 0,
                currency="USD",
                status="captured",
            )

        SubscriptionHistory.objects.create(
            subscription=subscription,
            user=subscription.user,
            action="created",
            new_plan=subscription.plan,
            notes="Subscription activated via Dodo Payments",
        )

    @transaction.atomic
    def _handle_sub_renewed(self, data):
        """Subscription renewed — extend end_date, refresh credits."""
        subscription_id = data.get("subscription_id", "")
        subscription = UserSubscription.objects.filter(
            dodo_subscription_id=subscription_id
        ).first()
        if not subscription:
            return

        subscription.end_date = timezone.now() + timedelta(days=30)
        subscription.auto_renew = True
        subscription.save()

        # Create payment record for renewal
        payment_id = data.get("payment_id", "")
        if payment_id:
            Payment.objects.create(
                user=subscription.user,
                subscription=subscription,
                dodo_payment_id=payment_id,
                amount=subscription.plan.price if subscription.plan else 0,
                currency="USD",
                status="captured",
            )

        # Refresh monthly credits
        try:
            from apps.billing.credit_service import CreditService
            from apps.billing.models import CreditWallet

            wallet = CreditWallet.objects.filter(user=subscription.user).first()
            if wallet:
                CreditService.refresh_monthly(wallet)
        except Exception as e:
            self._logger.error(f"Failed to refresh monthly credits: {e}")

    @transaction.atomic
    def _handle_sub_cancelled(self, data):
        """Subscription cancelled."""
        subscription_id = data.get("subscription_id", "")
        subscription = UserSubscription.objects.filter(
            dodo_subscription_id=subscription_id
        ).first()
        if not subscription:
            return

        old_plan = subscription.plan
        subscription.status = "cancelled"
        subscription.auto_renew = False
        subscription.save()

        SubscriptionHistory.objects.create(
            subscription=subscription,
            user=subscription.user,
            action="cancelled",
            old_plan=old_plan,
            notes="Subscription cancelled",
        )

    @transaction.atomic
    def _handle_sub_on_hold(self, data):
        """Subscription on hold due to failed payment — start grace period."""
        subscription_id = data.get("subscription_id", "")
        subscription = UserSubscription.objects.filter(
            dodo_subscription_id=subscription_id
        ).first()
        if not subscription:
            return

        subscription.grace_period_end = timezone.now() + timedelta(days=7)
        subscription.last_payment_failed_at = timezone.now()
        subscription.save()

        FailedPayment.objects.create(
            user=subscription.user,
            subscription=subscription,
            amount=subscription.plan.price if subscription.plan else 0,
            error_description="Subscription placed on hold due to payment failure",
        )

    @transaction.atomic
    def _handle_sub_plan_changed(self, data):
        """Subscription plan changed — update plan FK."""
        subscription_id = data.get("subscription_id", "")
        subscription = UserSubscription.objects.filter(
            dodo_subscription_id=subscription_id
        ).first()
        if not subscription:
            return

        product_id = data.get("product_id", "")
        new_plan = SubscriptionPlan.objects.filter(dodo_product_id=product_id).first()
        if not new_plan:
            self._logger.warning(f"No plan found for product_id: {product_id}")
            return

        old_plan = subscription.plan
        subscription.plan = new_plan
        subscription.save()

        old_price = old_plan.price if old_plan else 0
        new_price = new_plan.price if new_plan else 0
        action = "upgraded" if new_price > old_price else "downgraded"

        SubscriptionHistory.objects.create(
            subscription=subscription,
            user=subscription.user,
            action=action,
            old_plan=old_plan,
            new_plan=new_plan,
            notes=f"Plan changed via Dodo Payments",
        )

    @transaction.atomic
    def _handle_sub_expired(self, data):
        """Subscription expired — downgrade to free."""
        subscription_id = data.get("subscription_id", "")
        subscription = UserSubscription.objects.filter(
            dodo_subscription_id=subscription_id
        ).first()
        if not subscription:
            return

        old_plan = subscription.plan
        subscription.status = "expired"
        subscription.save()

        # Downgrade to free plan
        free_plan = SubscriptionPlan.objects.filter(tier="free").first()
        if free_plan:
            subscription.plan = free_plan
            subscription.dodo_subscription_id = None
            subscription.end_date = None
            subscription.status = "active"
            subscription.save()

        SubscriptionHistory.objects.create(
            subscription=subscription,
            user=subscription.user,
            action="expired",
            old_plan=old_plan,
            new_plan=free_plan,
            notes="Subscription expired, downgraded to free",
        )

    @transaction.atomic
    def _handle_payment_succeeded(self, data):
        """Payment succeeded — update/create Payment record, handle credit purchases."""
        payment_id = data.get("payment_id", "")
        metadata = data.get("metadata", {})

        # Check if this is an add-on credit purchase
        if metadata.get("type") == "credit_purchase":
            self._handle_credit_purchase(data)
            return

        # Regular subscription payment — find or create Payment record
        payment = Payment.objects.filter(dodo_payment_id=payment_id).first()
        if payment:
            payment.status = "captured"
            payment.save()

    @transaction.atomic
    def _handle_credit_purchase(self, data):
        """Handle a successful credit pack purchase."""
        metadata = data.get("metadata", {})
        user_id = metadata.get("user_id")
        credits_amount = int(metadata.get("credits", 0))
        payment_id = data.get("payment_id", "")

        if not user_id or not credits_amount:
            self._logger.error(f"Invalid credit purchase metadata: {metadata}")
            return

        try:
            from apps.billing.credit_service import CreditService
            from apps.billing.models import CreditWallet
            from apps.users.models import User

            user = User.objects.get(id=user_id)
            wallet = CreditWallet.objects.filter(user=user).first()
            if not wallet:
                wallet = CreditService.get_or_create_wallet(user)

            CreditService.purchase_addon_pack(
                wallet,
                credits_amount,
                payment_metadata={"dodo_payment_id": payment_id},
            )
            self._logger.info(
                f"Granted {credits_amount} addon credits to user {user_id}"
            )
        except Exception as e:
            self._logger.error(f"Failed to grant addon credits: {e}")

    @transaction.atomic
    def _handle_payment_failed(self, data):
        """Payment failed — create FailedPayment record."""
        payment_id = data.get("payment_id", "")
        subscription_id = data.get("subscription_id", "")

        subscription = (
            UserSubscription.objects.filter(
                dodo_subscription_id=subscription_id
            ).first()
            if subscription_id
            else None
        )

        if subscription:
            FailedPayment.objects.create(
                user=subscription.user,
                subscription=subscription,
                dodo_payment_id=payment_id,
                amount=subscription.plan.price if subscription.plan else 0,
                error_description="Payment failed",
            )

    @transaction.atomic
    def _handle_refund_succeeded(self, data):
        """Refund succeeded — update Payment status."""
        payment_id = data.get("payment_id", "")
        refund_id = data.get("refund_id", "")

        payment = Payment.objects.filter(dodo_payment_id=payment_id).first()
        if not payment:
            self._logger.warning(f"No payment found for refund: {payment_id}")
            return

        payment.status = "refunded"
        payment.dodo_refund_id = refund_id
        payment.save()

    def _find_subscription_by_metadata(self, data) -> Optional[UserSubscription]:
        """Look up a subscription from webhook metadata (user_id)."""
        metadata = data.get("metadata", {})
        user_id = metadata.get("user_id")
        if user_id:
            return UserSubscription.objects.filter(user_id=user_id).first()
        return None

    # ── Promo Codes ───────────────────────────────────────────────────────

    def validate_promo_code(self, code: str):
        """Validate a promotional coupon code and return discount information."""
        with self._handle_service_errors():
            from apps.billing.models import PromoCoupon

            try:
                coupon = PromoCoupon.objects.get(code=code)
            except PromoCoupon.DoesNotExist:
                return {
                    "valid": False,
                    "discount_percent": 0,
                    "message": "Invalid promo code",
                }

            if not coupon.is_active:
                return {
                    "valid": False,
                    "discount_percent": 0,
                    "message": "This promo code is no longer active",
                }

            now = timezone.now()
            if now < coupon.valid_from or now > coupon.valid_until:
                return {
                    "valid": False,
                    "discount_percent": 0,
                    "message": "This promo code has expired",
                }

            if coupon.max_uses and coupon.used_count >= coupon.max_uses:
                return {
                    "valid": False,
                    "discount_percent": 0,
                    "message": "This promo code has reached its usage limit",
                }

            discount_percent = (
                int(coupon.discount_value)
                if coupon.discount_type == "percentage"
                else 0
            )

            return {
                "valid": True,
                "discount_percent": discount_percent,
                "message": f"{discount_percent}% discount applied"
                if discount_percent > 0
                else f"${coupon.discount_value} discount applied",
            }


class CustomerSupportService(BaseService):
    """Service for managing customer support tickets."""

    SERVICE_NAME = "customer_support_service"
    SERVICE_VERSION = "1.0.0"

    def __init__(self, **kwargs):
        """Initialize CustomerSupportService with base infrastructure."""
        super().__init__(**kwargs)

    @cached_property
    def config(self):
        """Service configuration."""
        return {
            "version": "1.0.0",
            "item_limit": getattr(settings, "SUPPORT_TICKET_LIMIT", 100),
        }

    def _map_and_log_error(self, e: Exception, context: str) -> Exception:
        """Map raw exceptions to domain-specific errors."""

        known_exceptions = (
            BillingException,
            UnauthorizedAccessError,
            InvalidInputError,
            FileProcessingError,
            NotFoundError,
        )
        if isinstance(e, known_exceptions):
            self._logger.info(f"CustomerSupportError in {context}: {e}")
            return e

        if isinstance(e, ValidationError):
            self._logger.warning(f"Validation error in {context}: {e}")
            return InvalidInputError(str(e))

        self._logger.error(f"Unexpected error in {context}: {e}", exc_info=True)
        return BillingException(f"An unexpected error occurred: {e}")

    @transaction.atomic
    def create_ticket(self, request: WSGIRequest, title: str, message: str):
        """Create a new support ticket."""
        from apps.billing.models import CustomerSupportTicket

        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            ticket = CustomerSupportTicket.objects.create(
                user=user, title=title, message=message, status="open"
            )
            return ticket

    def get_ticket(self, request: WSGIRequest, ticket_id: str):
        """Get a single support ticket by ID."""
        from apps.billing.models import CustomerSupportTicket

        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            ticket_uuid = self._validate_uuid(ticket_id, "ticket_id")

            try:
                ticket = CustomerSupportTicket.objects.get(id=ticket_uuid, user=user)
            except CustomerSupportTicket.DoesNotExist:
                raise NotFoundError(f"Support ticket {ticket_id} not found")

            return ticket

    def list_tickets(self, request: WSGIRequest):
        """List all support tickets for the authenticated user."""
        from apps.billing.models import CustomerSupportTicket

        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            return CustomerSupportTicket.objects.filter(user=user).order_by(
                "-created_at"
            )

    @transaction.atomic
    def update_ticket(
        self,
        request: WSGIRequest,
        ticket_id: str,
        title: Optional[str] = None,
        message: Optional[str] = None,
        status: Optional[str] = None,
    ):
        """Update an existing support ticket."""
        from apps.billing.models import CustomerSupportTicket

        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            ticket_uuid = self._validate_uuid(ticket_id, "ticket_id")

            try:
                ticket = CustomerSupportTicket.objects.get(id=ticket_uuid, user=user)
            except CustomerSupportTicket.DoesNotExist:
                raise NotFoundError(f"Support ticket {ticket_id} not found")

            if title is not None:
                ticket.title = title
            if message is not None:
                ticket.message = message
            if status is not None:
                valid_statuses = ["open", "in_progress", "resolved", "closed"]
                if status not in valid_statuses:
                    raise InvalidInputError(
                        f"Invalid status. Must be one of: {valid_statuses}"
                    )
                ticket.status = status

            ticket.save()
            return ticket

    @transaction.atomic
    def delete_ticket(self, request: WSGIRequest, ticket_id: str):
        """Delete a support ticket."""
        from apps.billing.models import CustomerSupportTicket

        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            ticket_uuid = self._validate_uuid(ticket_id, "ticket_id")

            try:
                ticket = CustomerSupportTicket.objects.get(id=ticket_uuid, user=user)
            except CustomerSupportTicket.DoesNotExist:
                raise NotFoundError(f"Support ticket {ticket_id} not found")

            ticket.delete()
            return {"message": "Support ticket deleted successfully"}
