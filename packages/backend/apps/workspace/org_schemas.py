"""Request/response schemas for the Organization management API."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from ninja import Schema

# ── Request Schemas ─────────────────────────────────────────────────────────


class CreateOrganizationRequest(Schema):
    """Request body for creating a new organization."""

    name: str
    description: str = ""


class UpdateOrganizationRequest(Schema):
    """Request body for updating an organization (partial)."""

    name: Optional[str] = None
    description: Optional[str] = None


class InviteMemberRequest(Schema):
    """Request body for inviting a user to an organization."""

    email: str
    role: str = "member"  # viewer, member, admin


class ChangeMemberRoleRequest(Schema):
    """Request body for changing a member's role."""

    role: str  # viewer, member, admin, owner


# ── Response Schemas ────────────────────────────────────────────────────────


class OrganizationOut(Schema):
    """Organization detail in API responses."""

    id: UUID
    name: str
    slug: str
    description: str
    created_at: datetime
    updated_at: datetime
    member_count: int = 0
    your_role: Optional[str] = None


class OrganizationListOut(Schema):
    """Lightweight organization entry for list responses."""

    id: UUID
    name: str
    slug: str
    description: str
    member_count: int = 0
    your_role: Optional[str] = None


class MemberOut(Schema):
    """Organization member in API responses."""

    id: UUID
    user_id: int
    email: str
    name: str
    role: str
    joined_at: datetime


class ActionOut(Schema):
    """Generic success response."""

    success: bool
    message: str


class ErrorOut(Schema):
    """Generic error response."""

    detail: str


# ── Security Policy Schemas ────────────────────────────────────────────────


class UpdateSecurityPolicyRequest(Schema):
    """Request body for updating an organization's security policy."""

    mfa_required: Optional[bool] = None
    session_timeout_minutes: Optional[int] = None
    max_concurrent_sessions: Optional[int] = None


class SecurityPolicyOut(Schema):
    """Organization security policy in API responses."""

    mfa_required: bool
    session_timeout_minutes: Optional[int] = None
    max_concurrent_sessions: Optional[int] = None


# ── SSO Configuration Schemas ─────────────────────────────────────────────


class CreateSSOConfigRequest(Schema):
    """Request body for creating an SSO configuration."""

    provider_type: str = "saml"
    metadata_url: str = ""
    entity_id: str = ""
    certificate: str = ""
    is_active: bool = False
    enforce_sso: bool = False


class UpdateSSOConfigRequest(Schema):
    """Request body for updating an SSO configuration (partial)."""

    provider_type: Optional[str] = None
    metadata_url: Optional[str] = None
    entity_id: Optional[str] = None
    certificate: Optional[str] = None
    is_active: Optional[bool] = None
    enforce_sso: Optional[bool] = None
    emergency_bypass_enabled: Optional[bool] = None


class SSOConfigOut(Schema):
    """SSO configuration in API responses."""

    id: UUID
    organization_id: UUID
    provider_type: str
    metadata_url: str
    entity_id: str
    certificate: str
    is_active: bool
    enforce_sso: bool
    emergency_bypass_enabled: bool
    created_at: datetime
    updated_at: datetime


# ── SCIM Token Schemas ────────────────────────────────────────────────────


class CreateSCIMTokenRequest(Schema):
    """Request body for generating a new SCIM token."""

    name: str = ""
    allowed_cidrs: list[str] = []


class SCIMTokenOut(Schema):
    """SCIM token in API responses (never includes the full hash)."""

    id: UUID
    name: str
    prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime] = None
    last_used_ip: Optional[str] = None
    allowed_cidrs: list[str] = []


class SCIMTokenCreatedOut(Schema):
    """Response for token creation — includes the plaintext token once."""

    id: UUID
    name: str
    prefix: str
    token: str
    is_active: bool
    created_at: datetime
    allowed_cidrs: list[str] = []


# ── Org Lifecycle Schemas ────────────────────────────────────────────────


class DeleteOrganizationRequest(Schema):
    """Request body for deleting an organization with confirmation."""

    confirm_name: str
    cascade_mode: str  # "transfer" or "destroy"


class DeletionPreviewOut(Schema):
    """Preview of resources affected by org deletion."""

    organization_id: UUID
    organization_name: str
    projects: int = 0
    conversations: int = 0
    members: int = 0
    active_agent_runs: int = 0
    scim_tokens: int = 0
    has_sso_config: bool = False


class UpdateOrgSlugRequest(Schema):
    """Request body for changing an org's slug."""

    new_slug: str


# ── Invitation Schemas ──────────────────────────────────────────────────


class CreateInvitationRequest(Schema):
    """Request body for creating an email invitation."""

    email: str
    role: str = "member"


class CreateLinkInvitationRequest(Schema):
    """Request body for creating a shareable invitation link."""

    role: str = "member"
    expiry: str = "7d"  # 1d, 7d, 30d, never
    max_uses: Optional[int] = None  # None = unlimited


class InvitationOut(Schema):
    """Invitation in API responses."""

    id: UUID
    organization_id: UUID
    organization_name: str
    email: Optional[str] = None
    role: str
    token: UUID
    invited_by_email: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    use_count: int = 0
    is_active: bool = True


class InvitationInfoOut(Schema):
    """Public invitation info for the accept page."""

    organization_name: str
    organization_slug: str
    role: str
    invited_by_name: Optional[str] = None
    expires_at: Optional[datetime] = None


class InvitationAcceptOut(Schema):
    """Response after accepting an invitation."""

    success: bool
    message: str
    organization_id: UUID
    organization_name: str
    role: str


class OrgSlugChangeOut(Schema):
    """Response after an org slug change, showing old and new endpoint URLs."""

    old_slug: str
    new_slug: str
    old_scim_url: str
    new_scim_url: str
    old_saml_entity_id: str
    new_saml_entity_id: str


# ── Integration schemas ─────────────────────────────────────────────────────


class IntegrationOut(Schema):
    """Slack or Discord webhook integration."""

    webhook_url: str
    channel_name: str
    is_active: bool


class UpdateIntegrationRequest(Schema):
    """Create or update a webhook integration."""

    webhook_url: str
    channel_name: str = ""
    is_active: bool = True


class IntegrationTestOut(Schema):
    """Result of sending a test notification to a webhook."""

    ok: bool
    message: str


# ── IP Allowlist Schemas ──────────────────────────────────────────────────


class CreateIPAllowlistRequest(Schema):
    """Request body for adding an IP allowlist entry."""

    cidr_range: str
    description: str = ""
    is_active: bool = True


class IPAllowlistEntryOut(Schema):
    """IP allowlist entry in API responses."""

    id: UUID
    organization_id: UUID
    cidr_range: str
    description: str
    is_active: bool
    created_at: datetime


class IPAllowlistListOut(Schema):
    """IP allowlist for an org, including the requester's current IP."""

    entries: list[IPAllowlistEntryOut]
    your_ip: Optional[str] = None


# ── Conditional Access Policy Schemas ─────────────────────────────────────


class ConditionEntry(Schema):
    """A single condition in a conditional access policy."""

    type: str  # ip_range, time_of_day, day_of_week, user_agent_pattern
    cidr: Optional[str] = None
    start_hour: Optional[int] = None
    end_hour: Optional[int] = None
    timezone: Optional[str] = None
    days: Optional[list[int]] = None
    pattern: Optional[str] = None


class CreateAccessPolicyRequest(Schema):
    """Request body for creating a conditional access policy."""

    name: str
    conditions: list[ConditionEntry]
    action: str = "block"  # allow, block, require_mfa
    is_active: bool = True
    priority: int = 0


class UpdateAccessPolicyRequest(Schema):
    """Request body for updating a conditional access policy (partial)."""

    name: Optional[str] = None
    conditions: Optional[list[ConditionEntry]] = None
    action: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None


class AccessPolicyOut(Schema):
    """Conditional access policy in API responses."""

    id: UUID
    organization_id: UUID
    name: str
    conditions: list[dict]
    action: str
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime


class AccessPolicyListOut(Schema):
    """List of conditional access policies for an org."""

    policies: list[AccessPolicyOut]
    your_ip: Optional[str] = None


# ── Analytics Schemas ────────────────────────────────────────────────────


class UpdateCostPolicyRequest(Schema):
    """Request body for updating an org's cost policy."""

    member_monthly_credit_limit: Optional[int] = None
    alert_threshold_percent: Optional[int] = None


class CostPolicyOut(Schema):
    """Org cost policy in API responses."""

    member_monthly_credit_limit: Optional[int] = None
    alert_threshold_percent: int = 80


class MemberCostStatusEntry(Schema):
    """Per-member cost status for current month."""

    user_id: int
    email: str
    name: str
    credits_consumed: int
    limit: Optional[int] = None
    percent_used: Optional[float] = None


class ProjectCostStatusEntry(Schema):
    """Per-project cost status for current month."""

    project_id: UUID
    title: str
    current_month_usage: int
    monthly_credit_limit: Optional[int] = None
    percent_used: Optional[float] = None


class CostStatusOut(Schema):
    """Org cost status: per-member and per-project spending for current month."""

    member_monthly_credit_limit: Optional[int] = None
    alert_threshold_percent: int = 80
    members: list[MemberCostStatusEntry]
    projects: list[ProjectCostStatusEntry]


# ── Model Policy Schemas ────────────────────────────────────────────────


class UpdateModelPolicyRequest(Schema):
    """Request body for updating an org's model policy."""

    allowed_models: Optional[list[str]] = None
    allowed_providers: Optional[list[str]] = None
    block_byom: Optional[bool] = None


class ModelPolicyOut(Schema):
    """Org model policy in API responses."""

    allowed_models: list[str] = []
    allowed_providers: list[str] = []
    block_byom: bool = False


class UpdateAgentPolicyRequest(Schema):
    """Request body for updating an org's agent policy."""

    blocked_tools: Optional[list[str]] = None
    blocked_tool_groups: Optional[list[str]] = None
    require_hitl_for: Optional[list[str]] = None


class AgentPolicyOut(Schema):
    """Org agent policy in API responses."""

    blocked_tools: list[str] = []
    blocked_tool_groups: list[str] = []
    require_hitl_for: list[str] = []


# ── Org API Key Schemas ──────────────────────────────────────────────────


class CreateOrgAPIKeyRequest(Schema):
    """Request body for creating an org-level API key."""

    name: str = ""
    scopes: list[str] = []
    rate_limit_per_minute: int = 120
    billing_user_id: Optional[int] = None


class OrgAPIKeyOut(Schema):
    """Org API key in API responses (never includes the full key)."""

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str] = []
    is_active: bool
    rate_limit_per_minute: int = 120
    created_by_email: Optional[str] = None
    billing_user_email: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None


class OrgAPIKeyCreatedOut(Schema):
    """Response for key creation — includes the plaintext key once."""

    id: UUID
    name: str
    key_prefix: str
    key: str
    scopes: list[str] = []
    is_active: bool
    rate_limit_per_minute: int = 120
    created_at: datetime


class AnalyticsSummaryOut(Schema):
    """Org usage analytics summary."""

    total_agent_runs: int
    total_credits_consumed: int
    active_members: int
    total_conversations: int
    period_start: datetime
    period_end: datetime


class MemberAnalyticsEntry(Schema):
    """Per-member analytics row."""

    user_id: Optional[int] = None
    email: str
    name: str
    agent_runs_count: int
    credits_consumed: int
    conversations_count: int
    last_active: Optional[datetime] = None


class MemberAnalyticsOut(Schema):
    """Paginated per-member analytics."""

    page: int
    page_size: int
    total: int
    total_pages: int
    results: list[MemberAnalyticsEntry]


class ProjectAnalyticsEntry(Schema):
    """Per-project analytics row."""

    project_id: UUID
    title: str
    agent_runs: int
    credits_consumed: int
    unique_users: int
    last_activity: Optional[datetime] = None
    note: str = ""


class ProjectAnalyticsOut(Schema):
    """Paginated per-project analytics."""

    page: int
    page_size: int
    total: int
    total_pages: int
    results: list[ProjectAnalyticsEntry]


# ── DLP Policy Schemas ──────────────────────────────────────────────────


class DLPPatternEntry(Schema):
    """A single DLP scan pattern."""

    name: str
    regex: str
    action: str  # "block" or "redact"


class DLPPolicyOut(Schema):
    """Org DLP policy in API responses."""

    scan_patterns: list[DLPPatternEntry] = []
    is_active: bool = True


class UpdateDLPPolicyRequest(Schema):
    """Request body for updating an org's DLP policy."""

    scan_patterns: Optional[list[DLPPatternEntry]] = None
    is_active: Optional[bool] = None


class DLPTestRequest(Schema):
    """Request body for testing DLP patterns against sample text."""

    text: str


class DLPTestMatchEntry(Schema):
    """A single DLP test match result."""

    pattern_name: str
    action: str
    matched: bool


class DLPTestOut(Schema):
    """Result of testing DLP patterns against sample text."""

    matches: list[DLPTestMatchEntry]
    redacted_text: str
    would_block: bool
    block_pattern: Optional[str] = None


# ── Webhook Schemas ──────────────────────────────────────────────────


class CreateWebhookRequest(Schema):
    """Request body for creating an outbound webhook."""

    url: str
    secret: str
    events: list[str]
    destination_type: str = "generic"


class UpdateWebhookRequest(Schema):
    """Request body for updating an outbound webhook (partial)."""

    url: Optional[str] = None
    secret: Optional[str] = None
    events: Optional[list[str]] = None
    destination_type: Optional[str] = None
    is_active: Optional[bool] = None


class WebhookOut(Schema):
    """Outbound webhook in API responses."""

    id: UUID
    organization_id: UUID
    url: str
    events: list[str] = []
    destination_type: str = "generic"
    is_active: bool = True
    failure_count: int = 0
    created_at: datetime
    updated_at: datetime


class WebhookDeliveryLogOut(Schema):
    """Webhook delivery log entry in API responses."""

    id: UUID
    event_type: str
    status_code: Optional[int] = None
    response_time_ms: Optional[int] = None
    success: bool
    error_message: str = ""
    created_at: datetime
