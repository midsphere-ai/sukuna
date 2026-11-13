import { api } from './client';

// ── Types ───────────────────────────────────────────────────────────────────

export interface DashboardSummary {
	total_audit_entries: number;
	active_retention_policies: number;
	consent_coverage_percentage: number;
	total_users: number;
	mfa_enabled_count: number;
	mfa_enabled_percentage: number;
}

export interface AuditLogEntry {
	id: string;
	timestamp: string;
	actor_email: string;
	actor_ip: string;
	action: string;
	resource_type: string;
	resource_id: string;
	request_id: string;
	changes: unknown;
	metadata: unknown;
}

export interface AuditLogPage {
	page: number;
	page_size: number;
	total: number;
	total_pages: number;
	results: AuditLogEntry[];
}

export interface AuditLogFilters {
	page?: number;
	page_size?: number;
	actor_email?: string;
	action?: string;
	resource_type?: string;
	date_from?: string;
	date_to?: string;
	q?: string;
}

export interface RetentionStatus {
	id: string;
	resource_type: string;
	retention_days: number;
	action: string;
	is_active: boolean;
	last_run_at: string | null;
	records_affected_last_run: number;
	next_scheduled_run: string | null;
}

export interface ConsentTypeInfo {
	label: string;
	granted_count: number;
	revoked_count: number;
	coverage_percentage: number;
}

export interface ConsentOverview {
	total_users: number;
	consent_types: Record<string, ConsentTypeInfo>;
}

export interface MFAOrgInfo {
	id: string;
	name: string;
	slug: string;
	mfa_required: boolean;
	member_count: number;
}

export interface MFAStatus {
	total_users: number;
	mfa_enabled_count: number;
	mfa_enabled_percentage: number;
	organizations: MFAOrgInfo[];
}

// ── API calls ───────────────────────────────────────────────────────────────

const BASE = '/compliance';

export function getDashboardSummary(): Promise<DashboardSummary> {
	return api.get<DashboardSummary>(`${BASE}/dashboard/summary`, { skipErrorHandling: true });
}

export function getAuditLog(filters: AuditLogFilters = {}): Promise<AuditLogPage> {
	const params = new URLSearchParams();
	if (filters.page) params.set('page', String(filters.page));
	if (filters.page_size) params.set('page_size', String(filters.page_size));
	if (filters.actor_email) params.set('actor_email', filters.actor_email);
	if (filters.action) params.set('action', filters.action);
	if (filters.resource_type) params.set('resource_type', filters.resource_type);
	if (filters.date_from) params.set('date_from', filters.date_from);
	if (filters.date_to) params.set('date_to', filters.date_to);
	if (filters.q) params.set('q', filters.q);
	const qs = params.toString();
	return api.get<AuditLogPage>(`${BASE}/audit-log${qs ? `?${qs}` : ''}`);
}

export function getRetentionStatus(): Promise<RetentionStatus[]> {
	return api.get<RetentionStatus[]>(`${BASE}/retention-status`);
}

export function getConsentOverview(): Promise<ConsentOverview> {
	return api.get<ConsentOverview>(`${BASE}/consent-overview`);
}

export function getMFAStatus(): Promise<MFAStatus> {
	return api.get<MFAStatus>(`${BASE}/mfa-status`);
}

export function exportAuditLogUrl(filters: AuditLogFilters = {}): string {
	const params = new URLSearchParams();
	if (filters.actor_email) params.set('actor_email', filters.actor_email);
	if (filters.action) params.set('action', filters.action);
	if (filters.resource_type) params.set('resource_type', filters.resource_type);
	if (filters.date_from) params.set('date_from', filters.date_from);
	if (filters.date_to) params.set('date_to', filters.date_to);
	if (filters.q) params.set('q', filters.q);
	const qs = params.toString();
	return `/api/v1${BASE}/audit-log/export${qs ? `?${qs}` : ''}`;
}

// ── Retention Policy Editing ────────────────────────────────────────────────

export interface RetentionPolicyUpdate {
	retention_days?: number;
	action?: string;
	is_active?: boolean;
}

export function updateRetentionPolicy(
	policyId: string,
	data: RetentionPolicyUpdate
): Promise<RetentionStatus> {
	return api.patch<RetentionStatus>(`${BASE}/retention-policies/${policyId}`, data);
}

// ── User Consent Management ─────────────────────────────────────────────────

export interface UserConsentStatus {
	[consent_type: string]: {
		action: string | null;
		version: string | null;
		recorded_at: string | null;
		ip_address: string | null;
	};
}

export interface ConsentRequest {
	consent_type: string;
	action: 'granted' | 'revoked';
	version: string;
}

export interface ConsentRecord {
	id: string;
	consent_type: string;
	action: string;
	version: string;
	recorded_at: string;
	ip_address: string | null;
}

export function getUserConsent(): Promise<UserConsentStatus> {
	return api.get<UserConsentStatus>(`${BASE}/consent`);
}

export function updateUserConsent(data: ConsentRequest): Promise<ConsentRecord> {
	return api.post<ConsentRecord>(`${BASE}/consent`, data);
}

export function getConsentHistory(): Promise<ConsentRecord[]> {
	return api.get<ConsentRecord[]>(`${BASE}/consent-history`);
}

// ── Compliance Export Configs ───────────────────────────────────────────────

export interface ExportConfig {
	id: string;
	organization_id: string | null;
	export_type: string;
	format: string;
	schedule: string;
	destination_type: string;
	destination_config: Record<string, string>;
	is_active: boolean;
	last_export_at: string | null;
	last_export_record_count: number;
	created_at: string;
}

export interface ExportConfigCreate {
	organization_id?: string;
	export_type: string;
	format?: string;
	schedule?: string;
	destination_type: string;
	destination_config: Record<string, string>;
	is_active?: boolean;
}

export function getExportConfigs(): Promise<ExportConfig[]> {
	return api.get<ExportConfig[]>(`${BASE}/export-configs`);
}

export function createExportConfig(data: ExportConfigCreate): Promise<ExportConfig> {
	return api.post<ExportConfig>(`${BASE}/export-configs`, data);
}

export function updateExportConfig(
	configId: string,
	data: Partial<ExportConfigCreate>
): Promise<ExportConfig> {
	return api.patch<ExportConfig>(`${BASE}/export-configs/${configId}`, data);
}

export function deleteExportConfig(configId: string): Promise<{ detail: string }> {
	return api.delete<{ detail: string }>(`${BASE}/export-configs/${configId}`);
}

export function runExportNow(configId: string): Promise<{ detail: string }> {
	return api.post<{ detail: string }>(`${BASE}/export-configs/${configId}/run-now`);
}

// ── Conversation Archives ───────────────────────────────────────────────────

export interface ArchiveEntry {
	id: string;
	conversation_id: string | null;
	organization_id: string;
	archived_by: string;
	archived_at: string;
	content_hash: string;
	version: number;
}

export interface ArchivePage {
	page: number;
	page_size: number;
	total: number;
	total_pages: number;
	results: ArchiveEntry[];
}

export interface ArchiveFilters {
	page?: number;
	page_size?: number;
	organization_id?: string;
	conversation_id?: string;
	date_from?: string;
	date_to?: string;
}

export interface ArchiveVerifyResult {
	id: string;
	verified: boolean;
	stored_hash: string;
	computed_hash: string;
}

export function getArchives(filters: ArchiveFilters = {}): Promise<ArchivePage> {
	const params = new URLSearchParams();
	if (filters.page) params.set('page', String(filters.page));
	if (filters.page_size) params.set('page_size', String(filters.page_size));
	if (filters.organization_id) params.set('organization_id', filters.organization_id);
	if (filters.conversation_id) params.set('conversation_id', filters.conversation_id);
	if (filters.date_from) params.set('date_from', filters.date_from);
	if (filters.date_to) params.set('date_to', filters.date_to);
	const qs = params.toString();
	return api.get<ArchivePage>(`${BASE}/archives${qs ? `?${qs}` : ''}`);
}

export function verifyArchive(archiveId: string): Promise<ArchiveVerifyResult> {
	return api.get<ArchiveVerifyResult>(`${BASE}/archives/${archiveId}/verify`);
}

// ── GDPR User Endpoints ────────────────────────────────────────────────────

export interface DeleteAccountResponse {
	success: boolean;
	message: string;
	summary?: Record<string, unknown>;
}

export function exportUserData(): Promise<Record<string, unknown>> {
	return api.get<Record<string, unknown>>(`${BASE}/users/me/export`);
}

export function deleteUserAccount(data: {
	confirm: boolean;
	reason?: string;
}): Promise<DeleteAccountResponse> {
	return api.delete<DeleteAccountResponse>(`${BASE}/users/me`, data, { skipErrorHandling: true });
}

// ── Effective Security Policy ──────────────────────────────────────────────

export interface EffectiveSecurityPolicy {
	mfa_required: boolean;
	mfa_enabled: boolean;
	session_timeout_minutes: number | null;
	max_concurrent_sessions: number | null;
}

export function getEffectiveSecurityPolicy(): Promise<EffectiveSecurityPolicy> {
	return api.get<EffectiveSecurityPolicy>(`${BASE}/security-policy`, { skipErrorHandling: true });
}
