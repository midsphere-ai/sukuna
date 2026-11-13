"""Django models for the agents app — sandbox records and MCP configs."""

from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.files import File
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from e2b.exceptions import NotFoundException
from e2b_desktop import Sandbox

from apps.storage.models import Conversation, StoredFile

if TYPE_CHECKING:
    from apps.users.models import User

logger = logging.getLogger(__name__)


class UserCustomMCPConfig(models.Model):
    """
    Stores user-defined custom MCP (Midsphere Connector Protocol) server configurations.
    """

    class ServerType(models.TextChoices):
        """Supported MCP server transport types."""

        STDIO = "stdio", _("Stdio")
        SSE = "sse", _("SSE")
        STREAMABLE_HTTP = "streamable-http", _("Streamable HTTP")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_configs",
        verbose_name=_("User"),
    )
    server_name = models.CharField(
        _("Server Name"), max_length=100, blank=False, null=False
    )
    server_type = models.CharField(
        _("Server Type"),
        max_length=20,
        choices=ServerType.choices,
        default=ServerType.STDIO,
    )
    command = models.TextField(_("Command"), blank=True, null=True)
    arguments = models.TextField(_("Arguments"), blank=True)
    env = models.TextField(
        _("Environment Variables"),
        blank=True,
        help_text=_("JSON-formatted string of environment variables."),
    )

    url = models.URLField(
        _("Server URL"),
        blank=True,
        null=True,
        help_text=_("URL for SSE or Streamable HTTP servers"),
    )
    timeout = models.IntegerField(
        _("Timeout"), blank=True, null=True, help_text=_("Timeout in seconds")
    )
    sse_read_timeout = models.IntegerField(
        _("SSE Read Timeout"),
        blank=True,
        null=True,
        help_text=_("SSE Read Timeout in seconds"),
    )
    client_session_timeout_seconds = models.FloatField(
        _("Client Session Timeout"),
        blank=True,
        null=True,
        help_text=_("Session timeout in seconds"),
    )

    description = models.TextField(_("Description"), blank=True)

    # Timestamps
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    def __str__(self):
        """Return a human-readable representation of this MCP config."""
        return f"{self.user}'s {self.server_name} MCP Config"

    class Meta:
        """Meta options for UserCustomMCPConfig."""

        verbose_name = _("User Custom MCP Configuration")
        verbose_name_plural = _("User Custom MCP Configurations")
        unique_together = ("user", "server_name")
        ordering = ["-date_created"]


class UserProviderConfig(models.Model):
    """User-configured LLM provider for a specific tool slot (BYOM).

    Each row stores one complete provider configuration for a single slot
    (lead_agent, vision, browser, or audio).  API keys are encrypted at rest
    with Fernet using the ``BYOM_ENCRYPTION_KEY`` Django setting.
    """

    class ToolSlot(models.TextChoices):
        LEAD_AGENT = "lead_agent", _("Lead Agent")
        VISION = "vision", _("Vision")
        BROWSER = "browser", _("Browser")
        AUDIO = "audio", _("Audio")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_configs",
        verbose_name=_("User"),
    )
    tool_slot = models.CharField(
        _("Tool Slot"),
        max_length=20,
        choices=ToolSlot.choices,
    )
    provider_name = models.CharField(
        _("Provider"),
        max_length=50,
        help_text=_("e.g. openai, anthropic, gemini, azure_openai"),
    )
    model_name = models.CharField(
        _("Model Name"),
        max_length=200,
        help_text=_("e.g. gpt-4o, claude-sonnet-4-20250514"),
    )
    api_key_encrypted = models.BinaryField(
        _("Encrypted API Key"),
        help_text=_("Fernet-encrypted API key.  The raw key is never exposed."),
    )
    base_url = models.URLField(_("Base URL"), blank=True, default="")
    extras = models.JSONField(
        _("Provider Extras"),
        default=dict,
        blank=True,
        help_text=_("Provider-specific config: Azure deployment, region, etc."),
    )
    is_active = models.BooleanField(_("Active"), default=True)

    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    class Meta:
        verbose_name = _("User Provider Config")
        verbose_name_plural = _("User Provider Configs")
        unique_together = ("user", "tool_slot")
        ordering = ["-date_created"]

    def __str__(self) -> str:
        return (
            f"{self.user} / {self.tool_slot} → {self.provider_name}:{self.model_name}"
        )

    # ── Encryption helpers ────────────────────────────────────────────────

    def set_api_key(self, raw_key: str) -> None:
        """Encrypt and store an API key."""
        from cryptography.fernet import Fernet

        key = settings.BYOM_ENCRYPTION_KEY
        if not key:
            raise ValueError("BYOM_ENCRYPTION_KEY is not configured")
        f = Fernet(key.encode() if isinstance(key, str) else key)
        self.api_key_encrypted = f.encrypt(raw_key.encode())

    def get_api_key(self) -> str:
        """Decrypt and return the stored API key."""
        from cryptography.fernet import Fernet

        key = settings.BYOM_ENCRYPTION_KEY
        if not key:
            raise ValueError("BYOM_ENCRYPTION_KEY is not configured")
        f = Fernet(key.encode() if isinstance(key, str) else key)
        return f.decrypt(bytes(self.api_key_encrypted)).decode()

    @property
    def api_key_masked(self) -> str:
        """Return a masked version of the API key for display."""
        try:
            raw = self.get_api_key()
            if len(raw) <= 8:
                return "****"
            return raw[:4] + "****" + raw[-4:]
        except Exception:
            return "****"


class E2bSandboxQuerySet(models.QuerySet["E2bSandbox"]):
    """Custom QuerySet for E2bSandbox with chainable filters."""

    def active(self) -> E2bSandboxQuerySet:
        """Exclude terminated and error sandboxes."""
        return self.exclude(
            sandbox_state__in=[
                E2bSandbox.SandboxState.TERMINATED,
                E2bSandbox.SandboxState.ERROR,
            ]
        )

    def by_state(self, state: str) -> E2bSandboxQuerySet:
        """Filter by sandbox state."""
        return self.filter(sandbox_state=state)

    def for_conversation(self, conversation: Conversation) -> E2bSandboxQuerySet:
        """Filter sandboxes belonging to a conversation."""
        return self.filter(conversation=conversation)

    def pool(self) -> E2bSandboxQuerySet:
        """Filter to unassigned pool sandboxes."""
        return self.filter(conversation__isnull=True)

    def latest_first(self) -> E2bSandboxQuerySet:
        """Order by most recent start_time."""
        return self.order_by("-start_time")


class E2bSandboxManager(models.Manager["E2bSandbox"]):
    """Custom manager for E2bSandbox with common query shortcuts."""

    def get_queryset(self) -> E2bSandboxQuerySet:
        return E2bSandboxQuerySet(self.model, using=self._db)

    def active_for_conversation(self, conversation: Conversation) -> E2bSandboxQuerySet:
        """Return active (non-terminated, non-error) sandboxes for a conversation,
        ordered by most recent first."""
        return (
            self.get_queryset().for_conversation(conversation).active().latest_first()
        )

    def ready_for_conversation(self, conversation: Conversation) -> E2bSandboxQuerySet:
        """Return READY sandboxes for a conversation, ordered by most recent first."""
        return (
            self.get_queryset()
            .for_conversation(conversation)
            .by_state(E2bSandbox.SandboxState.READY)
            .latest_first()
        )

    def pool_ready(self) -> E2bSandboxQuerySet:
        """Return READY pool sandboxes (no conversation assigned)."""
        return self.get_queryset().pool().by_state(E2bSandbox.SandboxState.READY)

    def pool_stale(self, max_age_minutes: int = 50) -> E2bSandboxQuerySet:
        """Return pool sandboxes older than max_age_minutes."""
        cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
        return self.pool_ready().filter(start_time__lte=cutoff)

    def pool_stale_creating(self, max_age_minutes: int = 10) -> E2bSandboxQuerySet:
        """Return pool sandboxes stuck in CREATING longer than max_age_minutes."""
        cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
        return (
            self.get_queryset()
            .pool()
            .by_state(E2bSandbox.SandboxState.CREATING)
            .filter(start_time__lte=cutoff)
        )

    def idle_past_deadline(self) -> E2bSandboxQuerySet:
        """Return READY sandboxes past their delayed_termination_at time."""
        return (
            self.get_queryset()
            .by_state(E2bSandbox.SandboxState.READY)
            .filter(
                delayed_termination_at__isnull=False,
                delayed_termination_at__lte=timezone.now(),
            )
        )

    def active_for_project(self, project) -> E2bSandboxQuerySet:
        """Return active sandboxes linked to a project via Project.sandbox OneToOne."""
        from apps.spaces.models import Project

        if project is None:
            return self.get_queryset().none()
        sandbox_id = (
            Project.objects.filter(pk=project.pk)
            .values_list("sandbox_id", flat=True)
            .first()
        )
        if sandbox_id is None:
            return self.get_queryset().none()
        return self.get_queryset().filter(pk=sandbox_id).active().latest_first()

    def ready_for_project(self, project) -> E2bSandboxQuerySet:
        """Return READY sandboxes linked to a project."""
        return self.active_for_project(project).by_state(E2bSandbox.SandboxState.READY)

    def for_user(self, user: User) -> E2bSandboxQuerySet:
        """Return all sandboxes belonging to a user's conversations."""
        return self.get_queryset().filter(conversation__user=user)


class E2bSandbox(models.Model):
    """Tracks an E2B sandbox instance and its lifecycle state."""

    class SandboxState(models.TextChoices):
        """Possible lifecycle states for an E2B sandbox."""

        CREATING = "creating", _("Creating")
        READY = "ready", _("Ready")
        PAUSED = "paused", _("Paused")
        TERMINATED = "terminated", _("Terminated")
        ERROR = "error", _("Error")

    sandbox_id = models.TextField(_("E2B Sandbox ID"), blank=True)
    start_time = models.DateTimeField(_("Date Created"), auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    sandbox_state = models.CharField(
        _("Sandbox State"),
        max_length=20,
        choices=SandboxState.choices,
        default=SandboxState.CREATING,
    )

    usage_in_seconds = models.BigIntegerField(default=0)
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    # Delayed termination: when set, sandbox stays alive until this time
    delayed_termination_at = models.DateTimeField(
        _("Delayed Termination At"),
        null=True,
        blank=True,
        help_text=_("If set, sandbox will be paused by Celery task after this time"),
    )

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        related_name="sandbox_conversation",
        null=True,
        blank=True,
    )

    objects: E2bSandboxManager = E2bSandboxManager()

    # -- Deprecated boolean properties (derive from sandbox_state) --

    @property
    def is_running(self) -> bool:
        """Deprecated: use sandbox_state == 'ready' instead."""
        return self.sandbox_state == self.SandboxState.READY

    @is_running.setter
    def is_running(self, value: bool) -> None:
        """Deprecated setter for backward compat."""
        if value:
            self.sandbox_state = self.SandboxState.READY
        elif self.sandbox_state == self.SandboxState.READY:
            self.sandbox_state = self.SandboxState.TERMINATED

    @property
    def is_paused(self) -> bool:
        """Deprecated: use sandbox_state == 'paused' instead."""
        return self.sandbox_state == self.SandboxState.PAUSED

    @is_paused.setter
    def is_paused(self, value: bool) -> None:
        """Deprecated setter for backward compat."""
        if value:
            self.sandbox_state = self.SandboxState.PAUSED
        elif self.sandbox_state == self.SandboxState.PAUSED:
            self.sandbox_state = self.SandboxState.READY

    def _get_remaining_sandbox_time(self, user: User) -> int:
        """Return sandbox timeout in seconds.

        With credit-based billing, there is no subscription-level sandbox time
        cap — credits gate usage instead. The timeout here is purely an
        infrastructure guard (E2B sessions are rotated at 50 min anyway).
        """
        return 3600

    @staticmethod
    def _build_sandbox_envs() -> dict[str, str]:
        """Build sandbox env vars required by agent_server startup.

        Includes mandatory vault settings, proxy auth key, and selected optional
        runtime knobs when present in the host environment.
        """
        envs: dict[str, str] = {}

        for key in ("VAULT_ADDR", "VAULT_TOKEN"):
            value = os.getenv(key)
            if value:
                envs[key] = value

        api_key = getattr(settings, "AGENT_SERVER_API_KEY", "")
        if api_key:
            envs["API_KEY"] = api_key
            envs["SUKUNA_AGENT_SERVER_API_KEY"] = api_key

        envs["SKIP_DB_DDL"] = os.getenv("SKIP_DB_DDL", "true")
        envs["PORT"] = str(getattr(settings, "SANDBOX_AGENT_SERVER_PORT", 8000))

        # JWT secret for direct streaming (frontend → sandbox, bypassing proxy)
        stream_secret = getattr(settings, "SUKUNA_STREAM_JWT_SECRET", "") or getattr(
            settings, "SANDBOX_STREAM_JWT_SECRET", ""
        )
        if stream_secret:
            envs["SUKUNA_STREAM_JWT_SECRET"] = stream_secret

        optional_passthrough = (
            "AGENT_MODEL",
            "AGENT_MAX_STEPS",
            "AGENT_INSTRUCTIONS",
            "AGENT_RUN_TIMEOUT_SECONDS",
            "HITL_TIMEOUT_SECONDS",
            "SUKUNA_BACKEND_USAGE_FLUSH_SECONDS",
            "SUKUNA_BACKEND_USAGE_FLUSH_EVENTS",
        )
        for key in optional_passthrough:
            value = os.getenv(key)
            if value:
                envs[key] = value

        return envs

    def create_sandbox(
        self, api_key: str | None = None, user: User | None = None
    ) -> Sandbox | None:
        """Create a new E2B sandbox instance and start the agent server inside it.

        Returns the E2B Sandbox object, or None on failure.
        """
        try:
            logger.info("[SANDBOX] Creating new sandbox (record pk=%s)", self.pk)
            self.sandbox_state = self.SandboxState.CREATING
            self.save(update_fields=["sandbox_state", "date_updated"])

            timeout = 3600

            create_kwargs: dict[str, Any] = {
                "template": settings.AGENT_SANDBOX_TEMPLATE,
                "timeout": timeout,
                "envs": self._build_sandbox_envs(),
            }
            if api_key:
                create_kwargs["api_key"] = api_key

            sandbox = Sandbox.create(**create_kwargs)
            self.sandbox_id = sandbox.get_info().sandbox_id
            self.start_time = timezone.now()
            self.sandbox_state = self.SandboxState.READY
            self.save()

            self._start_agent_server(sandbox)
            logger.info(
                "[SANDBOX] Created sandbox %s (record pk=%s)",
                self.sandbox_id,
                self.pk,
            )

            return sandbox
        except Exception:
            logger.exception(
                "[SANDBOX] Failed to create sandbox (record pk=%s)", self.pk
            )
            self.sandbox_state = self.SandboxState.ERROR
            self.save(update_fields=["sandbox_state", "date_updated"])
            return None

    def _start_agent_server(self, sandbox: Sandbox) -> bool:
        """Launch the agent_server inside the sandbox and wait for readiness.

        Returns True if the server became healthy, False otherwise.
        """
        import time

        import httpx

        sandbox_id = self.sandbox_id or ""
        cmd = (
            "cd /opt/.midsphere && "
            f"SUKUNA_SANDBOX_ID='{sandbox_id}' "
            "uv run python -m agent_server "
            ">> /tmp/agent_server.log 2>&1"
        )
        logger.info("[SANDBOX] Starting agent_server in sandbox %s", self.sandbox_id)
        sandbox.commands.run(cmd, background=True, timeout=0)

        port: int = getattr(settings, "SANDBOX_AGENT_SERVER_PORT", 8000)
        health_url = f"https://{sandbox.get_host(port)}/health"
        max_attempts = 30
        for attempt in range(max_attempts):
            try:
                resp = httpx.get(health_url, timeout=3)
                if resp.status_code == 200:
                    logger.info(
                        "[SANDBOX] Agent server ready after %d attempt(s)", attempt + 1
                    )
                    return True
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                pass
            time.sleep(1)

        logger.warning(
            "[SANDBOX] Agent server did not become ready after %ds in sandbox %s",
            max_attempts,
            self.sandbox_id,
        )
        return False

    def get_sandbox(
        self, api_key: str | None = None, user: User | None = None
    ) -> Sandbox | None:
        """Connect to an existing E2B sandbox by its sandbox_id.

        Returns the E2B Sandbox object, or None on failure. When E2B reports
        the sandbox is gone (paused + garbage-collected, or never existed),
        ``self._last_connect_gone`` is set so callers can skip a redundant
        pause attempt.
        """
        self._last_connect_gone = False
        try:
            logger.info("[SANDBOX] Connecting to sandbox %s", self.sandbox_id)

            connect_kwargs: dict[str, Any] = {"timeout": 3600}
            if api_key:
                connect_kwargs["api_key"] = api_key

            return Sandbox.connect(self.sandbox_id, **connect_kwargs)
        except NotFoundException as exc:
            self._last_connect_gone = True
            logger.warning(
                "[SANDBOX] Sandbox %s is gone on E2B (%s)", self.sandbox_id, exc
            )
            return None
        except Exception:
            logger.exception(
                "[SANDBOX] Failed to connect to sandbox %s", self.sandbox_id
            )
            return None

    def upload_files(self, sandbox: Sandbox, files: list[StoredFile]) -> list[str]:
        """Upload StoredFile objects into the sandbox workspace.

        Returns list of sandbox file paths where files were uploaded.
        """
        sandbox_paths: list[str] = []
        for stored in files:
            file_path: str = stored.file.path
            sandbox_path = f"/home/user/workspace/{stored.file.name}"
            logger.info("[SANDBOX] Uploading %s to %s", file_path, sandbox_path)
            with open(file_path, "rb") as f:
                sandbox.files.write(sandbox_path, f)
                sandbox_paths.append(sandbox_path)

        return sandbox_paths

    def download_files(self, sandbox: Sandbox, file_paths: list[str]) -> list[str]:
        """Download files from the sandbox and create StoredFile records.

        Returns list of local file paths where files were saved.

        Raises:
            ValueError: If the conversation has been deleted.
        """
        if self.conversation is None:
            raise ValueError("Cannot download files: conversation was deleted")

        local_paths: list[str] = []

        for file_path in file_paths:
            content = sandbox.files.read(file_path)
            file_name = os.path.basename(file_path)
            local_dir = os.path.join(
                settings.MEDIA_ROOT, "downloads", str(self.conversation.id)
            )
            os.makedirs(local_dir, exist_ok=True)

            local_path = os.path.join(local_dir, file_name)

            mode = "wb" if isinstance(content, bytes) else "w"
            with open(local_path, mode) as file:
                file.write(content)
            local_paths.append(local_path)

        for path in local_paths:
            with open(path, "rb") as f:
                django_file = File(f)
                file_name = os.path.basename(path)
                StoredFile.objects.create(
                    owner=self.conversation.user,
                    file=django_file,
                    name=file_name,
                    size=os.path.getsize(path),
                    mime_type=self._get_mime_type(path),
                )

        return local_paths

    @staticmethod
    def _get_mime_type(file_path: str) -> str:
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type or "application/octet-stream"

    def update_end_time(self, time_stamp: Any) -> None:
        """Set the sandbox end time and record billing usage."""
        self.end_time = time_stamp
        self.save()
        self._record_billing_usage(
            int((self.end_time - self.start_time).total_seconds())
        )

    def _record_billing_usage(self, duration_seconds: int) -> None:
        """Record sandbox time billing usage for the conversation's user."""
        if self.conversation is None:
            return
        from apps.billing.models import UserSubscription

        try:
            subscription = UserSubscription.objects.select_related("plan").get(
                user=self.conversation.user
            )
            subscription.record_feature_usage(
                metric_name="sandbox_time",
                quantity=duration_seconds,
                metadata={},
            )
        except UserSubscription.DoesNotExist:
            logger.warning(
                "[BILLING] No subscription for user %s (sandbox %s)",
                self.conversation.user_id,
                self.sandbox_id,
            )
        except Exception:
            logger.exception(
                "[BILLING] Failed to record usage for sandbox %s", self.sandbox_id
            )
        # Shadow compute credit deduction
        try:
            from apps.billing.credit_service import CreditService

            run = self.conversation.current_task
            if run is not None:
                hold = CreditService.get_hold_for_run(run)
                if hold is not None:
                    credits = CreditService.calculate_compute_credits(duration_seconds)
                    if credits > 0:
                        CreditService.consume(
                            hold,
                            "compute",
                            credits,
                            source_type="e2b:sandbox",
                            description=f"Sandbox compute: {duration_seconds}s",
                        )
        except Exception:
            logger.warning(
                "[CREDITS] Shadow compute billing failed for sandbox %s",
                self.sandbox_id,
                exc_info=True,
            )

    def get_sse_link(
        self, sandbox: Sandbox, command: str, env: dict[str, str], port: int
    ) -> str:
        """Start an MCP proxy inside the sandbox and return its SSE URL."""
        env_string = " ".join([f'--env {k} "{v}"' for k, v in env.items()])
        proxy_command = f"mcp-proxy --host=0.0.0.0 --port {port} {env_string} {command}"
        sandbox.commands.run(proxy_command, background=True, timeout=0)
        return f"https://{sandbox.get_host(port)}/sse"

    def mark_done(self) -> None:
        """Mark the sandbox as terminated, record usage duration and billing."""
        if self.end_time is None:
            self.end_time = timezone.now()
        duration_seconds = int((self.end_time - self.start_time).total_seconds())
        self.sandbox_state = self.SandboxState.TERMINATED
        self.usage_in_seconds += duration_seconds
        self.save()
        self._record_billing_usage(duration_seconds)

    def schedule_idle_pause(self, minutes: int = 1) -> None:
        """Schedule sandbox for idle pause after the specified minutes."""
        self.delayed_termination_at = timezone.now() + timedelta(minutes=minutes)
        self.save(update_fields=["delayed_termination_at", "date_updated"])
        logger.info(
            "[SANDBOX] Scheduled idle pause for sandbox %s at %s",
            self.sandbox_id,
            self.delayed_termination_at,
        )

    def pause_sandbox(self) -> None:
        """Pause the sandbox via E2B API (preserves process state).

        Falls back to marking ERROR state if pause fails — never terminates.
        """
        try:
            if self.sandbox_id:
                # Use _cls_pause to pause by ID directly — avoids the need to
                # connect first, which can fail for unhealthy sandboxes.
                # _cls_pause returns a new sandbox_id for the paused snapshot.
                new_sandbox_id = Sandbox._cls_pause(self.sandbox_id)
                logger.info(
                    "[SANDBOX] Paused sandbox %s → new id %s",
                    self.sandbox_id,
                    new_sandbox_id,
                )
                self.sandbox_id = new_sandbox_id
            else:
                logger.warning(
                    "[SANDBOX] Cannot pause sandbox with no sandbox_id (pk=%s)", self.pk
                )
                return
        except NotFoundException as exc:
            logger.warning(
                "[SANDBOX] Pause target %s is already gone on E2B (%s); marking ERROR",
                self.sandbox_id,
                exc,
            )
            self.sandbox_state = self.SandboxState.ERROR
            self.delayed_termination_at = None
            self.save(
                update_fields=[
                    "sandbox_state",
                    "delayed_termination_at",
                    "date_updated",
                ]
            )
            return
        except Exception:
            logger.warning(
                "[SANDBOX] Error pausing sandbox %s, marking as ERROR",
                self.sandbox_id,
                exc_info=True,
            )
            self.sandbox_state = self.SandboxState.ERROR
            self.delayed_termination_at = None
            self.save(
                update_fields=[
                    "sandbox_state",
                    "delayed_termination_at",
                    "date_updated",
                ]
            )
            return
        self.sandbox_state = self.SandboxState.PAUSED
        self.delayed_termination_at = None
        self.save()

    def resume_sandbox(
        self, api_key: str | None = None, user: User | None = None
    ) -> Sandbox | None:
        """Resume a paused sandbox via E2B API.

        Verifies agent_server health after resume and restarts it if necessary.
        Falls back to creating a new sandbox if resume fails entirely.
        """
        self._last_connect_gone = False
        try:
            connect_kwargs: dict[str, Any] = {"timeout": 3600}
            if api_key:
                connect_kwargs["api_key"] = api_key

            sandbox = Sandbox.connect(self.sandbox_id, **connect_kwargs)
            self.sandbox_state = self.SandboxState.READY
            self.save()
            logger.info("[SANDBOX] Resumed sandbox %s", self.sandbox_id)

            import httpx

            port: int = getattr(settings, "SANDBOX_AGENT_SERVER_PORT", 8000)
            health_url = f"https://{sandbox.get_host(port)}/health"
            try:
                resp = httpx.get(health_url, timeout=5)
                if resp.status_code == 200:
                    logger.info("[SANDBOX] Agent server healthy after resume")
                    return sandbox
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                pass

            logger.warning(
                "[SANDBOX] Agent server not responding after resume of %s, restarting",
                self.sandbox_id,
            )
            self._start_agent_server(sandbox)
            return sandbox
        except NotFoundException as exc:
            self._last_connect_gone = True
            logger.warning(
                "[SANDBOX] Cannot resume sandbox %s: gone on E2B (%s); creating replacement",
                self.sandbox_id,
                exc,
            )
            self.sandbox_state = self.SandboxState.CREATING
            self.save(update_fields=["sandbox_state", "date_updated"])
            return self.create_sandbox(api_key=api_key, user=user)
        except Exception:
            logger.exception("[SANDBOX] Failed to resume sandbox %s", self.sandbox_id)
            # Try to pause the old sandbox before creating a new one.
            old_sandbox_id = self.sandbox_id
            if old_sandbox_id:
                try:
                    Sandbox._cls_pause(old_sandbox_id)
                    logger.info(
                        "[SANDBOX] Paused old sandbox %s before creating replacement",
                        old_sandbox_id,
                    )
                except NotFoundException:
                    logger.debug(
                        "[SANDBOX] Old sandbox %s already gone on E2B",
                        old_sandbox_id,
                    )
                except Exception:
                    logger.debug(
                        "[SANDBOX] Could not pause old sandbox %s (may already be paused/dead)",
                        old_sandbox_id,
                    )
            self.sandbox_state = self.SandboxState.CREATING
            self.save(update_fields=["sandbox_state", "date_updated"])
            return self.create_sandbox(api_key=api_key, user=user)

    def terminate_sandbox(self) -> None:
        """Pause the sandbox via E2B API instead of terminating.

        Despite the name (kept for call-site compatibility), this method pauses
        the sandbox so it can be resumed later.  Sandboxes are never killed.
        """
        try:
            if self.sandbox_id:
                new_sandbox_id = Sandbox._cls_pause(self.sandbox_id)
                logger.info(
                    "[SANDBOX] Paused (terminate path) sandbox %s → new id %s",
                    self.sandbox_id,
                    new_sandbox_id,
                )
                self.sandbox_id = new_sandbox_id
            else:
                logger.info("[SANDBOX] No sandbox_id to pause (pk=%s)", self.pk)
        except Exception:
            logger.warning(
                "[SANDBOX] Error pausing sandbox %s (terminate path)",
                self.sandbox_id,
                exc_info=True,
            )
        finally:
            self.end_time = timezone.now()
            self.mark_done()
            self.delayed_termination_at = None
            self.sandbox_state = self.SandboxState.PAUSED
            self.save()

    @classmethod
    def claim_from_pool(cls, conversation: Conversation) -> E2bSandbox | None:
        """Atomically claim a prewarmed pool sandbox for a conversation.

        Uses select_for_update(skip_locked=True) so concurrent claims get
        different sandboxes without blocking each other.  FIFO order ensures
        the oldest (closest to expiry) sandbox is used first.

        Returns the claimed E2bSandbox or None if the pool is empty.
        """
        with transaction.atomic():
            candidate = (
                cls.objects.select_for_update(skip_locked=True)
                .filter(conversation__isnull=True, sandbox_state=cls.SandboxState.READY)
                .exclude(sandbox_id__in=("", "local"))
                .order_by("start_time")
                .first()
            )
            if candidate is None:
                return None
            candidate.conversation = conversation
            candidate.delayed_termination_at = None
            candidate.save(
                update_fields=["conversation", "delayed_termination_at", "date_updated"]
            )
            logger.info(
                "[SANDBOX] Claimed pool sandbox %s for conversation %s",
                candidate.sandbox_id,
                conversation.id,
            )
            return candidate

    @classmethod
    def claim_from_pool_for_project(cls, project) -> E2bSandbox | None:
        """Atomically claim a prewarmed pool sandbox for a project.

        Links the sandbox to the project via Project.sandbox OneToOne.
        Returns the claimed E2bSandbox or None if the pool is empty.
        """
        with transaction.atomic():
            candidate = (
                cls.objects.select_for_update(skip_locked=True)
                .filter(conversation__isnull=True, sandbox_state=cls.SandboxState.READY)
                .exclude(sandbox_id__in=("", "local"))
                .order_by("start_time")
                .first()
            )
            if candidate is None:
                return None
            candidate.delayed_termination_at = None
            candidate.save(update_fields=["delayed_termination_at", "date_updated"])
            # Link to project via OneToOne
            project.sandbox = candidate
            project.save(update_fields=["sandbox"])
            logger.info(
                "[SANDBOX] Claimed pool sandbox %s for project %s",
                candidate.sandbox_id,
                project.id,
            )
            return candidate

    def __str__(self) -> str:
        return f"E2bSandbox {self.sandbox_id or self.pk} ({self.sandbox_state})"

    class Meta:
        """Meta options for E2bSandbox."""

        verbose_name = _("E2B Sandbox")
        verbose_name_plural = _("E2B Sandboxes")
