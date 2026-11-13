// User & Auth types

export interface User {
	id: string;
	name: string;
	email: string;
	avatar: string;
	is_active: boolean;
	date_joined: string;
	last_login: string | null;
	enterprise_mode: boolean;
	onboarding_completed?: boolean;
	mfa_enrolled?: boolean;
	mfa_pending?: boolean;
}

export interface LoginRequest {
	email: string;
	password: string;
}

export interface LoginResponse {
	key: string;
}

export interface CreateUserRequest {
	user_name: string;
	user_email: string;
	password: string;
}

export interface UserUpdateRequest {
	user_name?: string;
	user_email?: string;
}

export interface GoogleAuthRequest {
	id_token: string;
}

export interface GoogleAuthResponse {
	key: string;
	user: {
		pk: string;
		email: string;
		name: string;
	};
}

export interface RequestOTPRequest {
	email: string;
}

export interface VerifyOTPRequest {
	email: string;
	otp: string;
	new_password: string;
}

export interface OTPResponse {
	success: boolean;
	message: string;
}

export interface PasswordChangeRequest {
	old_password: string;
	new_password1: string;
	new_password2: string;
}

// Conversation types

export interface Conversation {
	id: string;
	title: string;
	icon?: string;
	summary: string | null;
	/** @deprecated Use status instead */
	on_going?: boolean;
	/** @deprecated Use status instead */
	has_error?: boolean;
	error: string | null;
	date_created: string;
	date_updated: string;
	metadata: Record<string, unknown>;
	status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled' | 'queued' | 'provisioning';
	project_id?: string | null;
}

export interface ConversationCreateResponse {
	conversation_id: string;
	is_new: boolean;
	message: string;
}

// File types

export interface StoredFile {
	id: string;
	name: string;
	file: string;
	size: number;
	mime_type: string;
	uploaded_at: string;
	updated_at: string;
}

export interface FileUploadResponse {
	file_id: string;
	filename: string;
	size: number;
	mime_type: string;
	message: string;
}

// Addon types

export interface MarketplaceAddon {
	id: string;
	name: string;
	description: string;
	link: string;
	logo: string;
	enum: string;
	tags: string[];
	date_created: string;
}

export interface UserAddon {
	id: string;
	enabled_addon: MarketplaceAddon;
	auth_complete: boolean;
	config_id: string | null;
	auth_link: string | null;
	auth_link_created_at: string | null;
}

// MCP types

export interface UserMCPConfig {
	id: string;
	server_name: string;
	server_type: 'stdio' | 'sse' | 'streamable-http';
	command: string | null;
	url: string | null;
	args: string[];
	env: Record<string, string>;
	timeout: number | null;
	description: string;
}

export interface MCPConfigInput {
	server_name: string;
	server_type: 'stdio' | 'sse' | 'streamable-http';
	command?: string;
	url?: string;
	args?: string[];
	env?: Record<string, string>;
	timeout?: number;
	description?: string;
}

// Pagination

export interface PaginatedResponse<T> {
	items: T[];
	count: number;
}

// Action responses (matches backend ActionResponse / DeleteActionResponse)

export interface ActionResponse {
	message: string;
}

export interface DeleteResponse extends ActionResponse {
	deleted_count: number;
}

// Billing types

export interface SubscriptionPlan {
	id: string;
	name: string;
	tier: string;
	price: number;
	monthly_credits: number;
	features: Record<string, unknown>;
	is_active: boolean;
}

export interface UsageMetric {
	limit: number;
	used: number;
	label: string;
}

export interface SubscriptionUsage {
	credits: UsageMetric;
	concurrent_tasks: UsageMetric;
}

export interface UserSubscription {
	id: string;
	plan: SubscriptionPlan;
	status: 'active' | 'cancelled' | 'expired' | 'pending';
	start_date: string | null;
	end_date: string | null;
	auto_renew: boolean;
	dodo_subscription_id: string | null;
	usage_schema: SubscriptionUsage | null;
}

export interface Payment {
	id: string;
	dodo_payment_id: string | null;
	amount: number;
	currency: string;
	status: string;
	created_at: string;
}

// Credit system types

export interface CreditBalance {
	total_available: number;
	monthly_credits: number;
	monthly_credits_remaining: number;
	addon_credits: number;
	free_credits: number;
	daily_credits_remaining: number;
	active_grants: number;
	active_holds: number;
}

export interface CreditTransaction {
	id: string;
	amount: number;
	balance_after: number;
	category:
		| 'llm'
		| 'compute'
		| 'integration'
		| 'grant'
		| 'refund'
		| 'refresh'
		| 'purchase'
		| 'signup_bonus';
	source_type: string;
	description: string;
	created_at: string;
}

export interface CreditPurchaseResponse {
	checkout_url: string | null;
	credits: number;
}

export type CreditUsageSummary = Record<string, number>;

// Settings types

export interface UserSettings {
	id: string;
	theme: string;
	accent_color: string;
	custom_instructions: string;
	nickname: string;
	occupation: string;
	about_you: string;
	onboarding_completed: boolean | null;
	web_search: boolean;
	browser: boolean;
	shell_commands: boolean;
	complex_reasoning: boolean;
	computer_use: boolean;
	notification_email: boolean;
	notification_push: boolean;
	notification_marketing: boolean;
	data_share_analytics: boolean;
	data_share_training: boolean;
	backend_url: string;
	local_mode: boolean;
	local_sandbox_url: string;
}

export type UserSettingsUpdate = Partial<Omit<UserSettings, 'id'>>;

// Support Tickets

export interface SupportTicket {
	id: string;
	title: string;
	message: string;
	status: 'open' | 'in_progress' | 'resolved' | 'closed';
	created_at: string;
	updated_at: string;
}

// CMS

export interface Tutorial {
	id: string;
	title: string;
	subtitle: string | null;
	image: string | null;
	markdownText?: string;
	as_info_button: boolean;
	date_created: string;
}

// Project types

export interface Project {
	id: string;
	title: string;
	description: string;
	icon: string;
	custom_instructions: string;
	isolated_toolkit: boolean;
	user: number;
	sandbox: string | null;
	date_created: string;
	date_updated: string;
}

export interface ProjectListItem extends Project {
	conversation_count: number;
	is_shared?: boolean;
	organization_id?: string | null;
}

export interface ProjectConversationSummary {
	id: string;
	title: string | null;
	date_created: string;
	date_updated: string;
}

export interface ProjectDetail extends Project {
	conversations: ProjectConversationSummary[];
	conversation_count: number;
}

export interface ProjectCreateRequest {
	title: string;
	description: string;
	icon?: string;
	custom_instructions?: string;
	template_id?: string;
	initial_skill_ids?: string[];
	isolated_toolkit?: boolean;
}

export interface ProjectUpdateRequest {
	title?: string;
	description?: string;
	icon?: string;
	custom_instructions?: string;
	isolated_toolkit?: boolean;
}

export interface ProjectCreateResponse {
	project_id: string;
}

export interface ProjectUpdateResponse {
	project_id: string;
	modified: boolean;
}

export interface ProjectDeleteResponse {
	project_id: string;
	deleted: boolean;
}

export interface ProjectFile {
	id: string;
	filename: string;
	file_path: string;
	mime_type: string;
	size_bytes: number;
	date_created: string;
}

export interface ProjectFileUploadResponse {
	file_id: string;
	filename: string;
	size_bytes: number;
	mime_type: string;
}

export interface ProjectFileDeleteResponse {
	file_id: string;
	deleted: boolean;
}

export interface ProjectSandboxStatus {
	busy: boolean;
	active_conversation_id: string | null;
	active_conversation_title: string | null;
}

export interface MoveProjectResult {
	project_id: string;
	organization_id: string | null;
	moved: boolean;
	warnings: string[];
}

// Project Toolkit types

export interface ProjectSkillEntry {
	id: string;
	skill: {
		id: string;
		slug: string;
		name: string;
		description: string;
		category: string;
		icon: string;
		source_type: string;
		author: string;
		tags: string[];
	};
	config_overrides: Record<string, unknown>;
	date_created: string;
}

export interface ProjectMCPConfigEntry {
	id: string;
	server_name: string;
	server_type: 'stdio' | 'sse' | 'streamable-http';
	command: string | null;
	arguments: string;
	env: string;
	url: string | null;
	timeout: number | null;
	sse_read_timeout: number | null;
	client_session_timeout_seconds: number | null;
	description: string;
	date_created: string;
}

export interface ProjectAddonEntry {
	id: string;
	addon: {
		id: string;
		enabled_addon: {
			id: string;
			name: string;
			description: string;
			logo: string;
		} | null;
	};
	config: Record<string, unknown>;
	date_created: string;
}

export interface ProjectToolkit {
	isolated_toolkit: boolean;
	skills: ProjectSkillEntry[];
	mcp_configs: ProjectMCPConfigEntry[];
	addons: ProjectAddonEntry[];
}

export interface ProjectToolkitUpdateRequest {
	isolated_toolkit?: boolean;
	skill_ids?: string[];
	addon_ids?: string[];
}

export interface ProjectMCPConfigCreateRequest {
	server_name: string;
	server_type?: 'stdio' | 'sse' | 'streamable-http';
	command?: string;
	arguments?: string;
	env?: string;
	url?: string;
	timeout?: number;
	description?: string;
}

// Developer API Key types

export interface DeveloperAPIKey {
	id: string;
	name: string;
	key_prefix: string;
	scopes: string[];
	is_active: boolean;
	last_used_at: string | null;
	expires_at: string | null;
	date_created: string;
	date_updated: string;
}

export interface DeveloperAPIKeyCreated {
	id: string;
	name: string;
	key: string;
	key_prefix: string;
	scopes: string[];
	expires_at: string | null;
	date_created: string;
}

export interface CreateAPIKeyRequest {
	name: string;
	scopes: string[];
	expires_at?: string | null;
}

// BYOM (Bring Your Own Model) types

export type BYOMToolSlot = 'lead_agent' | 'vision' | 'browser' | 'audio';

export type BYOMProviderName = 'openai' | 'anthropic' | 'azure_openai' | 'openrouter' | 'ollama';

export interface BYOMProvider {
	id: string;
	tool_slot: BYOMToolSlot;
	provider_name: BYOMProviderName;
	model_name: string;
	api_key_masked: string;
	base_url: string;
	extras: Record<string, string>;
	is_active: boolean;
	date_created: string;
	date_updated: string;
}

export interface BYOMProviderInput {
	tool_slot: BYOMToolSlot;
	provider_name: BYOMProviderName;
	model_name: string;
	api_key: string;
	base_url?: string;
	extras?: Record<string, string>;
}

// Standardised error envelope (matches backend ErrorResponseSchema)

export interface ApiErrorResponse {
	error: string;
	error_code: string;
	detail: unknown | null;
	status: number;
}

// Client-side error representation

export interface ApiError {
	status: number;
	message: string;
	errorCode: string | null;
	detail: unknown | null;
	data?: unknown;
}
