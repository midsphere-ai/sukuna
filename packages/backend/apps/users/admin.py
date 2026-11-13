"""Django admin configuration for the User model with subscription and usage dashboards."""

from datetime import timedelta

from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from apps.agents.models import UserCustomMCPConfig

# Import related models for inlines
from apps.billing.models import Payment, SubscriptionPlan, UserSubscription
from apps.storage.models import (
    AgentRun,
    Conversation,
    StoredFile,
    UserMarketplaceAddons,
)

from .forms import UserAdminChangeForm, UserAdminCreationForm
from .models import DeveloperAPIKey, User

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)


class UserSubscriptionInline(TabularInline):
    """User's subscription - OneToOne relationship via 'user' field."""

    model = UserSubscription
    extra = 0
    can_delete = False
    readonly_fields = [
        "plan",
        "status",
        "start_date",
        "end_date",
        "auto_renew",
        "paused",
    ]
    fields = ["plan", "status", "start_date", "end_date", "auto_renew", "paused"]

    def has_add_permission(self, request, obj=None):
        """Prevent adding subscriptions directly via inline.

        Args:
            request: The current HTTP request.
            obj: The parent User instance, or None.

        Returns:
            Always False.
        """
        return False


class PaymentInline(TabularInline):
    """User's payments - FK via 'user' field."""

    model = Payment
    extra = 0
    can_delete = False
    readonly_fields = ["amount", "currency", "status", "created_at"]
    fields = ["amount", "currency", "status", "created_at"]
    max_num = 10
    ordering = ["-created_at"]

    def has_add_permission(self, request, obj=None):
        """Prevent adding payments directly via inline.

        Args:
            request: The current HTTP request.
            obj: The parent User instance, or None.

        Returns:
            Always False.
        """
        return False


class ConversationInline(TabularInline):
    """User's conversations - FK via 'user' field."""

    model = Conversation
    fk_name = "user"
    extra = 0
    can_delete = False
    readonly_fields = ["title", "display_ongoing", "display_has_error", "date_created"]
    fields = ["title", "display_ongoing", "display_has_error", "date_created"]
    max_num = 10
    ordering = ["-date_created"]

    @admin.display(boolean=True, description="Ongoing")
    def display_ongoing(self, obj):
        """Return whether the conversation is currently ongoing.

        Args:
            obj: The Conversation instance.

        Returns:
            True if the conversation is ongoing, False otherwise.
        """
        return obj.get_is_ongoing()

    @admin.display(boolean=True, description="Has Error")
    def display_has_error(self, obj):
        """Return whether the conversation has encountered an error.

        Args:
            obj: The Conversation instance.

        Returns:
            True if the conversation has an error, False otherwise.
        """
        return obj.get_has_error()

    def has_add_permission(self, request, obj=None):
        """Prevent adding conversations directly via inline.

        Args:
            request: The current HTTP request.
            obj: The parent User instance, or None.

        Returns:
            Always False.
        """
        return False


class StoredFileInline(TabularInline):
    """User's stored files - FK via 'owner' field (not 'user')."""

    model = StoredFile
    fk_name = "owner"
    extra = 0
    can_delete = True
    readonly_fields = ["name", "size", "mime_type", "uploaded_at"]
    fields = ["name", "size", "mime_type", "uploaded_at"]
    max_num = 10
    ordering = ["-uploaded_at"]

    def has_add_permission(self, request, obj=None):
        """Prevent adding stored files directly via inline.

        Args:
            request: The current HTTP request.
            obj: The parent User instance, or None.

        Returns:
            Always False.
        """
        return False


@admin.register(User)
class UserAdmin(ModelAdmin):
    """Admin interface for managing User accounts with subscription and usage dashboards."""

    form = UserAdminChangeForm
    add_form = UserAdminCreationForm

    def get_form(self, request, obj=None, **kwargs):
        """Use add_form during user creation (handles password1/password2 form fields)."""
        defaults = {}
        if obj is None:
            defaults["form"] = self.add_form
        defaults.update(kwargs)
        return super().get_form(request, obj, **defaults)

    def get_fieldsets(self, request, obj=None):
        """Use add_fieldsets during user creation."""
        if not obj:
            return self.add_fieldsets
        return super().get_fieldsets(request, obj)

    def get_inlines(self, request, obj=None):
        """Hide inlines on add view (user doesn't exist yet)."""
        if not obj:
            return []
        return super().get_inlines(request, obj)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name",)}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (
            _("Subscription & Limits"),
            {
                "fields": ("subscription_info",),
            },
        ),
        (
            _("Usage This Week"),
            {
                "fields": ("usage_summary",),
            },
        ),
    )
    list_display = [
        "email",
        "name",
        "get_plan",
        "get_subscription_status",
        "get_tasks_this_week",
        "is_superuser",
    ]
    list_filter = ["is_staff", "is_superuser", "is_active"]
    search_fields = ["email_hash"]
    ordering = ["-date_joined"]
    readonly_fields = ["subscription_info", "usage_summary"]
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )
    inlines = [
        UserSubscriptionInline,
        PaymentInline,
        ConversationInline,
        StoredFileInline,
    ]
    actions = ["assign_free_plan", "assign_lite_plan", "assign_pro_plan"]

    def get_urls(self):
        """Register custom admin URLs for plan assignment actions.

        Returns:
            List of URL patterns including the custom assign-plan endpoint.
        """
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/assign-plan/<str:tier>/",
                self.admin_site.admin_view(self.assign_plan_view),
                name="users_user_assign_plan",
            ),
        ]
        return custom_urls + urls

    def assign_plan_view(self, request, object_id, tier):
        """Assign a subscription plan to a user via a custom admin URL.

        Args:
            request: The current HTTP request.
            object_id: The primary key of the target User.
            tier: The subscription tier slug (e.g., 'free', 'basic', 'premium').

        Returns:
            Redirect back to the user change page.
        """
        user = self.get_object(request, object_id)
        if user:
            try:
                plan = SubscriptionPlan.objects.get(tier=tier, is_active=True)
                subscription, created = UserSubscription.objects.update_or_create(
                    user=user,
                    defaults={
                        "plan": plan,
                        "status": "active",
                        "start_date": timezone.now(),
                        "end_date": timezone.now()
                        + timedelta(days=365),  # 1 year for manual assignments
                        "auto_renew": False,
                    },
                )
                action = "Assigned" if created else "Updated"
                messages.success(request, f"{action} {plan.name} to {user.email}")
            except SubscriptionPlan.DoesNotExist:
                messages.error(request, f"Plan '{tier}' not found")
        return HttpResponseRedirect(
            reverse("admin:users_user_change", args=[object_id])
        )

    @admin.action(description="Assign Free plan to selected users")
    def assign_free_plan(self, request, queryset):
        """Bulk-assign the Free plan to all selected users.

        Args:
            request: The current HTTP request.
            queryset: QuerySet of selected User instances.
        """
        self._bulk_assign_plan(request, queryset, "free")

    @admin.action(description="Assign Lite plan to selected users")
    def assign_lite_plan(self, request, queryset):
        """Bulk-assign the Lite plan to all selected users.

        Args:
            request: The current HTTP request.
            queryset: QuerySet of selected User instances.
        """
        self._bulk_assign_plan(request, queryset, "basic")

    @admin.action(description="Assign Pro plan to selected users")
    def assign_pro_plan(self, request, queryset):
        """Bulk-assign the Pro plan to all selected users.

        Args:
            request: The current HTTP request.
            queryset: QuerySet of selected User instances.
        """
        self._bulk_assign_plan(request, queryset, "premium")

    def _bulk_assign_plan(self, request, queryset, tier):
        try:
            plan = SubscriptionPlan.objects.get(tier=tier, is_active=True)
            count = 0
            for user in queryset:
                UserSubscription.objects.update_or_create(
                    user=user,
                    defaults={
                        "plan": plan,
                        "status": "active",
                        "start_date": timezone.now(),
                        "end_date": timezone.now() + timedelta(days=365),
                        "auto_renew": False,
                    },
                )
                count += 1
            messages.success(request, f"Assigned {plan.name} to {count} users")
        except SubscriptionPlan.DoesNotExist:
            messages.error(request, f"Plan '{tier}' not found")

    def get_week_start(self):
        """Get the start of the current week (Monday)"""
        today = timezone.now().date()
        return timezone.make_aware(
            timezone.datetime.combine(
                today - timedelta(days=today.weekday()), timezone.datetime.min.time()
            )
        )

    @admin.display(description="Tasks/Week")
    def get_tasks_this_week(self, obj):
        """Return a formatted string showing tasks used vs. weekly limit.

        Args:
            obj: The User instance.

        Returns:
            A string like '5/50' or just the count if no plan is set.
        """
        week_start = self.get_week_start()
        count = AgentRun.objects.filter(user=obj, created_at__gte=week_start).count()
        try:
            sub = obj.subscription
            if sub and sub.plan and sub.plan.features:
                limit_data = sub.plan.features.get("weekly_tasks", (0, ""))
                limit = (
                    limit_data[0]
                    if isinstance(limit_data, (list, tuple))
                    else limit_data
                )
                return f"{count}/{limit}"
        except UserSubscription.DoesNotExist:
            pass
        return str(count)

    @admin.display(description="Plan")
    def get_plan(self, obj):
        """Return the name of the user's current subscription plan.

        Args:
            obj: The User instance.

        Returns:
            The plan name string, or '-' if no subscription exists.
        """
        try:
            sub = obj.subscription
            if sub and sub.plan:
                return sub.plan.name
        except UserSubscription.DoesNotExist:
            pass
        return "-"

    @admin.display(description="Status")
    def get_subscription_status(self, obj):
        """Return an HTML-formatted subscription status indicator.

        Args:
            obj: The User instance.

        Returns:
            An HTML string with a colored status dot and label.
        """
        try:
            sub = obj.subscription
            if sub:
                status = sub.status
                if status == "active":
                    return format_html('<span style="color: #22c55e;">●</span> Active')
                elif status == "cancelled":
                    return format_html(
                        '<span style="color: #ef4444;">●</span> Cancelled'
                    )
                elif status == "expired":
                    return format_html('<span style="color: #71717a;">●</span> Expired')
                else:
                    return format_html(
                        '<span style="color: #f59e0b;">●</span> {}', status.title()
                    )
        except UserSubscription.DoesNotExist:
            pass
        return format_html('<span style="color: #71717a;">{}</span> None', "●")

    @admin.display(description="Subscription & Limits")
    def subscription_info(self, obj):
        """Render an HTML dashboard showing subscription details and plan limits.

        Args:
            obj: The User instance.

        Returns:
            An HTML string with plan info, feature limits, and quick-assign buttons.
        """
        try:
            sub = obj.subscription
            if sub and sub.plan:
                features = sub.plan.features or {}

                def get_feature(key, default=0):
                    val = features.get(key, (default, ""))
                    return val[0] if isinstance(val, (list, tuple)) else val

                def get_bool_feature(key, default=False):
                    val = features.get(key, (default, ""))
                    v = val[0] if isinstance(val, (list, tuple)) else val
                    return "✓" if v else "✗"

                weekly_tasks = get_feature("weekly_tasks", 0)
                max_addons = get_feature("max_addons", 0)
                max_addons_per_task = get_feature("max_addons_per_task", 0)
                max_mcp = get_feature("max_mcp_per_task", 0)
                max_sandbox = get_feature("max_sandbox_time", 0)
                max_concurrent = get_feature("max_concurrent_tasks", 1)
                max_scheduled = get_feature("max_scheduled_tasks", 0)

                sandbox_hours = max_sandbox // 3600 if max_sandbox else 0

                # Quick assign buttons
                assign_buttons = format_html(
                    """
                    <div style="margin-top: 12px; display: flex; gap: 8px;">
                        <a href="{}" class="button" style="background: #3f3f46; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 12px;">Assign Free</a>
                        <a href="{}" class="button" style="background: #3b82f6; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 12px;">Assign Lite ($5)</a>
                        <a href="{}" class="button" style="background: #8b5cf6; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 12px;">Assign Pro ($19)</a>
                    </div>
                    """,
                    reverse("admin:users_user_assign_plan", args=[obj.pk, "free"]),
                    reverse("admin:users_user_assign_plan", args=[obj.pk, "basic"]),
                    reverse("admin:users_user_assign_plan", args=[obj.pk, "premium"]),
                )

                return format_html(
                    """
                    <div style="background: #27272a; border-radius: 8px; padding: 16px; font-family: 'IBM Plex Mono', monospace; font-size: 13px;">
                        <div style="display: flex; justify-content: space-between; margin-bottom: 12px; border-bottom: 1px solid #3f3f46; padding-bottom: 12px;">
                            <div><strong style="color: #a1a1aa;">Plan:</strong> <span style="color: #f4f4f5;">{}</span></div>
                            <div><strong style="color: #a1a1aa;">Status:</strong> <span style="color: {};">{}</span></div>
                            <div><strong style="color: #a1a1aa;">Price:</strong> <span style="color: #22c55e;">${}</span>/mo</div>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;">
                            <div><span style="color: #71717a;">Weekly Tasks:</span> <strong>{}</strong></div>
                            <div><span style="color: #71717a;">Max Addons:</span> <strong>{}</strong></div>
                            <div><span style="color: #71717a;">Addons/Task:</span> <strong>{}</strong></div>
                            <div><span style="color: #71717a;">MCP/Task:</span> <strong>{}</strong></div>
                            <div><span style="color: #71717a;">Sandbox Time:</span> <strong>{}h</strong></div>
                            <div><span style="color: #71717a;">Concurrent:</span> <strong>{}</strong></div>
                            <div><span style="color: #71717a;">Scheduled:</span> <strong>{}</strong></div>
                            <div><span style="color: #71717a;">Custom LLM:</span> <strong>{}</strong></div>
                            <div><span style="color: #71717a;">Custom MCP:</span> <strong>{}</strong></div>
                        </div>
                        {}
                    </div>
                    """,
                    sub.plan.name,
                    "#22c55e" if sub.status == "active" else "#ef4444",
                    sub.status.title(),
                    sub.plan.price,
                    weekly_tasks,
                    max_addons,
                    max_addons_per_task,
                    max_mcp,
                    sandbox_hours,
                    max_concurrent,
                    max_scheduled,
                    get_bool_feature("use_custom_llm"),
                    get_bool_feature("use_custom_mcp"),
                    assign_buttons,
                )
        except UserSubscription.DoesNotExist:
            pass

        # No subscription - show quick assign buttons
        return format_html(
            """
            <div style="background: #27272a; border-radius: 8px; padding: 16px; font-family: 'IBM Plex Mono', monospace;">
                <div style="color: #f59e0b; margin-bottom: 12px;">⚠ No subscription assigned</div>
                <div style="display: flex; gap: 8px;">
                    <a href="{}" class="button" style="background: #3f3f46; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 12px;">Assign Free</a>
                    <a href="{}" class="button" style="background: #3b82f6; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 12px;">Assign Lite ($5)</a>
                    <a href="{}" class="button" style="background: #8b5cf6; color: white; padding: 6px 12px; border-radius: 4px; text-decoration: none; font-size: 12px;">Assign Pro ($19)</a>
                </div>
            </div>
            """,
            reverse("admin:users_user_assign_plan", args=[obj.pk, "free"]),
            reverse("admin:users_user_assign_plan", args=[obj.pk, "basic"]),
            reverse("admin:users_user_assign_plan", args=[obj.pk, "premium"]),
        )

    @admin.display(description="Usage This Week")
    def usage_summary(self, obj):
        """Render an HTML dashboard summarizing the user's weekly usage statistics.

        Args:
            obj: The User instance.

        Returns:
            An HTML string with progress bars and usage counts.
        """
        week_start = self.get_week_start()

        # Count usage
        tasks_this_week = AgentRun.objects.filter(
            user=obj, created_at__gte=week_start
        ).count()
        total_tasks = AgentRun.objects.filter(user=obj).count()
        conv_count = Conversation.objects.filter(user=obj).count()
        file_count = StoredFile.objects.filter(owner=obj).count()
        addon_count = UserMarketplaceAddons.objects.filter(owner=obj).count()
        mcp_count = UserCustomMCPConfig.objects.filter(user=obj).count()

        # Get limits for progress bars
        weekly_limit = 0
        addon_limit = 0
        try:
            sub = obj.subscription
            if sub and sub.plan and sub.plan.features:
                features = sub.plan.features

                def get_val(key, default=0):
                    val = features.get(key, (default, ""))
                    return val[0] if isinstance(val, (list, tuple)) else val

                weekly_limit = get_val("weekly_tasks", 0)
                addon_limit = get_val("max_addons", 0)
                get_val("max_mcp_per_task", 0) * 2  # Rough estimate for total MCPs
        except Exception:
            pass

        def progress_bar(used, limit, color="#3b82f6"):
            if limit == 0:
                pct = 100 if used > 0 else 0
            else:
                pct = min(100, (used / limit) * 100)
            bar_color = "#ef4444" if pct >= 90 else "#f59e0b" if pct >= 70 else color
            return format_html(
                """
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="flex: 1; background: #3f3f46; border-radius: 4px; height: 8px; overflow: hidden;">
                        <div style="width: {}%; background: {}; height: 100%;"></div>
                    </div>
                    <span style="min-width: 60px; text-align: right;">{}/{}</span>
                </div>
                """,
                pct,
                bar_color,
                used,
                limit if limit > 0 else "∞",
            )

        return format_html(
            """
            <div style="background: #27272a; border-radius: 8px; padding: 16px; font-family: 'IBM Plex Mono', monospace; font-size: 13px;">
                <div style="display: grid; gap: 12px;">
                    <div>
                        <div style="color: #71717a; margin-bottom: 4px;">Tasks This Week</div>
                        {}
                    </div>
                    <div>
                        <div style="color: #71717a; margin-bottom: 4px;">Connected Addons</div>
                        {}
                    </div>
                    <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-top: 8px; padding-top: 12px; border-top: 1px solid #3f3f46;">
                        <div><span style="color: #71717a;">Total Tasks:</span> <strong>{}</strong></div>
                        <div><span style="color: #71717a;">Conversations:</span> <strong>{}</strong></div>
                        <div><span style="color: #71717a;">Stored Files:</span> <strong>{}</strong></div>
                        <div><span style="color: #71717a;">MCPs:</span> <strong>{}</strong></div>
                    </div>
                </div>
            </div>
            """,
            progress_bar(tasks_this_week, weekly_limit),
            progress_bar(addon_count, addon_limit, "#8b5cf6"),
            total_tasks,
            conv_count,
            file_count,
            mcp_count,
        )


@admin.register(DeveloperAPIKey)
class DeveloperAPIKeyAdmin(ModelAdmin):
    """Admin interface for managing developer API keys."""

    list_display = (
        "name",
        "user",
        "key_prefix",
        "is_active",
        "last_used_at",
        "date_created",
    )
    list_filter = ("is_active", "user")
    search_fields = ("name", "user__email", "key_prefix")
    readonly_fields = (
        "id",
        "key_hash",
        "key_prefix",
        "date_created",
        "date_updated",
        "last_used_at",
    )
    ordering = ("-date_created",)
    fieldsets = (
        ("Key Details", {"fields": ("name", "user", "key_prefix", "key_hash")}),
        ("Status", {"fields": ("is_active", "scopes", "expires_at", "last_used_at")}),
        ("Timestamps", {"fields": ("date_created", "date_updated")}),
    )
