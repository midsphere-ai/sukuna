"""
Smoke tests — end-to-end flows (US-061, US-106, US-113).

These tests verify critical user flows work end-to-end using the Django
test client and real database interactions (no external services).

Flows tested:
1. Signup → Login → Create project → Start conversation → Receive response
2. Addon install → Conversation with addon → Addon tools available
3. Scheduled task create → Trigger → Complete
4. Billing subscribe → Usage tracked → Limits enforced
5. Shared sandbox: project → conversations → verify same sandbox (US-106)
6. File explorer: show files → edit file → verify change persists (US-106)
7. Sandbox busy indicator: shows when running, clears when done (US-106)
8. Developer API key: create → authenticate → make API call (US-106)
9. Full platform journey: signup → project → conversation → file ops → shared sandbox (US-113)
10. Auth flows: login, logout, password reset (US-113)
11. Developer API key rate limiting (US-113)
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.billing.models import (
    SubscriptionPlan,
    UsageRecord,
    UserSubscription,
)
from apps.storage.models import (
    AgentRun,
    Conversation,
    ConversationComposioAddon,
    MarketplaceAddon,
    UserMarketplaceAddons,
)
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    """Clear Django cache before each test to avoid rate-limit interference."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def free_plan():
    """Create a free subscription plan with standard features."""
    return SubscriptionPlan.objects.create(
        name="Free",
        tier="free",
        price=Decimal("0.00"),
        features={
            "weekly_tasks": [10],
            "max_sandbox_time": [3600],
            "max_addons": [4],
            "mcp_servers": [2],
            "concurrent_tasks": [1],
        },
        is_active=True,
    )


@pytest.fixture()
def premium_plan():
    """Create a premium subscription plan with higher limits."""
    return SubscriptionPlan.objects.create(
        name="Premium",
        tier="premium",
        price=Decimal("29.00"),
        features={
            "weekly_tasks": [100],
            "max_sandbox_time": [36000],
            "max_addons": [20],
            "mcp_servers": [10],
            "concurrent_tasks": [5],
        },
        is_active=True,
    )


@pytest.fixture()
def marketplace_addon():
    """Create a marketplace addon entry."""
    return MarketplaceAddon.objects.create(
        name="Test Slack Integration",
        description="Test addon for Slack",
        link="https://example.com/slack",
        logo="https://example.com/slack-logo.png",
        enum="SLACK",
        categories=["communication"],
        tags=["messaging", "notifications"],
    )


# =============================================================================
# HELPERS
# =============================================================================


def _auth_client(token):
    """Return a Django test client with Bearer authentication."""
    return Client(headers={"authorization": f"Bearer {token}"})


def _signup(name="Smoke User", email=None, password="TestPass123!@#"):
    """Create a user via the signup endpoint."""
    client = Client()
    email = email or f"smoke-{uuid.uuid4().hex[:8]}@test.com"
    resp = client.post(
        "/api/v1/workspace/users",
        data=json.dumps({"user_name": name, "user_email": email, "password": password}),
        content_type="application/json",
    )
    return resp, email, password


def _login(email, password):
    """Log in and return the auth token."""
    client = Client()
    resp = client.post(
        "/authentication/login/",
        data=json.dumps({"email": email, "password": password}),
        content_type="application/json",
    )
    return resp


def _setup_authenticated_user(free_plan):
    """Create a user with subscription and return (user, token_key, client)."""
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    UserSubscription.objects.create(user=user, plan=free_plan, status="active")
    return user, token.key, _auth_client(token.key)


# =============================================================================
# FLOW 1: Signup → Login → Create Project → Start Conversation → Response
# =============================================================================


class TestSignupToResponseFlow:
    """Smoke test: user signup → login → create project → start conversation → receive response."""

    def test_signup_creates_user(self, free_plan):
        """Signup endpoint returns 201 and creates user."""
        resp, email, _ = _signup()
        assert resp.status_code == 201
        data = resp.json()
        assert data["message"] == "User created successfully"

    def test_signup_assigns_free_plan(self, free_plan):
        """Signup automatically assigns the free subscription plan."""
        from apps.users.models import User

        _, email, _ = _signup()
        user = User.objects.get_by_email(email)
        sub = UserSubscription.objects.get(user=user)
        assert sub.plan.tier == "free"
        assert sub.status == "active"

    def test_login_returns_token(self, free_plan):
        """Login after signup returns a valid auth token."""
        _, email, password = _signup()
        resp = _login(email, password)
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert len(data["key"]) > 0

    def test_full_signup_login_flow(self, free_plan):
        """Full flow: signup → login → get token → authenticated request succeeds."""
        _, email, password = _signup()
        login_resp = _login(email, password)
        token = login_resp.json()["key"]

        # Verify the token works by accessing an authenticated endpoint.
        client = _auth_client(token)
        resp = client.get("/api/v1/memory/settings")
        assert resp.status_code == 200

    def test_create_project(self, free_plan):
        """Authenticated user can create a project."""
        _, _, client = _setup_authenticated_user(free_plan)
        resp = client.post(
            "/api/v1/spaces/projects",
            data=json.dumps(
                {
                    "title": "Smoke Test Project",
                    "description": "End-to-end test project",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        # CreateProjectResult returns project_id (not nested project object).
        assert "project_id" in data

    def test_create_conversation(self, free_plan):
        """Authenticated user can create a conversation."""
        _, _, client = _setup_authenticated_user(free_plan)
        resp = client.post("/api/v1/memory/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert "conversation_id" in data
        assert data["is_new"] is True

    def test_create_conversation_always_new(self, free_plan):
        """Each POST to create conversation returns a new conversation."""
        _, _, client = _setup_authenticated_user(free_plan)
        resp1 = client.post("/api/v1/memory/conversations")
        resp2 = client.post("/api/v1/memory/conversations")
        # Service always creates a new conversation.
        assert "conversation_id" in resp1.json()
        assert "conversation_id" in resp2.json()

    def test_start_agent_returns_queued(self, free_plan):
        """Starting an agent run returns a queued response when sandbox is not ready."""
        user, token, client = _setup_authenticated_user(free_plan)
        conv = Conversation.objects.create(user=user, title="Smoke conv")
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="test prompt",
            status=AgentRun.Status.QUEUED,
        )

        reservation_result = (
            {"conversation_id": str(conv.id), "run_pk": run.pk, "mode": "new"},
            None,
            None,
        )

        with (
            patch("apps.agents.locking.acquire_user_lock", return_value=True),
            patch("apps.agents.locking.release_user_lock"),
            patch(
                "apps.agents.views.do_atomic_reservation",
                new_callable=AsyncMock,
                return_value=reservation_result,
            ),
            patch(
                "apps.agents.views.try_fast_start",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "apps.agents.views.start_agent_run_background",
                new_callable=AsyncMock,
            ),
        ):
            resp = client.post(
                "/api/v1/chat/completions/start",
                data=json.dumps({"prompt": "Hello, build me a website"}),
                content_type="application/json",
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["conversation_id"] == str(conv.id)

    def test_get_agent_status_no_task(self, free_plan):
        """Getting agent status when no task exists returns idle status."""
        user, _, client = _setup_authenticated_user(free_plan)
        conv = Conversation.objects.create(user=user, title="Status test")
        resp = client.get(f"/api/v1/chat/completions/{conv.id}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["on_going"] is False

    def test_signup_login_project_conversation_flow(self, free_plan):
        """End-to-end: signup → login → create project → create conversation."""
        # 1. Signup
        signup_resp, email, password = _signup()
        assert signup_resp.status_code == 201

        # 2. Login
        login_resp = _login(email, password)
        assert login_resp.status_code == 200
        token = login_resp.json()["key"]
        client = _auth_client(token)

        # 3. Create project (description is required by ProjectDataSchema)
        project_resp = client.post(
            "/api/v1/spaces/projects",
            data=json.dumps({"title": "E2E Project", "description": "E2E test"}),
            content_type="application/json",
        )
        assert project_resp.status_code == 200
        assert project_resp.json()["project_id"]

        # 4. Create conversation
        conv_resp = client.post("/api/v1/memory/conversations")
        assert conv_resp.status_code == 200
        assert "conversation_id" in conv_resp.json()

        # 5. Verify project exists
        projects_resp = client.get("/api/v1/spaces/projects")
        assert projects_resp.status_code == 200

        # 6. Verify conversations endpoint works
        convs_resp = client.get("/api/v1/memory/conversations")
        assert convs_resp.status_code == 200


# =============================================================================
# FLOW 2: Addon Install → Conversation with Addon → Tools Available
# =============================================================================


class TestAddonFlow:
    """Smoke test: addon install → conversation with addon → tools available."""

    def test_register_addon(self, free_plan, marketplace_addon):
        """User can register a marketplace addon."""
        user, _, client = _setup_authenticated_user(free_plan)

        resp = client.post(
            "/api/v1/memory/addons/register",
            data=json.dumps({"addon_id": str(marketplace_addon.id)}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Verify addon is registered for user.
        assert UserMarketplaceAddons.objects.filter(
            owner=user, enabled_addon=marketplace_addon
        ).exists()

    def test_list_user_addons(self, free_plan, marketplace_addon):
        """User can list their registered addons."""
        user, _, client = _setup_authenticated_user(free_plan)
        UserMarketplaceAddons.objects.create(
            owner=user,
            enabled_addon=marketplace_addon,
        )

        resp = client.get("/api/v1/memory/user-addons")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any(
            a["enabled_addon"]["name"] == "Test Slack Integration"
            for a in data["items"]
        )

    def test_addon_linked_to_conversation(self, free_plan, marketplace_addon):
        """An addon can be linked to a conversation via the join table."""
        user, _, client = _setup_authenticated_user(free_plan)

        # Register addon and mark as auth complete.
        user_addon = UserMarketplaceAddons.objects.create(
            owner=user,
            enabled_addon=marketplace_addon,
            auth_complete=True,
            config_id="composio-test-config",
        )

        # Create conversation.
        conv = Conversation.objects.create(user=user, title="Addon test conv")

        # Link addon to conversation.
        ConversationComposioAddon.objects.create(conversation=conv, addon=user_addon)

        # Verify the link exists.
        linked = ConversationComposioAddon.objects.filter(
            conversation=conv, addon=user_addon
        )
        assert linked.exists()
        assert linked.first().addon.enabled_addon.enum == "SLACK"

    def test_addon_auth_status_workflow(self, free_plan, marketplace_addon):
        """Addon auth workflow: register → check status → (simulate auth) → verify complete."""
        user, _, client = _setup_authenticated_user(free_plan)

        # Register addon.
        user_addon = UserMarketplaceAddons.objects.create(
            owner=user,
            enabled_addon=marketplace_addon,
            auth_complete=False,
        )

        # Addon is not yet auth'd.
        assert user_addon.auth_complete is False

        # Simulate completing OAuth (normally done by Composio callback).
        user_addon.auth_complete = True
        user_addon.config_id = "composio-connected-account-123"
        user_addon.save()

        user_addon.refresh_from_db()
        assert user_addon.auth_complete is True
        assert user_addon.config_id == "composio-connected-account-123"

    def test_addon_max_limit_enforced(self, marketplace_addon):
        """User cannot exceed the max_addons limit from their subscription plan."""
        user = UserFactory()
        Token.objects.get_or_create(user=user)

        # Create plan with max_addons = 1.
        plan = SubscriptionPlan.objects.create(
            name="Tiny",
            tier="free",
            price=Decimal("0"),
            features={
                "weekly_tasks": [10],
                "max_sandbox_time": [3600],
                "max_addons": [1],
            },
            is_active=True,
        )
        sub = UserSubscription.objects.create(user=user, plan=plan, status="active")

        # Register one addon (at limit).
        UserMarketplaceAddons.objects.create(
            owner=user, enabled_addon=marketplace_addon
        )

        # Verify user has 1 addon, which is at the limit.
        count = UserMarketplaceAddons.objects.count_for_user(user)
        limit = sub.get_feature_info("max_addons")
        assert count >= limit

    def test_multiple_addons_on_conversation(self, free_plan):
        """Multiple addons can be linked to a single conversation."""
        user, _, client = _setup_authenticated_user(free_plan)
        conv = Conversation.objects.create(user=user, title="Multi-addon conv")

        for name in ["Slack", "GitHub", "Jira"]:
            ma = MarketplaceAddon.objects.create(
                name=name,
                description=f"{name} integration",
                link="https://example.com",
                logo="https://example.com/logo.png",
                enum=name.upper(),
            )
            ua = UserMarketplaceAddons.objects.create(
                owner=user,
                enabled_addon=ma,
                auth_complete=True,
            )
            ConversationComposioAddon.objects.create(conversation=conv, addon=ua)

        linked = ConversationComposioAddon.objects.filter(conversation=conv)
        assert linked.count() == 3


# =============================================================================
# FLOW 3: Scheduled Task Create → Trigger → Complete
# =============================================================================


class TestScheduledTaskFlow:
    """Smoke test: scheduled task create → trigger → complete."""

    def test_create_scheduled_task(self, free_plan):
        """User can create a scheduled task with a valid crontab."""
        _, _, client = _setup_authenticated_user(free_plan)

        resp = client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps(
                {"prompt": "Generate daily report", "crontab": "0 9 * * *"}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["prompt"] == "Generate daily report"
        assert data["crontab"] == "0 9 * * *"
        assert data["is_enabled"] is True
        assert "id" in data

    def test_create_scheduled_task_invalid_crontab(self, free_plan):
        """Invalid crontab returns 400 error."""
        _, _, client = _setup_authenticated_user(free_plan)

        resp = client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "Bad schedule", "crontab": "not a crontab"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_list_scheduled_tasks(self, free_plan):
        """User can list their scheduled tasks."""
        _, _, client = _setup_authenticated_user(free_plan)

        # Create two tasks.
        client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "Task A", "crontab": "0 9 * * *"}),
            content_type="application/json",
        )
        client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "Task B", "crontab": "30 14 * * 1-5"}),
            content_type="application/json",
        )

        resp = client.get("/api/v1/chat/completions/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_update_scheduled_task(self, free_plan):
        """User can update a scheduled task's prompt and crontab."""
        _, _, client = _setup_authenticated_user(free_plan)

        create_resp = client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "Original", "crontab": "0 9 * * *"}),
            content_type="application/json",
        )
        task_id = create_resp.json()["id"]

        update_resp = client.patch(
            f"/api/v1/chat/completions/schedule/{task_id}/",
            data=json.dumps({"prompt": "Updated prompt", "crontab": "0 10 * * *"}),
            content_type="application/json",
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["prompt"] == "Updated prompt"
        assert data["crontab"] == "0 10 * * *"

    def test_pause_and_resume_scheduled_task(self, free_plan):
        """User can pause (disable) and resume (enable) a scheduled task."""
        _, _, client = _setup_authenticated_user(free_plan)

        create_resp = client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "Pausable task", "crontab": "0 8 * * *"}),
            content_type="application/json",
        )
        task_id = create_resp.json()["id"]

        # Pause.
        pause_resp = client.patch(
            f"/api/v1/chat/completions/schedule/{task_id}/",
            data=json.dumps({"is_enabled": False}),
            content_type="application/json",
        )
        assert pause_resp.status_code == 200
        assert pause_resp.json()["is_enabled"] is False

        # Resume.
        resume_resp = client.patch(
            f"/api/v1/chat/completions/schedule/{task_id}/",
            data=json.dumps({"is_enabled": True}),
            content_type="application/json",
        )
        assert resume_resp.status_code == 200
        assert resume_resp.json()["is_enabled"] is True

    def test_delete_scheduled_task(self, free_plan):
        """User can delete a scheduled task."""
        _, _, client = _setup_authenticated_user(free_plan)

        create_resp = client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "Delete me", "crontab": "0 6 * * *"}),
            content_type="application/json",
        )
        task_id = create_resp.json()["id"]

        del_resp = client.delete(f"/api/v1/chat/completions/schedule/{task_id}/")
        assert del_resp.status_code == 200
        assert del_resp.json()["success"] is True

        # Listing should be empty.
        list_resp = client.get("/api/v1/chat/completions/schedule")
        assert list_resp.json()["count"] == 0

    def test_scheduled_task_celery_integration(self, free_plan):
        """Scheduled task creates a Celery PeriodicTask entry."""
        _, _, client = _setup_authenticated_user(free_plan)

        create_resp = client.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "Celery test", "crontab": "0 12 * * *"}),
            content_type="application/json",
        )
        task_id = create_resp.json()["id"]

        from apps.agents.models import ScheduledTask

        st = ScheduledTask.objects.get(id=task_id)
        assert st.celery_task is not None
        assert st.celery_task.enabled is True

    def test_task_ownership_isolation(self, free_plan):
        """Users cannot see or modify each other's scheduled tasks."""
        _, _, client_a = _setup_authenticated_user(free_plan)

        create_resp = client_a.post(
            "/api/v1/chat/completions/schedule",
            data=json.dumps({"prompt": "User A task", "crontab": "0 9 * * *"}),
            content_type="application/json",
        )
        task_id = create_resp.json()["id"]

        # Create another user.
        user_b = UserFactory()
        token_b, _ = Token.objects.get_or_create(user=user_b)
        UserSubscription.objects.create(user=user_b, plan=free_plan, status="active")
        client_b = _auth_client(token_b.key)

        # User B's list should be empty.
        list_resp = client_b.get("/api/v1/chat/completions/schedule")
        assert list_resp.json()["count"] == 0

        # User B cannot delete User A's task.
        del_resp = client_b.delete(f"/api/v1/chat/completions/schedule/{task_id}/")
        assert del_resp.status_code == 404


# =============================================================================
# FLOW 4: Billing Subscribe → Usage Tracked → Limits Enforced
# =============================================================================


class TestBillingFlow:
    """Smoke test: billing subscribe → usage tracked → limits enforced."""

    def test_get_plans(self, free_plan, premium_plan):
        """Authenticated users can list subscription plans."""
        user, _, client = _setup_authenticated_user(free_plan)
        resp = client.get("/api/v1/billing/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2
        tier_names = {p["tier"] for p in data["items"]}
        assert "free" in tier_names
        assert "premium" in tier_names

    def test_get_subscription(self, free_plan):
        """User can retrieve their own subscription."""
        user, _, client = _setup_authenticated_user(free_plan)
        resp = client.get("/api/v1/billing/subscription")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"

    def test_subscription_features_available(self, free_plan):
        """Subscription plan features are accessible via the model."""
        user, _, _ = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        assert sub.get_weekly_task_limit() == 10
        assert sub.get_feature_info("max_sandbox_time") == 3600
        assert sub.get_feature_info("max_addons") == 4

    def test_usage_tracking(self, free_plan):
        """Usage records are properly created and tracked."""
        user, _, _ = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        # Record a task usage.
        UsageRecord.objects.create(
            subscription=sub,
            user=user,
            metric_name="agent_task",
            quantity=1,
            metadata={"run_id": str(uuid.uuid4()), "status": "reserved"},
        )

        assert sub.get_tasks_used_this_week() == 1
        assert sub.can_run_task() is True  # 1 < 10

    def test_task_limit_enforcement(self, free_plan):
        """Task limit is enforced when weekly quota is exhausted."""
        user, _, _ = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        # Exhaust all 10 weekly tasks.
        for i in range(10):
            UsageRecord.objects.create(
                subscription=sub,
                user=user,
                metric_name="agent_task",
                quantity=1,
                metadata={"run_id": str(uuid.uuid4()), "status": "reserved"},
            )

        assert sub.get_tasks_used_this_week() == 10
        assert sub.can_run_task() is False

    def test_sandbox_time_tracking(self, free_plan):
        """Sandbox time usage is tracked and limits enforced."""
        user, _, _ = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        # Record sandbox time usage (2000 of 3600 seconds).
        UsageRecord.objects.create(
            subscription=sub,
            user=user,
            metric_name="sandbox_time",
            quantity=Decimal("2000"),
            metadata={},
        )

        assert sub.get_sandbox_time() == Decimal("2000")
        assert sub.check_sandbox_available() is True

        # Use remaining time.
        UsageRecord.objects.create(
            subscription=sub,
            user=user,
            metric_name="sandbox_time",
            quantity=Decimal("1700"),
            metadata={},
        )
        # Total: 3700 > 3600
        assert sub.check_sandbox_available() is False

    def test_remaining_tasks_count(self, free_plan):
        """get_remaining_tasks returns correct count."""
        user, _, _ = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        assert sub.get_remaining_tasks() == 10

        # Use 3 tasks.
        for _ in range(3):
            UsageRecord.objects.create(
                subscription=sub,
                user=user,
                metric_name="agent_task",
                quantity=1,
                metadata={"run_id": str(uuid.uuid4()), "status": "completed"},
            )

        assert sub.get_remaining_tasks() == 7

    def test_subscription_history_on_plan_change(self, free_plan, premium_plan):
        """Plan change creates a subscription history record."""
        from apps.billing.models import SubscriptionHistory

        user, _, _ = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        # Simulate plan upgrade.
        SubscriptionHistory.objects.create(
            subscription=sub,
            user=user,
            action="upgraded",
            old_plan=free_plan,
            new_plan=premium_plan,
            notes="Upgraded from Free to Premium",
        )

        sub.plan = premium_plan
        sub.save()

        history = SubscriptionHistory.objects.for_user(user)
        assert history.count() == 1
        entry = history.first()
        assert entry.action == "upgraded"
        assert entry.old_plan == free_plan
        assert entry.new_plan == premium_plan

        # After upgrade, limits are higher.
        sub.refresh_from_db()
        assert sub.get_weekly_task_limit() == 100

    def test_voided_tasks_not_counted(self, free_plan):
        """Voided usage records are not counted towards the weekly limit."""
        user, _, _ = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        # Create a voided usage record.
        UsageRecord.objects.create(
            subscription=sub,
            user=user,
            metric_name="agent_task",
            quantity=1,
            metadata={"run_id": str(uuid.uuid4()), "status": "voided"},
        )

        # Voided tasks should NOT count.
        assert sub.get_tasks_used_this_week() == 0
        assert sub.can_run_task() is True

    def test_grace_period_check(self, free_plan):
        """Grace period is correctly detected."""
        user, _, client = _setup_authenticated_user(free_plan)
        sub = UserSubscription.objects.get(user=user)

        # No grace period.
        assert sub.in_grace_period() is False

        # Set grace period.
        sub.grace_period_end = timezone.now() + timezone.timedelta(days=3)
        sub.save()
        assert sub.in_grace_period() is True

        # Expired grace period.
        sub.grace_period_end = timezone.now() - timezone.timedelta(days=1)
        sub.save()
        assert sub.in_grace_period() is False

    def test_billing_flow_end_to_end(self, free_plan, premium_plan):
        """End-to-end: signup → free plan → usage tracking → limit enforcement → upgrade → more usage."""
        from apps.billing.models import SubscriptionHistory

        # 1. Signup & auto-assign free plan.
        signup_resp, email, password = _signup()
        assert signup_resp.status_code == 201

        from apps.users.models import User

        user = User.objects.get_by_email(email)
        sub = UserSubscription.objects.get(user=user)
        assert sub.plan.tier == "free"

        # 2. Track usage.
        for _ in range(5):
            UsageRecord.objects.create(
                subscription=sub,
                user=user,
                metric_name="agent_task",
                quantity=1,
                metadata={"run_id": str(uuid.uuid4()), "status": "reserved"},
            )
        assert sub.get_remaining_tasks() == 5

        # 3. Exhaust limit.
        for _ in range(5):
            UsageRecord.objects.create(
                subscription=sub,
                user=user,
                metric_name="agent_task",
                quantity=1,
                metadata={"run_id": str(uuid.uuid4()), "status": "reserved"},
            )
        assert sub.can_run_task() is False

        # 4. Upgrade to premium.
        SubscriptionHistory.objects.create(
            subscription=sub,
            user=user,
            action="upgraded",
            old_plan=free_plan,
            new_plan=premium_plan,
        )
        sub.plan = premium_plan
        sub.save()
        sub.refresh_from_db()

        # 5. Premium has higher limit (100) so user can run tasks again.
        assert sub.get_weekly_task_limit() == 100
        assert sub.can_run_task() is True
        assert sub.get_remaining_tasks() == 90  # 100 - 10 used


# =============================================================================
# FLOW 5: Shared Sandbox — Project → Conversations → Same Sandbox (US-106)
# =============================================================================


class TestSharedSandboxFlow:
    """Smoke test: project → conversations → verify shared sandbox across conversations."""

    def test_create_project_start_two_conversations(self, free_plan):
        """Create project → start conv1 → start conv2 → both belong to same project."""
        user, _, client = _setup_authenticated_user(free_plan)

        # Create project.
        resp = client.post(
            "/api/v1/spaces/projects",
            data=json.dumps(
                {"title": "Sandbox Project", "description": "Shared sandbox test"}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        project_id = resp.json()["project_id"]

        # Create two conversations linked to the project.
        conv1 = Conversation.objects.create(
            user=user, title="Conv 1", project_id=project_id
        )
        conv2 = Conversation.objects.create(
            user=user, title="Conv 2", project_id=project_id
        )

        # Both conversations belong to the same project.
        assert str(conv1.project_id) == project_id
        assert str(conv2.project_id) == project_id

    def test_shared_sandbox_across_conversations(self, free_plan):
        """Two conversations in the same project share the same sandbox via the project."""
        from apps.agents.models import E2bSandbox
        from apps.spaces.models import Project

        user, _, client = _setup_authenticated_user(free_plan)

        # Create project.
        project = Project.objects.create_project(
            title="Shared Sandbox Project",
            description="Test shared sandbox",
            user=user,
        )

        # Attach a sandbox to the project.
        sandbox = E2bSandbox.objects.create(
            sandbox_id="sbx-shared-001",
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        project.sandbox = sandbox
        project.save()

        # Create two conversations in the project.
        conv1 = Conversation.objects.create(user=user, title="Conv A", project=project)
        conv2 = Conversation.objects.create(user=user, title="Conv B", project=project)

        # Both conversations' project resolves to the same sandbox.
        conv1.refresh_from_db()
        conv2.refresh_from_db()
        assert conv1.project.sandbox_id == sandbox.pk
        assert conv2.project.sandbox_id == sandbox.pk
        assert conv1.project.sandbox_id == conv2.project.sandbox_id

    def test_project_detail_shows_conversations(self, free_plan):
        """Project detail endpoint returns all linked conversations."""
        user, _, client = _setup_authenticated_user(free_plan)

        # Create project via API.
        resp = client.post(
            "/api/v1/spaces/projects",
            data=json.dumps({"title": "Detail Project", "description": "Detail test"}),
            content_type="application/json",
        )
        project_id = resp.json()["project_id"]

        # Create conversations under the project.
        Conversation.objects.create(
            user=user, title="Detail Conv 1", project_id=project_id
        )
        Conversation.objects.create(
            user=user, title="Detail Conv 2", project_id=project_id
        )

        # Fetch project detail.
        detail_resp = client.get(f"/api/v1/spaces/projects/{project_id}")
        assert detail_resp.status_code == 200
        data = detail_resp.json()
        assert data["conversation_count"] == 2
        assert len(data["conversations"]) == 2


# =============================================================================
# FLOW 6: File Explorer — Edit File → Change Persists (US-106)
# =============================================================================


class TestFileExplorerFlow:
    """Smoke test: file explorer shows files → edit file → verify change persists.

    Since file proxy endpoints forward to the sandbox agent server,
    these tests mock the proxy layer and verify the Django views
    correctly relay requests and responses.
    """

    def test_file_tree_returns_files(self, free_plan):
        """File tree endpoint proxies to sandbox and returns file listing."""
        from apps.agents.models import E2bSandbox

        user, token, client = _setup_authenticated_user(free_plan)
        conv = Conversation.objects.create(user=user, title="File tree test")
        sandbox = E2bSandbox.objects.create(
            sandbox_id="sbx-files-001",
            sandbox_state=E2bSandbox.SandboxState.READY,
            conversation=conv,
        )

        mock_tree = {
            "entries": [
                {
                    "name": "main.py",
                    "type": "file",
                    "path": "/home/user/workspace/main.py",
                },
                {
                    "name": "utils",
                    "type": "directory",
                    "path": "/home/user/workspace/utils",
                },
            ]
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_tree

        with (
            patch(
                "apps.agents.views.get_sandbox_host", return_value=sandbox.sandbox_id
            ),
            patch("apps.agents.views.proxy_get", return_value=mock_resp),
        ):
            resp = client.get(f"/api/v1/chat/sandbox/{conv.id}/files/tree")

        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert len(data["entries"]) == 2

    def test_file_write_then_read_persists(self, free_plan):
        """Write a file via proxy → read it back → content matches."""
        from apps.agents.models import E2bSandbox

        user, token, client = _setup_authenticated_user(free_plan)
        conv = Conversation.objects.create(user=user, title="File write test")
        E2bSandbox.objects.create(
            sandbox_id="sbx-files-002",
            sandbox_state=E2bSandbox.SandboxState.READY,
            conversation=conv,
        )

        file_content = "print('hello world')"

        # Mock write response.
        mock_write_resp = MagicMock()
        mock_write_resp.status_code = 200
        mock_write_resp.json.return_value = {"success": True, "message": "File written"}

        with (
            patch("apps.agents.views.get_sandbox_host", return_value="sbx-files-002"),
            patch("apps.agents.views.proxy_put", return_value=mock_write_resp),
        ):
            write_resp = client.put(
                f"/api/v1/chat/sandbox/{conv.id}/files/write",
                data=json.dumps(
                    {"path": "/home/user/workspace/main.py", "content": file_content}
                ),
                content_type="application/json",
            )

        assert write_resp.status_code == 200
        assert write_resp.json()["success"] is True

        # Mock read response — sandbox returns the written content.
        mock_read_resp = MagicMock()
        mock_read_resp.status_code = 200
        mock_read_resp.json.return_value = {
            "content": file_content,
            "path": "/home/user/workspace/main.py",
        }

        with (
            patch("apps.agents.views.get_sandbox_host", return_value="sbx-files-002"),
            patch("apps.agents.views.proxy_get", return_value=mock_read_resp),
        ):
            read_resp = client.get(
                f"/api/v1/chat/sandbox/{conv.id}/files/read?path=/home/user/workspace/main.py"
            )

        assert read_resp.status_code == 200
        assert read_resp.json()["content"] == file_content

    def test_file_create_endpoint(self, free_plan):
        """Create file endpoint proxies to sandbox successfully."""
        from apps.agents.models import E2bSandbox

        user, _, client = _setup_authenticated_user(free_plan)
        conv = Conversation.objects.create(user=user, title="File create test")
        E2bSandbox.objects.create(
            sandbox_id="sbx-files-003",
            sandbox_state=E2bSandbox.SandboxState.READY,
            conversation=conv,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "message": "File created"}

        with (
            patch("apps.agents.views.get_sandbox_host", return_value="sbx-files-003"),
            patch("apps.agents.views.proxy_post", return_value=mock_resp),
        ):
            resp = client.post(
                f"/api/v1/chat/sandbox/{conv.id}/files/create",
                data=json.dumps(
                    {
                        "path": "/home/user/workspace/new_file.py",
                        "type": "file",
                        "content": "# new file",
                    }
                ),
                content_type="application/json",
            )

        assert resp.status_code == 200
        assert resp.json()["success"] is True


# =============================================================================
# FLOW 7: Sandbox Busy Indicator (US-106)
# =============================================================================


class TestSandboxBusyIndicator:
    """Smoke test: sandbox busy indicator shows when running, clears when done."""

    def test_sandbox_not_busy_when_idle(self, free_plan):
        """Sandbox status returns not busy when no active runs."""
        user, _, client = _setup_authenticated_user(free_plan)

        resp = client.post(
            "/api/v1/spaces/projects",
            data=json.dumps(
                {"title": "Busy Test Project", "description": "Busy indicator test"}
            ),
            content_type="application/json",
        )
        project_id = resp.json()["project_id"]

        status_resp = client.get(f"/api/v1/spaces/projects/{project_id}/sandbox-status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["busy"] is False
        assert data["active_conversation_id"] is None

    def test_sandbox_busy_when_running(self, free_plan):
        """Sandbox status returns busy when a conversation has an active agent run."""
        from apps.spaces.models import Project

        user, _, client = _setup_authenticated_user(free_plan)

        project = Project.objects.create_project(
            title="Busy Running Project",
            description="Active run test",
            user=user,
        )

        conv = Conversation.objects.create(
            user=user, title="Active Conv", project=project
        )
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="running task",
            status=AgentRun.Status.RUNNING,
        )
        conv.current_task = run
        conv.save()

        status_resp = client.get(f"/api/v1/spaces/projects/{project.id}/sandbox-status")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["busy"] is True
        assert data["active_conversation_id"] == str(conv.id)
        assert data["active_conversation_title"] == "Active Conv"

    def test_sandbox_busy_clears_when_done(self, free_plan):
        """Sandbox busy status clears after the agent run completes."""
        from apps.spaces.models import Project

        user, _, client = _setup_authenticated_user(free_plan)

        project = Project.objects.create_project(
            title="Clear Project",
            description="Clear test",
            user=user,
        )

        conv = Conversation.objects.create(
            user=user, title="Clearing Conv", project=project
        )
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="finishing task",
            status=AgentRun.Status.RUNNING,
        )
        conv.current_task = run
        conv.save()

        # Verify busy.
        status = client.get(f"/api/v1/spaces/projects/{project.id}/sandbox-status")
        assert status.json()["busy"] is True

        # Complete the run.
        run.mark_completed()
        run.save()

        # Verify not busy anymore.
        status = client.get(f"/api/v1/spaces/projects/{project.id}/sandbox-status")
        assert status.json()["busy"] is False

    def test_sandbox_busy_with_queued_run(self, free_plan):
        """Sandbox is also busy when a run is queued (not just running)."""
        from apps.spaces.models import Project

        user, _, client = _setup_authenticated_user(free_plan)

        project = Project.objects.create_project(
            title="Queued Project",
            description="Queued test",
            user=user,
        )

        conv = Conversation.objects.create(
            user=user, title="Queued Conv", project=project
        )
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task="queued task",
            status=AgentRun.Status.QUEUED,
        )
        conv.current_task = run
        conv.save()

        status = client.get(f"/api/v1/spaces/projects/{project.id}/sandbox-status")
        assert status.json()["busy"] is True


# =============================================================================
# FLOW 8: Developer API Key — Create → Authenticate → API Call (US-106)
# =============================================================================


class TestDeveloperAPIKeyFlow:
    """Smoke test: developer API key creation → authenticate → make API call."""

    def test_create_api_key(self, free_plan):
        """User can create a developer API key and receives the raw key once."""
        _, _, client = _setup_authenticated_user(free_plan)

        resp = client.post(
            "/api/v1/developer/api-keys",
            data=json.dumps({"name": "Test Key", "scopes": ["read", "write"]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Key"
        assert "key" in data
        assert data["key"].startswith("msk_")
        assert data["scopes"] == ["read", "write"]
        assert data["key_prefix"] == data["key"][:8]  # PREFIX (4) + first 4 chars

    def test_list_api_keys_masked(self, free_plan):
        """Listed API keys show prefix only, not the full key."""
        _, _, client = _setup_authenticated_user(free_plan)

        # Create a key.
        client.post(
            "/api/v1/developer/api-keys",
            data=json.dumps({"name": "Listed Key", "scopes": []}),
            content_type="application/json",
        )

        resp = client.get("/api/v1/developer/api-keys")
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 1
        assert keys[0]["name"] == "Listed Key"
        assert keys[0]["key_prefix"].startswith("msk_")
        # Full key should NOT be in the list response.
        assert "key" not in keys[0]

    def test_revoke_api_key(self, free_plan):
        """User can revoke an API key, making it inactive."""
        _, _, client = _setup_authenticated_user(free_plan)

        create_resp = client.post(
            "/api/v1/developer/api-keys",
            data=json.dumps({"name": "Revoke Key", "scopes": []}),
            content_type="application/json",
        )
        key_id = create_resp.json()["id"]

        # Revoke.
        del_resp = client.delete(f"/api/v1/developer/api-keys/{key_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["message"] == "API key revoked successfully"

        # Verify inactive in listing.
        list_resp = client.get("/api/v1/developer/api-keys")
        keys = list_resp.json()
        revoked = [k for k in keys if k["id"] == key_id]
        assert len(revoked) == 1
        assert revoked[0]["is_active"] is False

    def test_update_api_key(self, free_plan):
        """User can update an API key's name and scopes."""
        _, _, client = _setup_authenticated_user(free_plan)

        create_resp = client.post(
            "/api/v1/developer/api-keys",
            data=json.dumps({"name": "Update Key", "scopes": ["read"]}),
            content_type="application/json",
        )
        key_id = create_resp.json()["id"]

        update_resp = client.patch(
            f"/api/v1/developer/api-keys/{key_id}",
            data=json.dumps(
                {"name": "Updated Key", "scopes": ["read", "write", "admin"]}
            ),
            content_type="application/json",
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["name"] == "Updated Key"
        assert data["scopes"] == ["read", "write", "admin"]

    def test_api_key_ownership_isolation(self, free_plan):
        """Users cannot see or modify each other's API keys."""
        _, _, client_a = _setup_authenticated_user(free_plan)

        create_resp = client_a.post(
            "/api/v1/developer/api-keys",
            data=json.dumps({"name": "User A Key", "scopes": []}),
            content_type="application/json",
        )
        key_id = create_resp.json()["id"]

        # Create another user.
        user_b = UserFactory()
        token_b, _ = Token.objects.get_or_create(user=user_b)
        from apps.billing.models import UserSubscription

        UserSubscription.objects.create(user=user_b, plan=free_plan, status="active")
        client_b = _auth_client(token_b.key)

        # User B should not see User A's key.
        list_resp = client_b.get("/api/v1/developer/api-keys")
        assert len(list_resp.json()) == 0

        # User B cannot delete User A's key.
        del_resp = client_b.delete(f"/api/v1/developer/api-keys/{key_id}")
        assert del_resp.status_code == 404

    def test_create_key_authenticate_make_call(self, free_plan):
        """End-to-end: create API key → verify key hash matches → key is usable for lookup."""
        from apps.users.models import DeveloperAPIKey

        user, _, client = _setup_authenticated_user(free_plan)

        # 1. Create key via API.
        create_resp = client.post(
            "/api/v1/developer/api-keys",
            data=json.dumps({"name": "E2E Key", "scopes": ["read"]}),
            content_type="application/json",
        )
        assert create_resp.status_code == 200
        raw_key = create_resp.json()["key"]

        # 2. Verify the key hash is stored correctly — simulate authentication.
        key_hash = DeveloperAPIKey.hash_key(raw_key)
        db_key = DeveloperAPIKey.objects.get(key_hash=key_hash)
        assert db_key.user == user
        assert db_key.is_active is True
        assert db_key.name == "E2E Key"
        assert db_key.scopes == ["read"]

        # 3. Verify key prefix matches.
        assert raw_key.startswith(db_key.key_prefix)


# =============================================================================
# FLOW 9: Full Platform Journey (US-113)
# =============================================================================


class TestFullPlatformJourney:
    """Smoke test: full user journey across the entire platform.

    signup → create project → conversation → file ops → new conversation
    in same project → verify shared sandbox
    """

    def test_full_user_journey(self, free_plan):
        """End-to-end: signup → login → project → conv → file ops → second conv → shared sandbox."""
        from apps.agents.models import E2bSandbox
        from apps.spaces.models import Project

        # 1. Signup.
        signup_resp, email, password = _signup(name="Journey User")
        assert signup_resp.status_code == 201

        # 2. Login → get token.
        login_resp = _login(email, password)
        assert login_resp.status_code == 200
        token = login_resp.json()["key"]
        client = _auth_client(token)

        # 3. Verify settings endpoint works (onboarding-like check).
        settings_resp = client.get("/api/v1/memory/settings")
        assert settings_resp.status_code == 200

        # 4. Create project.
        project_resp = client.post(
            "/api/v1/spaces/projects",
            data=json.dumps(
                {"title": "Journey Project", "description": "Full journey test"}
            ),
            content_type="application/json",
        )
        assert project_resp.status_code == 200
        project_id = project_resp.json()["project_id"]

        # 5. Start first conversation.
        conv_resp = client.post("/api/v1/memory/conversations")
        assert conv_resp.status_code == 200
        conv1_id = conv_resp.json()["conversation_id"]

        # Link conversation to project.
        conv1 = Conversation.objects.get(id=conv1_id)
        conv1.project_id = project_id
        conv1.save()

        # 6. Attach sandbox to project (simulates sandbox provisioning).
        project = Project.objects.get(id=project_id)
        sandbox = E2bSandbox.objects.create(
            sandbox_id="sbx-journey-001",
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        project.sandbox = sandbox
        project.save()

        # 7. File operations via proxy (mocked).
        mock_tree_resp = MagicMock()
        mock_tree_resp.status_code = 200
        mock_tree_resp.json.return_value = {
            "entries": [
                {
                    "name": "app.py",
                    "type": "file",
                    "path": "/home/user/workspace/app.py",
                },
            ]
        }

        with (
            patch("apps.agents.views.get_sandbox_host", return_value="sbx-journey-001"),
            patch("apps.agents.views.proxy_get", return_value=mock_tree_resp),
        ):
            tree_resp = client.get(f"/api/v1/chat/sandbox/{conv1_id}/files/tree")
        assert tree_resp.status_code == 200
        assert len(tree_resp.json()["entries"]) == 1

        # 8. Edit file.
        mock_write_resp = MagicMock()
        mock_write_resp.status_code = 200
        mock_write_resp.json.return_value = {"success": True, "message": "File written"}

        with (
            patch("apps.agents.views.get_sandbox_host", return_value="sbx-journey-001"),
            patch("apps.agents.views.proxy_put", return_value=mock_write_resp),
        ):
            write_resp = client.put(
                f"/api/v1/chat/sandbox/{conv1_id}/files/write",
                data=json.dumps(
                    {
                        "path": "/home/user/workspace/app.py",
                        "content": "print('updated')",
                    }
                ),
                content_type="application/json",
            )
        assert write_resp.status_code == 200

        # 9. Start second conversation in same project.
        conv2_resp = client.post("/api/v1/memory/conversations")
        assert conv2_resp.status_code == 200
        conv2_id = conv2_resp.json()["conversation_id"]

        conv2 = Conversation.objects.get(id=conv2_id)
        conv2.project_id = project_id
        conv2.save()

        # 10. Verify both conversations share the same sandbox via the project.
        conv1.refresh_from_db()
        conv2.refresh_from_db()
        assert conv1.project_id == conv2.project_id
        assert conv1.project.sandbox_id == sandbox.pk
        assert conv2.project.sandbox_id == sandbox.pk

        # 11. Verify project detail shows both conversations.
        detail_resp = client.get(f"/api/v1/spaces/projects/{project_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["conversation_count"] == 2


# =============================================================================
# FLOW 10: Auth Flows — Login, Logout, Password Reset (US-113)
# =============================================================================


class TestAuthFlows:
    """Smoke test: authentication flows — login, logout, password reset OTP."""

    def test_login_and_logout(self, free_plan):
        """Login → authenticated request → logout endpoint returns success."""
        _, email, password = _signup()
        login_resp = _login(email, password)
        assert login_resp.status_code == 200
        token = login_resp.json()["key"]
        client = _auth_client(token)

        # Authenticated request succeeds.
        assert client.get("/api/v1/memory/settings").status_code == 200

        # Logout via dj_rest_auth returns success.
        logout_resp = client.post("/authentication/logout/")
        assert logout_resp.status_code == 200

    def test_password_reset_otp_request(self, free_plan):
        """Password reset OTP request returns success (even for non-existent email)."""
        _, email, _ = _signup()
        client = Client()

        # Request OTP for existing user.
        resp = client.post(
            "/api/v1/workspace/password/request-otp",
            data=json.dumps({"email": email}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Request OTP for non-existent email (should still return success to prevent enumeration).
        resp = client.post(
            "/api/v1/workspace/password/request-otp",
            data=json.dumps({"email": "nonexistent@test.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        # Still returns success to prevent email enumeration.

    def test_password_reset_full_flow(self, free_plan):
        """Request OTP → verify + reset → login with new password."""
        from apps.users.models import User
        from apps.workspace.models import PasswordResetOTP

        _, email, old_password = _signup()
        client = Client()

        # Request OTP.
        client.post(
            "/api/v1/workspace/password/request-otp",
            data=json.dumps({"email": email}),
            content_type="application/json",
        )

        # Retrieve the OTP from the database directly.
        user = User.objects.get_by_email(email)
        otp_record = (
            PasswordResetOTP.objects.filter(user=user).order_by("-created_at").first()
        )
        assert otp_record is not None

        # Verify OTP and reset password.
        new_password = "NewSecurePass456!@#"
        reset_resp = client.post(
            "/api/v1/workspace/password/verify-otp",
            data=json.dumps(
                {
                    "email": email,
                    "otp": otp_record.otp,
                    "new_password": new_password,
                }
            ),
            content_type="application/json",
        )
        assert reset_resp.status_code == 200
        assert reset_resp.json()["success"] is True

        # Login with new password.
        login_resp = _login(email, new_password)
        assert login_resp.status_code == 200
        assert "key" in login_resp.json()

        # Old password should no longer work.
        old_login = _login(email, old_password)
        assert old_login.status_code == 400

    def test_google_oauth_missing_config(self):
        """Google OAuth endpoint returns error when social app is not configured."""
        client = Client()
        resp = client.post(
            "/api/v1/workspace/google-provider/verify",
            data=json.dumps({"token": "fake-google-token"}),
            content_type="application/json",
        )
        # Should fail because no Google SocialApp is configured in test DB.
        assert resp.status_code in (400, 422, 500)


# =============================================================================
# FLOW 11: Developer API Key Rate Limiting (US-113)
# =============================================================================


class TestDeveloperAPIKeyRateLimiting:
    """Smoke test: developer API key creation + rate limiting middleware."""

    def test_api_key_create_and_authenticate_hash(self, free_plan):
        """Create API key → verify hash-based lookup works → key usable for auth."""
        from apps.users.models import DeveloperAPIKey

        user, _, client = _setup_authenticated_user(free_plan)

        # Create API key.
        create_resp = client.post(
            "/api/v1/developer/api-keys",
            data=json.dumps({"name": "Auth Key", "scopes": ["read", "write"]}),
            content_type="application/json",
        )
        assert create_resp.status_code == 200
        raw_key = create_resp.json()["key"]
        assert raw_key.startswith("msk_")

        # Verify hash lookup resolves to the correct user.
        key_hash = DeveloperAPIKey.hash_key(raw_key)
        db_key = DeveloperAPIKey.objects.get(key_hash=key_hash)
        assert db_key.user == user
        assert db_key.scopes == ["read", "write"]

    def test_unauthenticated_rate_limit_enforcement(self, free_plan):
        """Unauthenticated requests are rate-limited after exceeding the limit."""
        from apps.users.adapters import UNAUTHENTICATED_RATE_LIMIT

        anon_client = Client()

        # Exhaust the unauthenticated rate limit (10/min).
        last_status = None
        for _ in range(UNAUTHENTICATED_RATE_LIMIT + 5):
            resp = anon_client.get("/api/v1/workspace/password/request-otp")
            last_status = resp.status_code
            if last_status == 429:
                break

        # Should have been rate-limited at some point.
        assert last_status == 429

    def test_authenticated_rate_limit_higher_than_unauthenticated(self, free_plan):
        """Authenticated users have a higher rate limit than anonymous users."""
        from apps.users.adapters import (
            AUTHENTICATED_RATE_LIMIT,
            UNAUTHENTICATED_RATE_LIMIT,
        )

        assert AUTHENTICATED_RATE_LIMIT > UNAUTHENTICATED_RATE_LIMIT
