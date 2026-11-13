"""
Integration Test Fixtures for Agent Executor

These tests run against the REAL database, REAL Redis,
and a REAL running server.

Requirements:
- Redis running
- PostgreSQL running
- Django server running: daphne -p 8000 config.asgi:application
"""

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import django
import httpx
import pytest

# Setup Django before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from django.conf import settings  # noqa: E402
from rest_framework.authtoken.models import Token  # noqa: E402

from apps.billing.models import SubscriptionPlan, UserSubscription  # noqa: E402
from apps.storage.models import Conversation  # noqa: E402
from apps.users.models import User  # noqa: E402

# Server configuration - adjust if needed
API_SERVER_HOST = os.environ.get("API_TEST_HOST", "localhost")
API_SERVER_PORT = os.environ.get("API_TEST_PORT", "8000")
API_BASE_URL = f"http://{API_SERVER_HOST}:{API_SERVER_PORT}"


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class SSEMessage:
    """Represents a message received from SSE stream"""

    raw: dict
    msg_type: str = ""
    status: Optional[str] = None
    error: Optional[str] = None
    content: Optional[str] = None

    def __post_init__(self):
        self.msg_type = self.raw.get("type", "")
        self.status = self.raw.get("status")
        self.error = self.raw.get("error")
        self.content = self.raw.get("content")

    @property
    def is_terminal(self) -> bool:
        return self.msg_type == "complete" or self.status in (
            "completed",
            "error",
            "cancelled",
        )


@dataclass
class ConversationResult:
    """Result from a conversation task"""

    messages: list = field(default_factory=list)
    final_status: Optional[str] = None
    error: Optional[str] = None
    task_id: Optional[str] = None
    conversation_id: Optional[str] = None

    @property
    def response_text(self) -> str:
        for msg in reversed(self.messages):
            if isinstance(msg, SSEMessage) and msg.content:
                return msg.content
        return ""

    @property
    def all_text(self) -> str:
        texts = []
        for msg in self.messages:
            if isinstance(msg, SSEMessage) and msg.content:
                texts.append(msg.content)
        return " ".join(texts)


# ============================================================================
# SESSION-SCOPED EVENT LOOP
# ============================================================================


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# REAL DATABASE FIXTURES
# ============================================================================


def create_test_user_sync() -> Tuple[User, str]:
    """Create a real test user in the database with all required configs"""
    unique_id = uuid.uuid4().hex[:8]
    email = f"test_{unique_id}@integration-test.local"

    user = User.objects.create_user(
        email=email,
        password="IntegrationTest123!",
        name=f"Integration Test User {unique_id}",
    )

    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def create_subscription_sync(user: User, tier: str = "free") -> UserSubscription:
    """Create a real subscription in the database"""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        tier=tier,
        defaults={
            "name": f"{tier.title()} Test Plan",
            "price": 0 if tier == "free" else 19,
            "features": {
                "max_concurrent_tasks": (5, "5 tasks"),
                "max_addons_per_task": (5, "5 addons"),
                "max_mcp_per_task": (5, "5 MCP"),
                "weekly_tasks": (1000, "1000 tasks"),
                "max_sandbox_time": (120, "120 minutes"),
                "use_custom_llm": (True, "Yes"),
                "use_custom_mcp": (True, "Yes"),
            },
        },
    )

    subscription, _ = UserSubscription.objects.get_or_create(
        user=user, defaults={"plan": plan, "status": "active"}
    )
    return subscription


def create_conversation_sync(user: User, title: str = None) -> Conversation:
    """Create a real conversation in the database"""
    title = title or f"Integration Test {uuid.uuid4().hex[:8]}"
    return Conversation.objects.create(user=user, title=title)


def cleanup_test_user_sync(user: User) -> None:
    """Clean up all data for a test user"""
    Conversation.objects.filter(user=user).delete()
    UserSubscription.objects.filter(user=user).delete()
    Token.objects.filter(user=user).delete()
    user.delete()


# Async wrappers
async def create_test_user() -> Tuple[User, str]:
    return await sync_to_async(create_test_user_sync)()


async def create_subscription(user: User, tier: str = "free") -> UserSubscription:
    return await sync_to_async(create_subscription_sync)(user, tier)


async def create_conversation(user: User, title: str = None) -> Conversation:
    return await sync_to_async(create_conversation_sync)(user, title)


async def cleanup_test_user(user: User) -> None:
    return await sync_to_async(cleanup_test_user_sync)(user)


# ============================================================================
# HTTP API CLIENT
# ============================================================================


class AgentAPIClient:
    """
    HTTP API client for agent execution.
    Replaces the WebSocket client with HTTP API + SSE streaming.
    """

    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Token {token}"}
        self.client = httpx.AsyncClient(
            base_url=API_BASE_URL, headers=self.headers, timeout=180.0
        )

    async def execute_task(self, message: str, **extra_data) -> dict:
        """Start an agent task execution."""
        data = {"message": message, **extra_data}
        response = await self.client.post("/api/agents/execute", json=data)
        response.raise_for_status()
        return response.json()

    async def get_task_status(self, conversation_id: str) -> dict:
        """Get task status."""
        response = await self.client.get(f"/api/agents/tasks/{conversation_id}/status")
        response.raise_for_status()
        return response.json()

    async def stream_messages(
        self, conversation_id: str, timeout: float = 180.0
    ) -> ConversationResult:
        """Stream SSE messages until task completes."""
        result = ConversationResult()

        async with self.client.stream(
            "GET", f"/api/agents/tasks/{conversation_id}/stream", timeout=timeout
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    msg = SSEMessage(raw=data)
                    result.messages.append(msg)

                    if msg.is_terminal:
                        result.final_status = msg.status or data.get("status")
                        break

        return result

    async def execute_and_stream(
        self, message: str, **extra_data
    ) -> ConversationResult:
        """Execute a task and stream results until completion."""
        # Start the task
        exec_response = await self.execute_task(message, **extra_data)

        result = ConversationResult(
            task_id=exec_response.get("task_id"),
            conversation_id=exec_response.get("conversation_id"),
        )

        if exec_response.get("status") == "capacity_exceeded":
            result.final_status = "capacity_exceeded"
            result.error = "Server at capacity"
            return result

        # Stream the results
        stream_result = await self.stream_messages(result.conversation_id)
        result.messages = stream_result.messages
        result.final_status = stream_result.final_status
        result.error = stream_result.error

        return result

    async def close(self):
        await self.client.aclose()


@asynccontextmanager
async def api_client(token: str):
    """Context manager for API client."""
    client = AgentAPIClient(token)
    try:
        yield client
    finally:
        await client.close()


# ============================================================================
# REDIS HELPERS
# ============================================================================

import redis.asyncio as aioredis  # noqa: E402


class RedisHelper:
    """Helper for Redis operations"""

    def __init__(self):
        self._client: Optional[aioredis.Redis] = None

    async def get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = await aioredis.from_url(
                settings.ARQ_REDIS_URL, encoding="utf-8", decode_responses=True
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_active_task_count(self) -> int:
        client = await self.get_client()
        return await client.zcard("active_agent_tasks")

    async def simulate_full_capacity(self) -> None:
        count = getattr(settings, "MAX_AGENTS_WORKERS", 12)
        client = await self.get_client()
        for i in range(count):
            await client.zadd("active_agent_tasks", {f"fake_task_{i}": time.time()})

    async def clear_fake_tasks(self) -> None:
        client = await self.get_client()
        for i in range(20):
            await client.zrem("active_agent_tasks", f"fake_task_{i}")


@asynccontextmanager
async def redis_helper():
    helper = RedisHelper()
    try:
        yield helper
    finally:
        await helper.close()


@asynccontextmanager
async def simulate_capacity_exceeded():
    """Simulate system at full capacity"""
    async with redis_helper() as helper:
        await helper.simulate_full_capacity()
        try:
            yield helper
        finally:
            await helper.clear_fake_tasks()


# ============================================================================
# TEST CONTEXT MANAGER
# ============================================================================


@dataclass
class TestContext:
    """Holds test user, token, subscription for cleanup"""

    user: User
    token: str
    subscription: UserSubscription
    conversations: List[Conversation] = field(default_factory=list)


@asynccontextmanager
async def test_context(tier: str = "free"):
    """
    Create a complete test context with user, token, subscription.
    Automatically cleans up after the test.
    """
    user, token = await create_test_user()
    subscription = await create_subscription(user, tier)
    ctx = TestContext(user=user, token=token, subscription=subscription)

    try:
        yield ctx
    finally:
        await cleanup_test_user(user)


async def add_conversation(ctx: TestContext, title: str = None) -> Conversation:
    """Add a conversation to the test context"""
    conv = await create_conversation(ctx.user, title)
    ctx.conversations.append(conv)
    return conv
