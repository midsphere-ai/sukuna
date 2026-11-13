import { api } from './client';

// ── Types ───────────────────────────────────────────────────────────────────

export interface Organization {
	id: string;
	name: string;
	slug: string;
	description: string;
	created_at: string;
	updated_at: string;
	member_count: number;
	your_role: string;
}

export interface OrgMember {
	id: string;
	user_id: number;
	email: string;
	name: string;
	role: string;
	joined_at: string;
}

export interface SSOConfig {
	id: string;
	organization_id: string;
	provider_type: string;
	metadata_url: string;
	entity_id: string;
	certificate: string;
	is_active: boolean;
	enforce_sso: boolean;
	emergency_bypass_enabled: boolean;
	created_at: string;
	updated_at: string;
}

export interface SSOConfigCreate {
	provider_type: string;
	metadata_url: string;
	entity_id: string;
	certificate: string;
	is_active: boolean;
	enforce_sso: boolean;
	emergency_bypass_enabled?: boolean;
}

export interface SSOConfigUpdate {
	provider_type?: string;
	metadata_url?: string;
	entity_id?: string;
	certificate?: string;
	is_active?: boolean;
	enforce_sso?: boolean;
	emergency_bypass_enabled?: boolean;
}

export interface SPMetadata {
	entity_id: string;
	acs_url: string;
	slo_url: string;
	name_id_format: string;
	org_slug: string;
}

export interface ActiveOrg {
	organization_id: string | null;
	organization_name: string | null;
	organization_slug: string | null;
	your_role: string | null;
}

// ── API calls ───────────────────────────────────────────────────────────────

const BASE = '/workspace/organizations';

export function listOrganizations(): Promise<Organization[]> {
	return api.get<Organization[]>(`${BASE}/`);
}

export function createOrganization(data: {
	name: string;
	description?: string;
}): Promise<Organization> {
	return api.post<Organization>(`${BASE}/`, {
		name: data.name,
		description: data.description ?? ''
	});
}

export function getOrganization(orgId: string): Promise<Organization> {
	return api.get<Organization>(`${BASE}/${orgId}`);
}

export function listMembers(orgId: string): Promise<OrgMember[]> {
	return api.get<OrgMember[]>(`${BASE}/${orgId}/members`);
}

export function changeMemberRole(
	orgId: string,
	membershipId: string,
	data: { role: string }
): Promise<OrgMember> {
	return api.patch<OrgMember>(`${BASE}/${orgId}/members/${membershipId}`, data);
}

export function removeMember(
	orgId: string,
	membershipId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(
		`${BASE}/${orgId}/members/${membershipId}`
	);
}

export function leaveOrganization(orgId: string): Promise<{ success: boolean; message: string }> {
	return api.post<{ success: boolean; message: string }>(`${BASE}/${orgId}/leave`);
}

// SSO

export function getSSOConfig(orgId: string): Promise<SSOConfig> {
	return api.get<SSOConfig>(`${BASE}/${orgId}/sso`, { skipErrorHandling: true });
}

export function createSSOConfig(orgId: string, data: SSOConfigCreate): Promise<SSOConfig> {
	return api.post<SSOConfig>(`${BASE}/${orgId}/sso`, data);
}

export function updateSSOConfig(orgId: string, data: SSOConfigUpdate): Promise<SSOConfig> {
	return api.patch<SSOConfig>(`${BASE}/${orgId}/sso`, data);
}

export function deleteSSOConfig(orgId: string): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(`${BASE}/${orgId}/sso`);
}

export function getSPMetadata(orgId: string): Promise<SPMetadata> {
	return api.get<SPMetadata>(`${BASE}/${orgId}/sso/metadata`, { skipErrorHandling: true });
}

// ── Invitations ──────────────────────────────────────────────────────────

export interface Invitation {
	id: string;
	organization_id: string;
	organization_name: string;
	email: string | null;
	role: string;
	token: string;
	invited_by_email: string | null;
	created_at: string;
	expires_at: string | null;
	max_uses: number | null;
	use_count: number;
	is_active: boolean;
}

export interface InvitationInfo {
	organization_name: string;
	organization_slug: string;
	role: string;
	invited_by_name: string | null;
	expires_at: string | null;
}

export interface InvitationAcceptResult {
	success: boolean;
	message: string;
	organization_id: string;
	organization_name: string;
	role: string;
}

export function listInvitations(orgId: string): Promise<Invitation[]> {
	return api.get<Invitation[]>(`${BASE}/${orgId}/invitations`);
}

export function createInvitation(
	orgId: string,
	data: { email: string; role: string }
): Promise<Invitation> {
	return api.post<Invitation>(`${BASE}/${orgId}/invitations`, data);
}

export function createLinkInvitation(
	orgId: string,
	data: { role: string; expiry: string; max_uses: number | null }
): Promise<Invitation> {
	return api.post<Invitation>(`${BASE}/${orgId}/invitation-links`, data);
}

export function getInvitationInfo(token: string): Promise<InvitationInfo> {
	return api.get<InvitationInfo>(`/workspace/invitations/${token}`, {
		skipAuth: true,
		skipErrorHandling: true
	});
}

export function acceptInvitation(token: string): Promise<InvitationAcceptResult> {
	return api.post<InvitationAcceptResult>(`/workspace/invitations/${token}/accept`, {});
}

export function revokeInvitation(
	invitationId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(
		`/workspace/invitations/${invitationId}/revoke`
	);
}

// ── Webhook Integrations ─────────────────────────────────────────────────

export interface WebhookIntegration {
	webhook_url: string;
	channel_name: string;
	is_active: boolean;
}

export interface IntegrationTestResult {
	ok: boolean;
	message: string;
}

export function getSlackIntegration(orgId: string): Promise<WebhookIntegration> {
	return api.get<WebhookIntegration>(`${BASE}/${orgId}/integrations/slack`, {
		skipErrorHandling: true
	});
}

export function upsertSlackIntegration(
	orgId: string,
	data: WebhookIntegration
): Promise<WebhookIntegration> {
	return api.put<WebhookIntegration>(`${BASE}/${orgId}/integrations/slack`, data);
}

export function deleteSlackIntegration(orgId: string): Promise<{ detail: string }> {
	return api.delete<{ detail: string }>(`${BASE}/${orgId}/integrations/slack`);
}

export function testSlackIntegration(orgId: string): Promise<IntegrationTestResult> {
	return api.post<IntegrationTestResult>(`${BASE}/${orgId}/integrations/slack/test`);
}

export function getDiscordIntegration(orgId: string): Promise<WebhookIntegration> {
	return api.get<WebhookIntegration>(`${BASE}/${orgId}/integrations/discord`, {
		skipErrorHandling: true
	});
}

export function upsertDiscordIntegration(
	orgId: string,
	data: WebhookIntegration
): Promise<WebhookIntegration> {
	return api.put<WebhookIntegration>(`${BASE}/${orgId}/integrations/discord`, data);
}

export function deleteDiscordIntegration(orgId: string): Promise<{ detail: string }> {
	return api.delete<{ detail: string }>(`${BASE}/${orgId}/integrations/discord`);
}

export function testDiscordIntegration(orgId: string): Promise<IntegrationTestResult> {
	return api.post<IntegrationTestResult>(`${BASE}/${orgId}/integrations/discord/test`);
}

// ── IP Allowlist ────────────────────────────────────────────────────────

export interface IPAllowlistEntry {
	id: string;
	organization_id: string;
	cidr_range: string;
	description: string;
	is_active: boolean;
	created_at: string;
}

export interface IPAllowlistList {
	entries: IPAllowlistEntry[];
	your_ip: string | null;
}

export function getIPAllowlist(orgId: string): Promise<IPAllowlistList> {
	return api.get<IPAllowlistList>(`${BASE}/${orgId}/ip-allowlist`, { skipErrorHandling: true });
}

export function addIPAllowlistEntry(
	orgId: string,
	data: { cidr_range: string; description?: string; is_active?: boolean }
): Promise<IPAllowlistEntry> {
	return api.post<IPAllowlistEntry>(`${BASE}/${orgId}/ip-allowlist`, data);
}

export function removeIPAllowlistEntry(
	orgId: string,
	entryId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(
		`${BASE}/${orgId}/ip-allowlist/${entryId}`
	);
}

// ── Conditional Access Policies ──────────────────────────────────────────

export interface AccessPolicyCondition {
	type: string; // ip_range, time_of_day, day_of_week, user_agent_pattern
	cidr?: string;
	start_hour?: number;
	end_hour?: number;
	timezone?: string;
	days?: number[];
	pattern?: string;
}

export interface AccessPolicy {
	id: string;
	organization_id: string;
	name: string;
	conditions: AccessPolicyCondition[];
	action: string; // allow, block, require_mfa
	is_active: boolean;
	priority: number;
	created_at: string;
	updated_at: string;
}

export interface AccessPolicyList {
	policies: AccessPolicy[];
	your_ip: string | null;
}

export interface AccessPolicyCreate {
	name: string;
	conditions: AccessPolicyCondition[];
	action: string;
	is_active?: boolean;
	priority?: number;
}

export interface AccessPolicyUpdate {
	name?: string;
	conditions?: AccessPolicyCondition[];
	action?: string;
	is_active?: boolean;
	priority?: number;
}

export function getAccessPolicies(orgId: string): Promise<AccessPolicyList> {
	return api.get<AccessPolicyList>(`${BASE}/${orgId}/access-policies`, { skipErrorHandling: true });
}

export function createAccessPolicy(orgId: string, data: AccessPolicyCreate): Promise<AccessPolicy> {
	return api.post<AccessPolicy>(`${BASE}/${orgId}/access-policies`, data);
}

export function updateAccessPolicy(
	orgId: string,
	policyId: string,
	data: AccessPolicyUpdate
): Promise<AccessPolicy> {
	return api.patch<AccessPolicy>(`${BASE}/${orgId}/access-policies/${policyId}`, data);
}

export function deleteAccessPolicy(
	orgId: string,
	policyId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(
		`${BASE}/${orgId}/access-policies/${policyId}`
	);
}

// ── Project Templates ────────────────────────────────────────────────────

export interface TemplateFile {
	id?: string;
	file_name: string;
	file_content: string;
	sort_order: number;
}

export interface ProjectTemplate {
	id: string;
	name: string;
	description: string;
	custom_instructions: string;
	icon: string;
	created_by_id: string | null;
	created_at: string;
	updated_at: string;
	files: TemplateFile[];
}

export interface CreateTemplateRequest {
	name: string;
	description?: string;
	custom_instructions?: string;
	icon?: string;
	files?: TemplateFile[];
}

export interface UpdateTemplateRequest {
	name?: string;
	description?: string;
	custom_instructions?: string;
	icon?: string;
	files?: TemplateFile[];
}

const TMPL_BASE = '/workspace/organizations/templates';

export function listTemplates(orgId: string): Promise<ProjectTemplate[]> {
	return api.get<ProjectTemplate[]>(`${TMPL_BASE}/${orgId}`);
}

export function getTemplate(orgId: string, templateId: string): Promise<ProjectTemplate> {
	return api.get<ProjectTemplate>(`${TMPL_BASE}/${orgId}/${templateId}`);
}

export function createTemplate(
	orgId: string,
	data: CreateTemplateRequest
): Promise<ProjectTemplate> {
	return api.post<ProjectTemplate>(`${TMPL_BASE}/${orgId}`, data);
}

export function updateTemplate(
	orgId: string,
	templateId: string,
	data: UpdateTemplateRequest
): Promise<ProjectTemplate> {
	return api.patch<ProjectTemplate>(`${TMPL_BASE}/${orgId}/${templateId}`, data);
}

export function deleteTemplate(
	orgId: string,
	templateId: string
): Promise<{ id: string; deleted: boolean }> {
	return api.delete<{ id: string; deleted: boolean }>(`${TMPL_BASE}/${orgId}/${templateId}`);
}

export function createTemplateFromProject(
	orgId: string,
	projectId: string
): Promise<ProjectTemplate> {
	return api.post<ProjectTemplate>(`${TMPL_BASE}/${orgId}/from-project/${projectId}`, {});
}

// ── Analytics ────────────────────────────────────────────────────────────

export interface AnalyticsSummary {
	total_agent_runs: number;
	total_credits_consumed: number;
	active_members: number;
	total_conversations: number;
	period_start: string;
	period_end: string;
}

export interface MemberAnalyticsEntry {
	user_id: number | null;
	email: string;
	name: string;
	agent_runs_count: number;
	credits_consumed: number;
	conversations_count: number;
	last_active: string | null;
}

export interface MemberAnalyticsPage {
	page: number;
	page_size: number;
	total: number;
	total_pages: number;
	results: MemberAnalyticsEntry[];
}

export interface ProjectAnalyticsEntry {
	project_id: string;
	title: string;
	agent_runs: number;
	credits_consumed: number;
	unique_users: number;
	last_activity: string | null;
	note: string;
}

export interface ProjectAnalyticsPage {
	page: number;
	page_size: number;
	total: number;
	total_pages: number;
	results: ProjectAnalyticsEntry[];
}

export interface AnalyticsParams {
	period?: string;
	start_date?: string;
	end_date?: string;
	page?: number;
	page_size?: number;
	sort_by?: string;
	sort_order?: string;
	format?: string;
}

function _buildQuery(params: AnalyticsParams): string {
	const entries = Object.entries(params).filter(([, v]) => v != null);
	if (!entries.length) return '';
	return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&');
}

export function getAnalyticsSummary(
	orgId: string,
	params: AnalyticsParams = {}
): Promise<AnalyticsSummary> {
	return api.get<AnalyticsSummary>(`${BASE}/${orgId}/analytics/summary${_buildQuery(params)}`);
}

export function getAnalyticsMembers(
	orgId: string,
	params: AnalyticsParams = {}
): Promise<MemberAnalyticsPage> {
	return api.get<MemberAnalyticsPage>(`${BASE}/${orgId}/analytics/members${_buildQuery(params)}`);
}

export function getAnalyticsProjects(
	orgId: string,
	params: AnalyticsParams = {}
): Promise<ProjectAnalyticsPage> {
	return api.get<ProjectAnalyticsPage>(`${BASE}/${orgId}/analytics/projects${_buildQuery(params)}`);
}

export function exportAnalyticsMembersUrl(orgId: string, params: AnalyticsParams = {}): string {
	return `/api/v1${BASE}/${orgId}/analytics/members${_buildQuery({ ...params, format: 'csv' })}`;
}

export function exportAnalyticsProjectsUrl(orgId: string, params: AnalyticsParams = {}): string {
	return `/api/v1${BASE}/${orgId}/analytics/projects${_buildQuery({ ...params, format: 'csv' })}`;
}

// ── Model Policy ────────────────────────────────────────────────────────

export interface ModelPolicy {
	allowed_models: string[];
	allowed_providers: string[];
	block_byom: boolean;
}

export interface ModelPolicyUpdate {
	allowed_models?: string[];
	allowed_providers?: string[];
	block_byom?: boolean;
}

export function getModelPolicy(orgId: string): Promise<ModelPolicy> {
	return api.get<ModelPolicy>(`${BASE}/${orgId}/model-policy`, { skipErrorHandling: true });
}

export function updateModelPolicy(orgId: string, data: ModelPolicyUpdate): Promise<ModelPolicy> {
	return api.patch<ModelPolicy>(`${BASE}/${orgId}/model-policy`, data);
}

// ── Agent Policy ────────────────────────────────────────────────────────

export interface AgentPolicy {
	blocked_tools: string[];
	blocked_tool_groups: string[];
	require_hitl_for: string[];
}

export interface AgentPolicyUpdate {
	blocked_tools?: string[];
	blocked_tool_groups?: string[];
	require_hitl_for?: string[];
}

export function getAgentPolicy(orgId: string): Promise<AgentPolicy> {
	return api.get<AgentPolicy>(`${BASE}/${orgId}/agent-policy`, { skipErrorHandling: true });
}

export function updateAgentPolicy(orgId: string, data: AgentPolicyUpdate): Promise<AgentPolicy> {
	return api.patch<AgentPolicy>(`${BASE}/${orgId}/agent-policy`, data);
}

// ── Org Context Switching ─────────────────────────────────────────────────

export function switchOrg(organizationId: string | null): Promise<ActiveOrg> {
	return api.post<ActiveOrg>('/workspace/switch-org', { organization_id: organizationId });
}

export function getActiveOrg(): Promise<ActiveOrg> {
	return api.get<ActiveOrg>('/workspace/active-org');
}

// ── SCIM Tokens ─────────────────────────────────────────────────────────────

export interface ScimToken {
	id: string;
	token_prefix: string;
	name: string;
	is_active: boolean;
	expires_at: string | null;
	created_at: string;
	last_used_at: string | null;
}

export interface ScimTokenCreateResult extends ScimToken {
	token: string; // plaintext, shown once
}

export function listScimTokens(orgId: string): Promise<ScimToken[]> {
	return api.get<ScimToken[]>(`${BASE}/${orgId}/scim-tokens`);
}

export function createScimToken(
	orgId: string,
	data: { name: string; expires_in_days?: number }
): Promise<ScimTokenCreateResult> {
	return api.post<ScimTokenCreateResult>(`${BASE}/${orgId}/scim-tokens`, data);
}

export function deleteScimToken(
	orgId: string,
	tokenId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(
		`${BASE}/${orgId}/scim-tokens/${tokenId}`
	);
}

// ── DLP Policy ──────────────────────────────────────────────────────────────

export interface DlpPattern {
	pattern: string;
	type: string;
	action: string; // 'block' | 'redact'
}

export interface DlpPolicy {
	scan_patterns: DlpPattern[];
	is_active: boolean;
}

export interface DlpTestResult {
	matches: boolean;
	matched_patterns: string[];
}

export function getDlpPolicy(orgId: string): Promise<DlpPolicy> {
	return api.get<DlpPolicy>(`${BASE}/${orgId}/dlp-policy`, { skipErrorHandling: true });
}

export function updateDlpPolicy(orgId: string, data: Partial<DlpPolicy>): Promise<DlpPolicy> {
	return api.patch<DlpPolicy>(`${BASE}/${orgId}/dlp-policy`, data);
}

export function testDlpPolicy(orgId: string, data: { text: string }): Promise<DlpTestResult> {
	return api.post<DlpTestResult>(`${BASE}/${orgId}/dlp-policy/test`, data);
}

// ── Outbound Webhooks ───────────────────────────────────────────────────────

export interface OrgWebhook {
	id: string;
	organization_id: string;
	url: string;
	events: string[];
	destination_type: string;
	is_active: boolean;
	failure_count: number;
	created_at: string;
	updated_at: string;
}

export interface OrgWebhookCreate {
	url: string;
	secret: string;
	events: string[];
	destination_type?: string;
}

export interface OrgWebhookUpdate {
	url?: string;
	secret?: string;
	events?: string[];
	destination_type?: string;
	is_active?: boolean;
}

export interface WebhookDelivery {
	id: string;
	event_type: string;
	status_code: number | null;
	response_time_ms: number | null;
	success: boolean;
	error_message: string;
	created_at: string;
}

export function listWebhooks(orgId: string): Promise<OrgWebhook[]> {
	return api.get<OrgWebhook[]>(`${BASE}/${orgId}/webhooks`);
}

export function createWebhook(orgId: string, data: OrgWebhookCreate): Promise<OrgWebhook> {
	return api.post<OrgWebhook>(`${BASE}/${orgId}/webhooks`, data);
}

export function getWebhook(orgId: string, webhookId: string): Promise<OrgWebhook> {
	return api.get<OrgWebhook>(`${BASE}/${orgId}/webhooks/${webhookId}`);
}

export function updateWebhook(
	orgId: string,
	webhookId: string,
	data: OrgWebhookUpdate
): Promise<OrgWebhook> {
	return api.patch<OrgWebhook>(`${BASE}/${orgId}/webhooks/${webhookId}`, data);
}

export function deleteWebhook(
	orgId: string,
	webhookId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(
		`${BASE}/${orgId}/webhooks/${webhookId}`
	);
}

export function testWebhook(
	orgId: string,
	webhookId: string
): Promise<{ success: boolean; message: string }> {
	return api.post<{ success: boolean; message: string }>(
		`${BASE}/${orgId}/webhooks/${webhookId}/test`
	);
}

export function listWebhookDeliveries(
	orgId: string,
	webhookId: string
): Promise<WebhookDelivery[]> {
	return api.get<WebhookDelivery[]>(`${BASE}/${orgId}/webhooks/${webhookId}/deliveries`);
}

// ── Org API Keys ────────────────────────────────────────────────────────────

export interface OrgApiKey {
	id: string;
	name: string;
	key_prefix: string;
	scopes: string[];
	is_active: boolean;
	rate_limit_per_minute: number;
	created_by_email: string;
	billing_user_email: string | null;
	created_at: string;
	last_used_at: string | null;
}

export interface OrgApiKeyCreateResult extends OrgApiKey {
	key: string; // plaintext, shown once
}

export function listOrgApiKeys(orgId: string): Promise<OrgApiKey[]> {
	return api.get<OrgApiKey[]>(`${BASE}/${orgId}/api-keys`);
}

export function createOrgApiKey(
	orgId: string,
	data: { name: string; scopes: string[]; billing_user_id?: string; rate_limit_per_minute?: number }
): Promise<OrgApiKeyCreateResult> {
	return api.post<OrgApiKeyCreateResult>(`${BASE}/${orgId}/api-keys`, data);
}

export function deleteOrgApiKey(
	orgId: string,
	keyId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(`${BASE}/${orgId}/api-keys/${keyId}`);
}

// ── Cost Policy ─────────────────────────────────────────────────────────────

export interface CostPolicy {
	member_monthly_credit_limit: number | null;
	alert_threshold_percent: number;
}

export interface CostMember {
	user_id: number;
	email: string;
	name: string;
	spent_this_month: number;
	monthly_limit: number | null;
}

export interface CostProject {
	project_id: string;
	name: string;
	spent_this_month: number;
}

export interface CostStatus {
	current_cycle_start: string;
	current_cycle_end: string;
	members: CostMember[];
	projects: CostProject[];
}

export function updateCostPolicy(orgId: string, data: Partial<CostPolicy>): Promise<CostPolicy> {
	return api.patch<CostPolicy>(`${BASE}/${orgId}/cost-policy`, data);
}

export function getCostStatus(orgId: string): Promise<CostStatus> {
	return api.get<CostStatus>(`${BASE}/${orgId}/cost-status`);
}

// ── Security Policy ─────────────────────────────────────────────────────────

export interface SecurityPolicy {
	mfa_required: boolean;
	session_timeout_minutes: number | null;
	max_concurrent_sessions: number | null;
}

export function getSecurityPolicy(orgId: string): Promise<SecurityPolicy> {
	return api.get<SecurityPolicy>(`${BASE}/${orgId}/security-policy`, { skipErrorHandling: true });
}

export function updateSecurityPolicy(
	orgId: string,
	data: Partial<SecurityPolicy>
): Promise<SecurityPolicy> {
	return api.patch<SecurityPolicy>(`${BASE}/${orgId}/security-policy`, data);
}

// ── Force Logout ────────────────────────────────────────────────────────────

export function forceLogout(
	orgId: string,
	data?: { user_id?: number }
): Promise<{ success: boolean; message: string }> {
	return api.post<{ success: boolean; message: string }>(
		`${BASE}/${orgId}/force-logout`,
		data ?? {}
	);
}

// ── Org Lifecycle ───────────────────────────────────────────────────────────

export interface DeletionPreview {
	organization_name: string;
	member_count: number;
	conversation_count: number;
	project_count: number;
	will_delete: string[];
	warning: string;
}

export interface SlugChangeResult {
	old_endpoint_url: string;
	new_endpoint_url: string;
}

export function freezeOrg(orgId: string): Promise<{ success: boolean; message: string }> {
	return api.post<{ success: boolean; message: string }>(`${BASE}/${orgId}/freeze`);
}

export function unfreezeOrg(orgId: string): Promise<{ success: boolean; message: string }> {
	return api.post<{ success: boolean; message: string }>(`${BASE}/${orgId}/unfreeze`);
}

export function getDeletionPreview(orgId: string): Promise<DeletionPreview> {
	return api.get<DeletionPreview>(`${BASE}/${orgId}/deletion-preview`);
}

export function deleteOrg(
	orgId: string,
	data: { confirm_name: string }
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(`${BASE}/${orgId}`, data);
}

export function updateOrgSlug(
	orgId: string,
	data: { new_slug: string }
): Promise<SlugChangeResult> {
	return api.patch<SlugChangeResult>(`${BASE}/${orgId}/slug`, data);
}
