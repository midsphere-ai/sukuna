/**
 * Run-scoped API surface, mounted on the sandbox session client.
 *
 * This replaces the backend-proxied run calls that used to live in `chat.ts`
 * (`startTask`, `injectMessage`, `cancelRun`, `branchConversation`,
 * `submitHitlResponse`, etc). After the backend purge every run-scoped
 * request goes straight to the conversation's sandbox; the first call in a
 * session is `acquireSession`, which hands back `{sandbox_host, jwt}`.
 *
 * Every wrapper takes `conversationId` as the first argument so callers
 * don't have to thread a `SandboxClient` through their stack — the client is
 * resolved from the session store on demand, and the 401 retry happens
 * inside `sandboxClient.ts`.
 */
import { getSandboxClient } from '$stores/sandboxSession';
import type { SandboxClient } from './sandboxClient';

// ── Schemas ───────────────────────────────────────────────────────────────

export interface MCPServerConfig {
	name: string;
	transport: 'stdio' | 'sse' | 'streamable-http' | 'websocket';
	command?: string;
	args?: string[];
	env?: Record<string, string>;
	url?: string;
	headers?: Record<string, string>;
	timeout?: number;
	description?: string;
}

export interface StartRunInput {
	task: string;
	conversationId?: string;
	parentRunId?: string;
	model?: string;
	instructions?: string;
	maxSteps?: number;
	mcpServers?: MCPServerConfig[];
	metadata?: Record<string, unknown>;
	userId?: string;
	sessionId?: string;
}

export interface StartRunResponse {
	run_id: string;
	status: string;
	conversation_id: string;
}

export interface InjectMessageResponse {
	status: string;
	run_id: string;
}

export interface CancelRunResponse {
	status: string;
	run_id: string;
}

export interface BranchRunResponse {
	branch_conversation_id: string;
}

export interface HitlResponse {
	status: string;
	request_id: string;
}

export interface HitlRequestSummary {
	request_id: string;
	prompt: string;
	choices: unknown;
	status: string;
	response: string | null;
	created_at: string;
	responded_at: string | null;
}

export interface HitlListResponse {
	run_id: string;
	hitl_requests: HitlRequestSummary[];
	total: number;
}

export interface PendingHitlResponse {
	pending: boolean;
	request_id?: string;
	prompt?: string;
	choices?: unknown;
}

export interface RunMcpServer {
	name: string;
	tools: string[];
}

export interface ListRunMcpResponse {
	run_id: string;
	is_active: boolean;
	mcp_servers: RunMcpServer[];
}

export interface AddRunMcpResponse {
	server_name: string;
	tools_added: string[];
}

export interface RemoveRunMcpResponse {
	server_name: string;
	tools_removed: string[];
}

export interface FileTreeEntry {
	name: string;
	path: string;
	type: 'file' | 'directory';
	size?: number;
	children?: FileTreeEntry[];
}

export interface FilesTreeResponse {
	path: string;
	tree: FileTreeEntry[];
}

export interface FilesReadResponse {
	path: string;
	content: string;
	size: number;
	modified: string;
}

export interface FilesWriteResponse {
	path: string;
	size: number;
	status: string;
}

export interface FilesCreateResponse {
	path: string;
	type: string;
	status: string;
}

export interface FilesDeleteResponse {
	path: string;
	type: string;
	status: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function client(conversationId: string): SandboxClient {
	return getSandboxClient(conversationId);
}

function toStartRunBody(input: StartRunInput): Record<string, unknown> {
	return {
		task: input.task,
		conversation_id: input.conversationId,
		parent_run_id: input.parentRunId,
		model: input.model,
		instructions: input.instructions,
		max_steps: input.maxSteps,
		mcp_servers: input.mcpServers,
		metadata: input.metadata,
		user_id: input.userId,
		session_id: input.sessionId
	};
}

// ── Run lifecycle ─────────────────────────────────────────────────────────

export async function startRun(
	conversationId: string,
	input: StartRunInput
): Promise<StartRunResponse> {
	return client(conversationId).post<StartRunResponse>('/runs', toStartRunBody(input));
}

export async function injectMessage(
	conversationId: string,
	runId: string,
	message: string
): Promise<InjectMessageResponse> {
	return client(conversationId).post<InjectMessageResponse>(`/runs/${runId}/inject`, { message });
}

export async function cancelRun(conversationId: string, runId: string): Promise<CancelRunResponse> {
	return client(conversationId).del<CancelRunResponse>(`/runs/${runId}`);
}

export async function branchRun(
	conversationId: string,
	runId: string,
	fromMessageId: string
): Promise<BranchRunResponse> {
	return client(conversationId).post<BranchRunResponse>(`/runs/${runId}/branch`, {
		from_message_id: fromMessageId
	});
}

// ── HITL ──────────────────────────────────────────────────────────────────

export async function submitHitlResponse(
	conversationId: string,
	runId: string,
	requestId: string,
	response: string
): Promise<HitlResponse> {
	return client(conversationId).post<HitlResponse>(`/runs/${runId}/hitl/${requestId}`, {
		response
	});
}

export async function getHitlHistory(
	conversationId: string,
	runId: string,
	options?: { status?: string; limit?: number; offset?: number }
): Promise<HitlListResponse> {
	const params = new URLSearchParams();
	if (options?.status) params.set('status', options.status);
	if (options?.limit != null) params.set('limit', String(options.limit));
	if (options?.offset != null) params.set('offset', String(options.offset));
	const qs = params.toString();
	const path = `/runs/${runId}/hitl${qs ? `?${qs}` : ''}`;
	return client(conversationId).get<HitlListResponse>(path);
}

export async function getPendingHitl(
	conversationId: string,
	runId: string
): Promise<PendingHitlResponse> {
	return client(conversationId).get<PendingHitlResponse>(`/runs/${runId}/hitl/pending`);
}

// ── MCP hot-swap ──────────────────────────────────────────────────────────

export async function listRunMcpServers(
	conversationId: string,
	runId: string
): Promise<ListRunMcpResponse> {
	return client(conversationId).get<ListRunMcpResponse>(`/runs/${runId}/mcp`);
}

export async function addRunMcpServer(
	conversationId: string,
	runId: string,
	config: MCPServerConfig
): Promise<AddRunMcpResponse> {
	return client(conversationId).post<AddRunMcpResponse>(`/runs/${runId}/mcp`, config);
}

export async function removeRunMcpServer(
	conversationId: string,
	runId: string,
	serverName: string
): Promise<RemoveRunMcpResponse> {
	return client(conversationId).del<RemoveRunMcpResponse>(
		`/runs/${runId}/mcp/${encodeURIComponent(serverName)}`
	);
}

// ── File operations ───────────────────────────────────────────────────────

export async function filesTree(conversationId: string, path = ''): Promise<FilesTreeResponse> {
	const qs = path ? `?path=${encodeURIComponent(path)}` : '';
	return client(conversationId).get<FilesTreeResponse>(`/files/tree${qs}`);
}

export async function filesRead(conversationId: string, path: string): Promise<FilesReadResponse> {
	return client(conversationId).get<FilesReadResponse>(
		`/files/read?path=${encodeURIComponent(path)}`
	);
}

export async function filesWrite(
	conversationId: string,
	path: string,
	content: string
): Promise<FilesWriteResponse> {
	return client(conversationId).put<FilesWriteResponse>('/files/write', { path, content });
}

export async function filesCreate(
	conversationId: string,
	path: string,
	type: 'file' | 'directory' = 'file',
	content = ''
): Promise<FilesCreateResponse> {
	return client(conversationId).post<FilesCreateResponse>('/files/create', {
		path,
		type,
		content
	});
}

export async function filesDelete(
	conversationId: string,
	path: string
): Promise<FilesDeleteResponse> {
	return client(conversationId).del<FilesDeleteResponse>(
		`/files/delete?path=${encodeURIComponent(path)}`
	);
}

/** Return the absolute sandbox URL for a run's SSE stream. */
export function streamUrl(conversationId: string, runId: string): string {
	return client(conversationId).buildUrl(`/runs/${runId}/stream`);
}
