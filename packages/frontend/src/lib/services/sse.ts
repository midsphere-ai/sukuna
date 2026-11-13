/**
 * SSE streaming service — StreamSession class + backward-compatible module exports.
 *
 * Post-purge: direct-mode only. The chat page first calls
 * `acquireSession(conversationId)` (see `$stores/sandboxSession`) to get
 * `{host, jwt}` for the conversation's sandbox; `connectToRun` then reads
 * that session from the store and opens an SSE stream directly at
 * `{host}/runs/{runId}/stream`. The shared public view (`connectToSharedRun`)
 * still points at the backend's read-only SSE for `/chat/shared/*`.
 *
 * There is no proxy transport, no polling fallback, and no embedded
 * `direct_stream_url` / `direct_stream_token` threaded through the API —
 * the session store is the single source of truth for sandbox auth.
 */
import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';
import { toasts } from '$stores/toast';
import { detectLimitError, usageLimitModal } from '$stores/usageLimit';
import { invalidateCreditBalance, fetchCreditBalance } from '$stores/credits';
import { createSSEParserState, parseSSELines } from '$lib/utils/sseParser';
import { computerPanelToolIndex } from '$stores/computerPanel';
import { expandPane } from '$stores/workspaceLayout';
import { SILENT_TOOLS as SILENT_TOOL_NAMES } from '$lib/utils/toolLabels';
import { getFetch } from '$utils/fetch';
import { isTauri } from '$utils/platform';
import { sanitizeStreamText } from '$lib/utils/promptGuard';
import { getSession, refreshSession } from '$stores/sandboxSession';
import {
	pushDebugEvent,
	markConnected,
	markReconnectScheduled,
	markDisconnected,
	resetStreamDiagnostics
} from '$stores/debugBus';

const API_V1 = '/api/v1';
const API_BASE = browser ? import.meta.env.VITE_API_BASE_URL || '' : '';

function apiV1Url(path: string): string {
	if (path.startsWith('http://') || path.startsWith('https://')) return path;
	if (path.startsWith(`${API_V1}/`)) return `${API_BASE}${path}`;
	return `${API_BASE}${API_V1}${path}`;
}

// ── Re-export types (72+ files import these from '$lib/services/sse') ──────
export type {
	RunStatus,
	StreamTransport,
	Message,
	TextMessage,
	UserMessage,
	ToolCallMessage,
	HitlMessage,
	ErrorMessage,
	StepMessage,
	ReasoningMessage,
	McpProgressMessage,
	PhaseInfo,
	PlanState,
	StepInfo,
	TokenUsage,
	HitlRequest,
	PersistedEvent,
	PaginationCursor
} from './stream-types';

import type {
	RunStatus,
	StreamTransport,
	Message,
	ToolCallMessage,
	PhaseInfo,
	PlanState,
	StepInfo,
	TokenUsage,
	HitlRequest,
	PersistedEvent,
	PaginationCursor
} from './stream-types';

// ── Plan tool matchers (compat — server tags with _plan:true, but old servers may not) ──
function isPlanTool(name: string, args: Record<string, unknown>): boolean {
	return (
		name === 'mcp_update_plan' ||
		name === 'mcp_advance_plan' ||
		name === 'mcp_get_plan' ||
		(name === 'plan' && typeof args.action === 'string')
	);
}
function isPlanGet(name: string, args: Record<string, unknown>): boolean {
	return name === 'mcp_get_plan' || (name === 'plan' && args.action === 'get');
}

function _refreshCreditBalance(): void {
	invalidateCreditBalance();
	void fetchCreditBalance().catch(() => {
		// Credit refresh is best-effort and must never surface as an unhandled rejection.
	});
}

function normalisePhaseStatus(value: unknown): PhaseInfo['status'] {
	const raw = String(value || '')
		.trim()
		.toLowerCase();
	if (raw === 'in_progress' || raw === 'in-progress' || raw === 'in progress' || raw === 'active')
		return 'in_progress';
	if (raw === 'completed' || raw === 'complete' || raw === 'done' || raw === 'finished')
		return 'completed';
	return 'pending';
}

function normalisePhaseLabel(value: unknown): string {
	if (typeof value !== 'string') return '';
	return value.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function parsePhasesFromArgs(raw: unknown): PhaseInfo[] {
	if (!Array.isArray(raw)) return [];
	return raw
		.map((phase, index) => {
			if (typeof phase === 'string') {
				const description = normalisePhaseLabel(phase);
				return {
					id: `phase_${index + 1}`,
					description,
					status: 'pending' as const
				};
			}
			if (!isRecord(phase)) return null;

			const id = firstNonEmptyString(phase.id, phase.phase_id, phase.key) || `phase_${index + 1}`;
			const description =
				firstNonEmptyString(
					phase.description,
					phase.title,
					phase.name,
					phase.step,
					phase.objective,
					phase.goal
				) || normalisePhaseLabel(id);

			return {
				id,
				description,
				status: normalisePhaseStatus(phase.status),
				startedAt:
					(firstNonEmptyString(phase.startedAt, phase.started_at) as string | null) || undefined,
				completedAt:
					(firstNonEmptyString(phase.completedAt, phase.completed_at) as string | null) || undefined
			};
		})
		.filter((phase): phase is PhaseInfo => phase !== null);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseStructuredString(value: unknown): unknown {
	if (typeof value !== 'string') return value;
	const trimmed = value.trim();
	if (!trimmed) return value;
	if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return value;
	try {
		return JSON.parse(trimmed);
	} catch {
		return value;
	}
}

function normaliseArgs(value: unknown): Record<string, unknown> {
	const parsed = parseStructuredString(value);
	return isRecord(parsed) ? parsed : {};
}

function normaliseResult(value: unknown): unknown {
	return parseStructuredString(value);
}

function firstNonEmptyString(...values: unknown[]): string | null {
	for (const value of values) {
		if (typeof value !== 'string') continue;
		const trimmed = value.trim();
		if (trimmed) return trimmed;
	}
	return null;
}

function toolErrorMessage(rawError: unknown): string | undefined {
	const parsed = parseStructuredString(rawError);
	const direct = firstNonEmptyString(parsed);
	if (direct) return direct;
	if (parsed == null || parsed === false) return undefined;
	if (Array.isArray(parsed)) {
		for (const item of parsed) {
			const nested = toolErrorMessage(item);
			if (nested) return nested;
		}
		return parsed.length > 0 ? 'Tool call failed' : undefined;
	}
	if (isRecord(parsed)) {
		const nested = firstNonEmptyString(parsed.error, parsed.message, parsed.detail);
		if (nested) return nested;
		return Object.keys(parsed).length > 0 ? 'Tool call failed' : undefined;
	}
	return String(parsed);
}

function resolveToolError(success: unknown, rawError: unknown): string | undefined {
	if (success === false) return toolErrorMessage(rawError) || 'Tool call failed';
	return toolErrorMessage(rawError);
}

function hasMessageToolOutput(tool: ToolCallMessage): boolean {
	if (tool.toolName !== 'message') return false;
	const result = parseStructuredString(tool.result);
	const resultObj = isRecord(result) ? result : null;
	return Boolean(
		firstNonEmptyString(
			tool.args?.text,
			tool.args?.content,
			resultObj?.message,
			resultObj?.text,
			resultObj?.content
		)
	);
}

function parsePersistedEventData(event: PersistedEvent): Record<string, unknown> {
	if (typeof event.data === 'string') {
		try {
			const parsed = JSON.parse(event.data);
			return isRecord(parsed) ? parsed : {};
		} catch (error: unknown) {
			console.warn('[SSE replay] Dropped malformed persisted event payload:', error);
			return {};
		}
	}
	if (isRecord(event.data)) return event.data;
	console.warn('[SSE replay] Dropped malformed persisted event payload:', event.data);
	return {};
}

function reconcileUnresolvedToolAtTerminal(
	tool: ToolCallMessage,
	status: 'completed' | 'failed' | 'cancelled'
): ToolCallMessage {
	if (tool.status !== 'running') return tool;
	if (status === 'completed') {
		return { ...tool, status: 'success', error: undefined };
	}
	if (hasMessageToolOutput(tool)) {
		// Message tools can produce user-visible output before a later terminal failure.
		return { ...tool, status: 'success', error: undefined };
	}
	return { ...tool, status: 'error', error: tool.error || 'Run ended before tool completed' };
}

// ── Module-level stores (public API — components subscribe to $messages, $runStatus, etc.) ──
export const runStatus = writable<RunStatus>('idle');
export const streamTransport = writable<StreamTransport>('none');
/**
 * Kept for backward compat with debug UIs; always null after the proxy-fallback
 * purge. Direct-mode SSE either connects or raises a hard error.
 */
export const directStreamFailureReason = writable<string | null>(null);
export const messages = writable<Message[]>([]);
export const toolCalls = writable<Map<string, ToolCallMessage>>(new Map());
export const activeStep = writable<StepInfo | null>(null);
export const tokenUsage = writable<TokenUsage>({
	inputTokens: 0,
	outputTokens: 0,
	totalTokens: 0,
	model: ''
});
export const hitlRequest = writable<HitlRequest | null>(null);
export const planState = writable<PlanState | null>(null);
export const eventsHasMore = writable<boolean>(false);
export const creditBurn = writable<number>(0);
export const isThinking = writable<boolean>(false);
export const isReconnecting = writable<boolean>(false);
export const injectionQueuePosition = writable<number | null>(null);

// ── Internal state ──
let pendingPromptText: string | null = null;
let oldestLoadedSequence = Infinity;
let oldestLoadedCursor: PaginationCursor | null = null;

// ══════════════════════════════════════════════════════════════════════════════
// StreamSession — internal class managing one SSE connection
// ══════════════════════════════════════════════════════════════════════════════

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;
const NON_RETRIABLE_HTTP_STATUSES = new Set([401, 403, 404]);
const RECONNECT_TOAST_THRESHOLD = 3;

class StreamConnectError extends Error {
	readonly status: number;
	readonly retriable: boolean;

	constructor(status: number, retriable: boolean) {
		super(`SSE connect failed: ${status}`);
		this.name = 'StreamConnectError';
		this.status = status;
		this.retriable = retriable;
	}
}

class StreamSession {
	private seq = -1;
	private abortController: AbortController | null = null;
	private assistantText = '';
	private isStreamingText = false;
	private activeTextSourceAgent: string | undefined = undefined;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private consecutiveFailures = 0;
	private currentPhaseId: string | null = null;
	private planToolCallIds = new Set<string>();
	/**
	 * Transport for this session:
	 *  - `direct`: sandbox SSE (JWT bearer, looked up from `sandboxSession` store)
	 *  - `shared`: backend `/chat/shared/*` SSE (no auth, public view)
	 */
	private transport: Exclude<StreamTransport, 'none'> = 'direct';
	/**
	 * For `shared` transport, the absolute backend URL is stored here at
	 * connect time. For `direct` transport, the URL is resolved per-attempt
	 * from the sandbox session so a refreshed host always wins.
	 */
	private sharedUrl: string | null = null;
	/**
	 * Sandbox run endpoint path (e.g. `/runs/{run_id}/stream`) for direct
	 * transport. Combined with the current session host each attempt.
	 */
	private runStreamPath: string | null = null;

	currentRunId: string | null = null;
	conversationId: string | null = null;

	connectDirect(conversationId: string, runId: string, afterSeq?: number): void {
		this.abortController?.abort();
		this.abortController = new AbortController();
		this.seq = afterSeq ?? this.seq;
		this.consecutiveFailures = 0;
		this.conversationId = conversationId;
		this.currentRunId = runId;
		this.transport = 'direct';
		this.runStreamPath = `/runs/${runId}/stream`;
		this.sharedUrl = null;
		runStatus.set('connecting');
		directStreamFailureReason.set(null);
		this._doConnect();
	}

	connectShared(conversationId: string, afterSeq?: number): void {
		this.abortController?.abort();
		this.abortController = new AbortController();
		this.seq = afterSeq ?? this.seq;
		this.consecutiveFailures = 0;
		this.conversationId = conversationId;
		this.transport = 'shared';
		this.sharedUrl = apiV1Url(`/chat/shared/${conversationId}/stream`);
		this.runStreamPath = null;
		runStatus.set('connecting');
		directStreamFailureReason.set(null);
		this._doConnect();
	}

	private _isTerminalStatus(status: RunStatus): boolean {
		return (
			status === 'completed' ||
			status === 'failed' ||
			status === 'cancelled' ||
			status === 'error' ||
			status === 'idle'
		);
	}

	private _shouldReconnectOnEOF(): boolean {
		if (this.abortController?.signal.aborted) return false;
		return !this._isTerminalStatus(get(runStatus));
	}

	private _resolveConnectUrl(): string | null {
		let base: string | null;
		if (this.transport === 'direct') {
			if (!this.conversationId || !this.runStreamPath) return null;
			const session = getSession(this.conversationId);
			if (!session) return null;
			// E2B's bare hostnames (e.g. "8000-<id>.e2b.dev") must be prefixed
			// with https:// — otherwise fetch() treats the whole URL as a
			// same-origin relative path and never hits the sandbox.
			const hostWithScheme =
				session.host.startsWith('http://') || session.host.startsWith('https://')
					? session.host
					: `https://${session.host}`;
			const cleanHost = hostWithScheme.replace(/\/$/, '');
			base = `${cleanHost}${this.runStreamPath}`;
		} else {
			base = this.sharedUrl;
		}
		if (!base) return null;
		return this.seq >= 0 ? `${base}${base.includes('?') ? '&' : '?'}after=${this.seq}` : base;
	}

	private _streamHeaders(): Record<string, string> {
		if (this.transport === 'direct' && this.conversationId) {
			const session = getSession(this.conversationId);
			if (session?.jwt) return { Authorization: `Bearer ${session.jwt}` };
		}
		return {};
	}

	private async _recoverDirectAuth(): Promise<boolean> {
		if (this.transport !== 'direct' || !this.conversationId) return false;
		try {
			await refreshSession(this.conversationId);
			return true;
		} catch (error) {
			console.warn('[SSE] Failed to refresh sandbox session JWT:', error);
			return false;
		}
	}

	private async _doConnect(): Promise<void> {
		const connectUrl = this._resolveConnectUrl();
		if (!connectUrl) {
			console.error(
				'[SSE] No sandbox session for conversation',
				this.conversationId,
				'transport=',
				this.transport,
				'runStreamPath=',
				this.runStreamPath
			);
			// No session available — caller must acquire before connecting.
			runStatus.set('error');
			messages.update((msgs) => [
				...msgs,
				{ type: 'error', message: 'No sandbox session available for this conversation.' }
			]);
			return;
		}

		const fetchFn = isTauri() ? await getFetch() : globalThis.fetch;

		try {
			const headers = this._streamHeaders();
			const hasAuth = 'Authorization' in headers;
			console.debug(
				`[SSE] connecting transport=${this.transport} url=${connectUrl} auth=${hasAuth} seq=${this.seq}`
			);
			const resp = await fetchFn(connectUrl, {
				signal: this.abortController?.signal,
				headers
			});
			console.debug(
				`[SSE] connect ← ${resp.status} url=${connectUrl} content-type=${resp.headers.get('content-type')}`
			);
			if (!resp.ok) {
				if (resp.status === 401 && this.transport === 'direct') {
					const recovered = await this._recoverDirectAuth();
					if (recovered) {
						if (this._isTerminalStatus(get(runStatus))) {
							isReconnecting.set(false);
							return;
						}
						return this._doConnect();
					}
					throw new StreamConnectError(resp.status, false);
				}
				throw new StreamConnectError(resp.status, !NON_RETRIABLE_HTTP_STATUSES.has(resp.status));
			}
			if (!resp.body) throw new Error('No response body');

			runStatus.set('running');
			streamTransport.set(this.transport);
			isReconnecting.set(false);
			markConnected(connectUrl, this.transport);

			const reader = resp.body.getReader();
			const decoder = new TextDecoder();
			let buffer = '';
			const parserState = createSSEParserState();

			while (true) {
				const { done, value } = await reader.read();
				if (done) {
					if (this._shouldReconnectOnEOF()) {
						console.warn('[SSE] Stream ended before terminal event; reconnecting...');
						this._scheduleReconnect();
					}
					break;
				}
				buffer += decoder.decode(value, { stream: true });
				buffer = parseSSELines(
					buffer,
					(eventType: string, data: unknown, eventId?: string) => {
						const seq = eventId ? parseInt(eventId, 10) : -1;
						const prevSeq = this.seq;
						this.handleEvent(eventType, data, seq);
						const advancedSeq = seq >= 0 && this.seq > prevSeq;
						const meaningfulNoSeqEvent =
							seq < 0 &&
							eventType !== 'status' &&
							eventType !== 'context' &&
							eventType !== 'message_injected';
						if (advancedSeq || meaningfulNoSeqEvent) {
							this.consecutiveFailures = 0;
						}
					},
					parserState
				);
			}
		} catch (err: unknown) {
			if (err instanceof DOMException && err.name === 'AbortError') return;
			if (err instanceof StreamConnectError && !err.retriable) {
				console.error(`[SSE] non-retriable error status=${err.status} url=${connectUrl}`, err);
				isThinking.set(false);
				runStatus.set('error');
				isReconnecting.set(false);
				const message =
					err.status === 401 || err.status === 403
						? 'Stream authorization failed. Please refresh and try again.'
						: err.status === 404
							? 'Run stream was not found.'
							: 'Run stream failed with a non-retriable error.';
				messages.update((msgs) => [...msgs, { type: 'error', message }]);
				return;
			}
			console.warn(`[SSE] connection error url=${connectUrl}:`, err);
			this._scheduleReconnect();
		}
	}

	private _scheduleReconnect(): void {
		if (this._isTerminalStatus(get(runStatus))) {
			isReconnecting.set(false);
			return;
		}
		this.consecutiveFailures++;
		markReconnectScheduled(this.consecutiveFailures, 'connection_error');
		if (this.consecutiveFailures === RECONNECT_TOAST_THRESHOLD) {
			toasts.error('Connection to agent lost, retrying...');
		}
		if (this.consecutiveFailures > MAX_RECONNECT_ATTEMPTS) {
			isThinking.set(false);
			runStatus.set('error');
			isReconnecting.set(false);
			toasts.error('Connection to agent lost after multiple retries.');
			messages.update((msgs) => [
				...msgs,
				{ type: 'error', message: 'Connection lost after multiple retries' }
			]);
			return;
		}
		isReconnecting.set(true);
		const delay = Math.min(
			BASE_RECONNECT_DELAY_MS * Math.pow(2, this.consecutiveFailures - 1),
			MAX_RECONNECT_DELAY_MS
		);
		const jitter = delay * (0.75 + Math.random() * 0.5);
		this.reconnectTimer = setTimeout(() => this._doConnect(), jitter);
	}

	private handleEvent(type: string, data: unknown, seq: number): void {
		// Sequence-based dedup — one integer comparison replaces seenToolCallIds + counters
		if (seq >= 0 && seq <= this.seq) return;
		if (seq >= 0) this.seq = seq;

		const d = isRecord(data) ? data : {};

		// Debug-mode tap: push every (de-duplicated) event into the ring buffer.
		// No-op when the debug-mode feature flag is off.
		pushDebugEvent({
			seq,
			type,
			payload: d,
			transport: this.transport
		});

		switch (type) {
			case 'user_message': {
				const text = String(d.text || '');
				if (!text) break;
				const files = Array.isArray(d.files) ? d.files.map(String) : undefined;
				const timestamp = new Date().toISOString();
				const senderId = firstNonEmptyString(d.sender_id);
				const senderName = firstNonEmptyString(d.sender_name);
				messages.update((msgs) => {
					const last = msgs[msgs.length - 1];
					if (last?.type === 'user' && last.text === text && last.optimistic) {
						return [
							...msgs.slice(0, -1),
							{
								...last,
								optimistic: false,
								created_at: last.created_at || timestamp,
								...(senderId ? { sender_id: senderId } : {}),
								...(senderName ? { sender_name: senderName } : {})
							}
						];
					}
					if (msgs.some((m) => m.type === 'user' && !m.optimistic && m.text === text)) return msgs;
					return [
						...msgs,
						{
							type: 'user',
							text,
							files,
							created_at: timestamp,
							...(senderId ? { sender_id: senderId } : {}),
							...(senderName ? { sender_name: senderName } : {})
						}
					];
				});
				break;
			}
			case 'text': {
				isThinking.set(false);
				const content = String(d.content || d.text || '');
				const sourceAgent = firstNonEmptyString(d.source_agent, d.agent_name) || undefined;
				if (content) {
					const clean = sanitizeStreamText(content);
					if (clean) this.appendText(clean, sourceAgent);
				}
				break;
			}
			case 'tool_call': {
				this.finalizeText();
				isThinking.set(false);
				const callId = String(d.tool_call_id || d.call_id || '');
				const toolName = String(d.tool_name || d.name || 'unknown');
				const args = normaliseArgs(d.arguments);
				const sourceAgent = firstNonEmptyString(d.source_agent, d.agent_name) || undefined;

				// Plan events — tagged server-side or detected by name
				if (d._plan || isPlanTool(toolName, args)) {
					this.planToolCallIds.add(callId);
					if (toolName === 'mcp_update_plan' || (toolName === 'plan' && args.action === 'update')) {
						const phases = parsePhasesFromArgs(args.phases);
						const phaseId = String(args.current_phase_id || phases[0]?.id || '');
						this.currentPhaseId = phaseId;
						planState.set({
							goal: String(args.goal || ''),
							phases: phases.map((p) =>
								p.id === phaseId
									? { ...p, status: 'in_progress', startedAt: new Date().toISOString() }
									: p
							),
							currentPhaseId: phaseId
						});
					} else if (
						toolName === 'mcp_advance_plan' ||
						(toolName === 'plan' && args.action === 'advance')
					) {
						const nextPhaseId = String(args.next_phase_id || '');
						this.currentPhaseId = nextPhaseId;
						planState.update((s) =>
							s
								? {
										...s,
										currentPhaseId: nextPhaseId,
										phases: s.phases.map((p) => {
											if (p.id === String(args.current_phase_id || s.currentPhaseId))
												return {
													...p,
													status: 'completed' as const,
													completedAt: new Date().toISOString()
												};
											if (p.id === nextPhaseId)
												return {
													...p,
													status: 'in_progress' as const,
													startedAt: new Date().toISOString()
												};
											return p;
										})
									}
								: s
						);
					}
					break;
				}

				const toolCall: ToolCallMessage = {
					type: 'tool_call',
					callId,
					toolName,
					args,
					status: 'running',
					phaseId: this.currentPhaseId ?? undefined,
					source_agent: sourceAgent
				};
				toolCalls.update((map) => new Map(map).set(callId, toolCall));
				messages.update((msgs) => {
					const idx = msgs.findIndex((m) => m.type === 'tool_call' && m.callId === callId);
					if (idx >= 0) {
						const r = [...msgs];
						r[idx] = toolCall;
						return r;
					}
					return [...msgs, toolCall];
				});

				const toolPart = toolName.includes('__')
					? toolName.split('__').pop() || toolName
					: toolName;
				if (!SILENT_TOOL_NAMES.has(toolName) && !SILENT_TOOL_NAMES.has(toolPart)) {
					const tcMap = get(toolCalls);
					const idx = Array.from(tcMap.keys()).indexOf(callId);
					if (idx >= 0) {
						computerPanelToolIndex.set(idx);
						expandPane('editor');
					}
				}
				break;
			}
			case 'tool_result': {
				this.finalizeText();
				const callId = String(d.tool_call_id || d.call_id || '');
				const args = normaliseArgs(d.arguments);
				const result = normaliseResult(d.result);
				const resolvedError = resolveToolError(d.success, d.error);
				const sourceAgent = firstNonEmptyString(d.source_agent, d.agent_name) || undefined;
				if (this.planToolCallIds.has(callId)) {
					this.planToolCallIds.delete(callId);
					const toolName = String(d.tool_name || d.name || '');
					if (isPlanGet(toolName, args)) {
						const resultObj = isRecord(result) ? result : undefined;
						if (resultObj?.success && isRecord(resultObj.message)) {
							const pd = resultObj.message as Record<string, unknown>;
							planState.set({
								goal: String(pd.goal || ''),
								phases: parsePhasesFromArgs(pd.phases),
								currentPhaseId: String(pd.current_phase_id || '')
							});
						}
					}
					break;
				}
				const existing = get(toolCalls).get(callId);
				const updated: ToolCallMessage = {
					type: 'tool_call',
					callId,
					toolName: String(d.tool_name || d.name || existing?.toolName || 'unknown'),
					args: Object.keys(args).length > 0 ? args : existing?.args || {},
					status: resolvedError ? 'error' : 'success',
					result,
					error: resolvedError,
					durationMs: d.duration_ms as number | undefined,
					phaseId: existing?.phaseId ?? this.currentPhaseId ?? undefined,
					source_agent: sourceAgent || existing?.source_agent
				};
				toolCalls.update((map) => new Map(map).set(callId, updated));
				messages.update((msgs) => {
					const idx = msgs.findIndex((m) => m.type === 'tool_call' && m.callId === callId);
					if (idx >= 0) {
						const r = [...msgs];
						r[idx] = updated;
						return r;
					}
					return [...msgs, updated];
				});
				isThinking.set(true);
				break;
			}
			case 'step': {
				const step: StepInfo = {
					stepNumber: Number(d.step_number),
					status: d.status as 'started' | 'completed',
					maxSteps: Number(d.max_steps) || get(activeStep)?.maxSteps || 50,
					durationMs: d.duration_ms as number | undefined
				};
				activeStep.set(step);
				messages.update((msgs) => [
					...msgs,
					{
						type: 'step',
						stepNumber: step.stepNumber,
						status: step.status,
						maxSteps: d.max_steps as number | undefined,
						durationMs: step.durationMs
					}
				]);
				if (step.status === 'started') isThinking.set(true);
				if (step.status === 'completed' && d.usage && typeof d.usage === 'object') {
					const u = d.usage as Record<string, number>;
					tokenUsage.update((t) => ({
						inputTokens: t.inputTokens + (u.input_tokens || 0),
						outputTokens: t.outputTokens + (u.output_tokens || 0),
						totalTokens: t.totalTokens + (u.total_tokens || 0),
						model: t.model
					}));
				}
				break;
			}
			case 'status': {
				const statusMap: Record<string, RunStatus> = {
					starting: 'running',
					pending: 'queued',
					running: 'running',
					queued: 'queued',
					provisioning: 'provisioning',
					waiting_for_tool: 'running',
					completed: 'completed',
					failed: 'failed',
					cancelled: 'cancelled',
					error: 'error'
				};
				const mapped = statusMap[String(d.status)];
				if (mapped) {
					if (
						mapped === 'completed' ||
						mapped === 'failed' ||
						mapped === 'cancelled' ||
						mapped === 'error'
					) {
						this._handleTerminal(mapped);
					} else {
						runStatus.set(mapped);
						if (mapped === 'running') isThinking.set(true);
					}
				}
				break;
			}
			case 'usage': {
				const u = (d.usage && typeof d.usage === 'object' ? d.usage : d) as Record<string, unknown>;
				tokenUsage.update((t) => ({
					inputTokens: Number(u.input_tokens ?? t.inputTokens),
					outputTokens: Number(u.output_tokens ?? t.outputTokens),
					totalTokens: Number(u.total_tokens ?? t.totalTokens),
					model: String(u.model || (d as Record<string, unknown>).model || t.model)
				}));
				const cost = Number(u.cost_usd ?? (d as Record<string, unknown>).cost_usd ?? 0);
				if (cost > 0) creditBurn.update((n) => n + Math.ceil(cost * 2.0 * 1000));
				break;
			}
			case 'reasoning': {
				isThinking.set(false);
				const text = String(d.text || d.content || '');
				const sourceAgent = firstNonEmptyString(d.source_agent, d.agent_name) || undefined;
				if (text) {
					messages.update((msgs) => [
						...msgs,
						{ type: 'reasoning', text, source_agent: sourceAgent }
					]);
				}
				break;
			}
			case 'mcp_progress':
				messages.update((msgs) => [
					...msgs,
					{
						type: 'mcp_progress',
						toolName: String(d.tool_name),
						progress: Number(d.progress),
						total: Number(d.total),
						message: String(d.message)
					}
				]);
				break;
			case 'tool_call_delta': {
				const id = String(d.tool_call_id || '');
				if (!id) break;
				toolCalls.update((map) => {
					const existing = map.get(id);
					if (existing) {
						const updated = { ...existing, args: { ...existing.args } };
						const delta = String(d.arguments_delta || '');
						if (delta) {
							updated.args._rawDelta = ((updated.args._rawDelta as string) || '') + delta;
						}
						return new Map(map).set(id, updated);
					}
					return map;
				});
				break;
			}
			case 'context':
				toasts.info(`Context ${d.action}: ${d.before_count ?? 0} → ${d.after_count ?? 0} messages`);
				break;
			case 'message_injected':
				toasts.info('Message injected into agent');
				break;
			case 'error': {
				this.finalizeText();
				isThinking.set(false);
				const msg = String(d.message || d.error || 'Unknown error');
				messages.update((msgs) => [...msgs, { type: 'error', message: msg }]);
				const limitInfo = detectLimitError(msg);
				if (limitInfo) usageLimitModal.show(limitInfo);
				break;
			}
			case 'hitl_request': {
				this.finalizeText();
				isThinking.set(false);
				if (!d.request_id || !d.prompt) break;
				hitlRequest.set({
					requestId: String(d.request_id),
					prompt: String(d.prompt),
					choices: Array.isArray(d.choices) ? d.choices.map(String) : undefined
				});
				runStatus.set('waiting_for_input');
				messages.update((msgs) => [
					...msgs,
					{
						type: 'hitl',
						requestId: String(d.request_id),
						prompt: String(d.prompt),
						choices: Array.isArray(d.choices) ? d.choices.map(String) : undefined
					}
				]);
				break;
			}
			case 'run_completed':
				this.currentRunId = String(d.run_id || '') || this.currentRunId;
				this._handleTerminal('completed');
				break;
			case 'run_failed':
				this.currentRunId = String(d.run_id || '') || this.currentRunId;
				this._handleTerminal('failed');
				if (d.error)
					messages.update((msgs) => [...msgs, { type: 'error', message: String(d.error) }]);
				break;
			case 'run_cancelled':
				this.currentRunId = String(d.run_id || '') || this.currentRunId;
				this._handleTerminal('cancelled');
				break;
		}
	}

	private _handleTerminal(status: RunStatus): void {
		this.finalizeText();
		isThinking.set(false);
		if (status === 'completed' || status === 'failed' || status === 'cancelled') {
			toolCalls.update((map) => {
				let changed = false;
				const next = new Map(map);
				for (const [id, tc] of next) {
					const reconciled = reconcileUnresolvedToolAtTerminal(tc, status);
					if (reconciled !== tc) {
						next.set(id, reconciled);
						changed = true;
					}
				}
				return changed ? next : map;
			});
			messages.update((msgs) => {
				let changed = false;
				const next = msgs.map((msg) => {
					if (msg.type !== 'tool_call') return msg;
					const reconciled = reconcileUnresolvedToolAtTerminal(msg, status);
					if (reconciled !== msg) {
						changed = true;
					}
					return reconciled;
				});
				return changed ? next : msgs;
			});
		}
		runStatus.set(status);
		hitlRequest.set(null);
		creditBurn.set(0);
		_refreshCreditBalance();
	}

	private appendText(content: string, sourceAgent?: string): void {
		if (
			this.isStreamingText &&
			sourceAgent &&
			this.activeTextSourceAgent &&
			sourceAgent !== this.activeTextSourceAgent
		) {
			// Agent switched mid-stream: finalize previous message first so
			// planner and executor text do not get merged into one bubble.
			this.finalizeText();
		}

		this.assistantText += content;
		if (!this.isStreamingText) {
			this.isStreamingText = true;
			this.activeTextSourceAgent = sourceAgent;
			messages.update((msgs) => [
				...msgs,
				{
					type: 'assistant',
					text: this.assistantText,
					isStreaming: true,
					source_agent: sourceAgent
				}
			]);
		} else {
			if (!this.activeTextSourceAgent && sourceAgent) {
				this.activeTextSourceAgent = sourceAgent;
			}
			messages.update((msgs) => {
				const last = msgs[msgs.length - 1];
				if (last?.type === 'assistant') {
					return [
						...msgs.slice(0, -1),
						{
							...last,
							text: this.assistantText,
							source_agent: this.activeTextSourceAgent || last.source_agent
						}
					];
				}
				return msgs;
			});
		}
	}

	private finalizeText(): void {
		if (!this.isStreamingText) return;
		messages.update((msgs) => {
			const last = msgs[msgs.length - 1];
			if (last?.type === 'assistant')
				return [...msgs.slice(0, -1), { ...last, isStreaming: false }];
			return msgs;
		});
		this.assistantText = '';
		this.isStreamingText = false;
		this.activeTextSourceAgent = undefined;
	}

	disconnect(): void {
		this.abortController?.abort();
		this.abortController = null;
		if (this.reconnectTimer) {
			clearTimeout(this.reconnectTimer);
			this.reconnectTimer = null;
		}
		this.finalizeText();
		markDisconnected();
	}
}

// ══════════════════════════════════════════════════════════════════════════════
// Singleton + backward-compatible exported functions
// ══════════════════════════════════════════════════════════════════════════════

let _session: StreamSession | null = null;

/**
 * Connect to a live run's SSE stream on the conversation's sandbox.
 *
 * Requires a sandbox session to already be acquired for the conversation
 * (see `acquireSession` in `$stores/sandboxSession`). The host and JWT are
 * read from the session store on every connect attempt, so JWT refreshes
 * are picked up transparently.
 */
export function connectToRun(conversationId: string, runId: string, keepMessages = false): void {
	disconnect();
	if (!keepMessages) resetStores();

	_session = new StreamSession();
	streamTransport.set('direct');
	_session.connectDirect(conversationId, runId);
}

/** Connect to the backend-side shared SSE stream for public conversation views. */
export function connectToSharedRun(conversationId: string): void {
	disconnect();
	resetStores();
	_session = new StreamSession();
	streamTransport.set('shared');
	_session.connectShared(conversationId);
}

export function disconnect(): void {
	_session?.disconnect();
	_session = null;
	runStatus.set('idle');
	isReconnecting.set(false);
}

export function resetStores(): void {
	messages.set([]);
	toolCalls.set(new Map());
	activeStep.set(null);
	tokenUsage.set({ inputTokens: 0, outputTokens: 0, totalTokens: 0, model: '' });
	hitlRequest.set(null);
	planState.set(null);
	eventsHasMore.set(false);
	creditBurn.set(0);
	isThinking.set(false);
	isReconnecting.set(false);
	injectionQueuePosition.set(null);
	runStatus.set('idle');
	streamTransport.set('none');
	directStreamFailureReason.set(null);
	oldestLoadedSequence = Infinity;
	oldestLoadedCursor = null;
	resetStreamDiagnostics();
}

// ── Event replay (backward-compatible — pages still call this with PersistedEvent[]) ──

export function replayEvents(events: PersistedEvent[]): void {
	const existingOptimisticByText = new Map<
		string,
		{
			clientId?: string;
			addons?: string[];
			mcps?: string[];
			files?: string[];
			created_at?: string;
		}
	>();
	for (const msg of get(messages)) {
		if (msg.type !== 'user' || !msg.optimistic || !msg.text) continue;
		if (existingOptimisticByText.has(msg.text)) continue;
		existingOptimisticByText.set(msg.text, {
			clientId: msg.clientId,
			addons: msg.addons,
			mcps: msg.mcps,
			files: msg.files,
			created_at: msg.created_at
		});
	}
	const msgs: Message[] = [];
	const tcMap = new Map<string, ToolCallMessage>();
	let textAccum = '';
	let textSourceAgent: string | undefined;
	let lastSenderName: string | undefined;
	activeStep.set(null);
	hitlRequest.set(null);

	const reconcileRunningToolCalls = (status: 'completed' | 'failed' | 'cancelled'): void => {
		for (const [id, tc] of tcMap) {
			tcMap.set(id, reconcileUnresolvedToolAtTerminal(tc, status));
		}
		for (let i = 0; i < msgs.length; i++) {
			const msg = msgs[i];
			if (msg.type !== 'tool_call') continue;
			msgs[i] = reconcileUnresolvedToolAtTerminal(msg, status);
		}
	};

	for (const evt of events) {
		const raw = parsePersistedEventData(evt);
		const evtType = evt.type || evt.event_type || evt.event || raw.type || '';

		switch (evtType) {
			case 'text': {
				const sourceAgent =
					firstNonEmptyString(
						(raw as Record<string, unknown>).source_agent,
						(raw as Record<string, unknown>).agent_name
					) || undefined;
				if (textAccum && sourceAgent && textSourceAgent && sourceAgent !== textSourceAgent) {
					msgs.push({
						type: 'assistant',
						text: textAccum,
						isStreaming: false,
						started_by_name: lastSenderName,
						source_agent: textSourceAgent
					});
					textAccum = '';
					textSourceAgent = undefined;
				}
				const content = String(
					(raw as Record<string, unknown>).content || (raw as Record<string, unknown>).text || ''
				);
				textAccum += content;
				if (sourceAgent) textSourceAgent = sourceAgent;
				lastSenderName = String(
					(raw as Record<string, unknown>).sender_name || lastSenderName || ''
				);
				break;
			}
			case 'tool_call': {
				if (textAccum) {
					msgs.push({
						type: 'assistant',
						text: textAccum,
						isStreaming: false,
						started_by_name: lastSenderName,
						source_agent: textSourceAgent
					});
					textAccum = '';
					textSourceAgent = undefined;
				}
				const r = raw as Record<string, unknown>;
				const args = normaliseArgs(r.arguments);
				const sourceAgent = firstNonEmptyString(r.source_agent, r.agent_name) || undefined;
				if (r._plan || isPlanTool(String(r.tool_name || r.name || ''), args)) break;
				const callId = String(r.tool_call_id || r.call_id || '');
				const tc: ToolCallMessage = {
					type: 'tool_call',
					callId,
					toolName: String(r.tool_name || r.name || 'unknown'),
					args,
					status: 'running',
					source_agent: sourceAgent
				};
				tcMap.set(callId, tc);
				msgs.push(tc);
				break;
			}
			case 'tool_result': {
				if (textAccum) {
					msgs.push({
						type: 'assistant',
						text: textAccum,
						isStreaming: false,
						source_agent: textSourceAgent
					});
					textAccum = '';
					textSourceAgent = undefined;
				}
				const r = raw as Record<string, unknown>;
				const callId = String(r.tool_call_id || r.call_id || '');
				const args = normaliseArgs(r.arguments);
				const result = normaliseResult(r.result);
				const resolvedError = resolveToolError(r.success, r.error);
				const sourceAgent = firstNonEmptyString(r.source_agent, r.agent_name) || undefined;
				if (isPlanTool(String(r.tool_name || r.name || ''), args)) break;
				const existing = tcMap.get(callId);
				if (existing) {
					if (Object.keys(args).length > 0) existing.args = args;
					existing.status = resolvedError ? 'error' : 'success';
					existing.result = result;
					existing.error = resolvedError;
					existing.durationMs = r.duration_ms as number | undefined;
					existing.source_agent = sourceAgent || existing.source_agent;
				} else {
					const synthetic: ToolCallMessage = {
						type: 'tool_call',
						callId,
						toolName: String(r.tool_name || r.name || 'unknown'),
						args,
						status: resolvedError ? 'error' : 'success',
						result,
						error: resolvedError,
						durationMs: r.duration_ms as number | undefined,
						source_agent: sourceAgent
					};
					tcMap.set(callId, synthetic);
					msgs.push(synthetic);
				}
				break;
			}
			case 'user_message': {
				if (textAccum) {
					msgs.push({
						type: 'assistant',
						text: textAccum,
						isStreaming: false,
						source_agent: textSourceAgent
					});
					textAccum = '';
					textSourceAgent = undefined;
				}
				const r = raw as Record<string, unknown>;
				const text = String(r.text || r.content || '');
				const optimistic = existingOptimisticByText.get(text);
				const files = Array.isArray(r.files)
					? r.files.filter((f): f is string => typeof f === 'string' && f.trim().length > 0)
					: optimistic?.files;
				const senderId = firstNonEmptyString(r.sender_id);
				const senderName = firstNonEmptyString(r.sender_name);
				msgs.push({
					type: 'user',
					text,
					files,
					...(optimistic?.addons ? { addons: optimistic.addons } : {}),
					...(optimistic?.mcps ? { mcps: optimistic.mcps } : {}),
					...(optimistic?.clientId ? { clientId: optimistic.clientId } : {}),
					...(optimistic?.created_at ? { created_at: optimistic.created_at } : {}),
					...(senderId ? { sender_id: senderId } : {}),
					...(senderName ? { sender_name: senderName } : {})
				});
				break;
			}
			case 'step': {
				const r = raw as Record<string, unknown>;
				const step: StepInfo = {
					stepNumber: Number(r.step_number),
					status: r.status as 'started' | 'completed',
					maxSteps: Number(r.max_steps) || get(activeStep)?.maxSteps || 50,
					durationMs: r.duration_ms as number | undefined
				};
				activeStep.set(step);
				msgs.push({
					type: 'step',
					stepNumber: step.stepNumber,
					status: step.status,
					maxSteps: r.max_steps as number | undefined,
					durationMs: step.durationMs
				});
				if (step.status === 'completed' && r.usage && typeof r.usage === 'object') {
					const usage = r.usage as Record<string, number>;
					tokenUsage.update((t) => ({
						inputTokens: t.inputTokens + (usage.input_tokens || 0),
						outputTokens: t.outputTokens + (usage.output_tokens || 0),
						totalTokens: t.totalTokens + (usage.total_tokens || 0),
						model: t.model
					}));
				}
				break;
			}
			case 'status': {
				const r = raw as Record<string, unknown>;
				const statusMap: Record<string, RunStatus> = {
					starting: 'running',
					pending: 'queued',
					running: 'running',
					queued: 'queued',
					provisioning: 'provisioning',
					waiting_for_tool: 'running',
					completed: 'completed',
					failed: 'failed',
					cancelled: 'cancelled',
					error: 'error'
				};
				const mapped = statusMap[String(r.status)];
				if (mapped) {
					runStatus.set(mapped);
				}
				break;
			}
			case 'error': {
				if (textAccum) {
					msgs.push({
						type: 'assistant',
						text: textAccum,
						isStreaming: false,
						source_agent: textSourceAgent
					});
					textAccum = '';
					textSourceAgent = undefined;
				}
				msgs.push({
					type: 'error',
					message: String(
						(raw as Record<string, unknown>).message || (raw as Record<string, unknown>).error || ''
					)
				});
				break;
			}
			case 'hitl_request': {
				if (textAccum) {
					msgs.push({
						type: 'assistant',
						text: textAccum,
						isStreaming: false,
						source_agent: textSourceAgent
					});
					textAccum = '';
					textSourceAgent = undefined;
				}
				const r = raw as Record<string, unknown>;
				hitlRequest.set({
					requestId: String(r.request_id),
					prompt: String(r.prompt),
					choices: Array.isArray(r.choices) ? r.choices.map(String) : undefined
				});
				runStatus.set('waiting_for_input');
				msgs.push({
					type: 'hitl',
					requestId: String(r.request_id),
					prompt: String(r.prompt),
					choices: Array.isArray(r.choices) ? r.choices.map(String) : undefined
				});
				break;
			}
			case 'reasoning': {
				const r = raw as Record<string, unknown>;
				msgs.push({
					type: 'reasoning',
					text: String(r.text || r.content || ''),
					source_agent: firstNonEmptyString(r.source_agent, r.agent_name) || undefined
				});
				break;
			}
			case 'usage': {
				const u = ((raw as Record<string, unknown>).usage || raw) as Record<string, unknown>;
				tokenUsage.set({
					inputTokens: Number(u.input_tokens || 0),
					outputTokens: Number(u.output_tokens || 0),
					totalTokens: Number(u.total_tokens || 0),
					model: String(
						u.model || (raw as Record<string, unknown>).model || get(tokenUsage).model || ''
					)
				});
				break;
			}
			case 'mcp_progress': {
				const r = raw as Record<string, unknown>;
				msgs.push({
					type: 'mcp_progress',
					toolName: String(r.tool_name),
					progress: Number(r.progress),
					total: Number(r.total),
					message: String(r.message)
				});
				break;
			}
			case 'run_completed':
				reconcileRunningToolCalls('completed');
				runStatus.set('completed');
				hitlRequest.set(null);
				break;
			case 'run_failed':
				reconcileRunningToolCalls('failed');
				runStatus.set('failed');
				hitlRequest.set(null);
				if ((raw as Record<string, unknown>).error) {
					msgs.push({ type: 'error', message: String((raw as Record<string, unknown>).error) });
				}
				break;
			case 'run_cancelled':
				reconcileRunningToolCalls('cancelled');
				runStatus.set('cancelled');
				hitlRequest.set(null);
				break;
		}

		if (typeof evt.sequence === 'number' && evt.sequence < oldestLoadedSequence) {
			oldestLoadedSequence = evt.sequence;
		}
	}
	if (textAccum)
		msgs.push({
			type: 'assistant',
			text: textAccum,
			isStreaming: false,
			started_by_name: lastSenderName,
			source_agent: textSourceAgent
		});
	messages.set(msgs);
	toolCalls.set(tcMap);
}

export function replayEventsPage(
	events: PersistedEvent[],
	hasMore: boolean,
	nextCursor?: PaginationCursor
): void {
	replayEvents(events);
	eventsHasMore.set(hasMore);
	if (nextCursor) oldestLoadedCursor = nextCursor;
}

export function prependOlderEvents(
	events: PersistedEvent[],
	hasMore: boolean,
	nextCursor?: PaginationCursor
): void {
	const savedMsgs = get(messages);
	const savedTc = get(toolCalls);
	resetStores();
	replayEvents(events);
	const olderMsgs = get(messages);
	const olderTc = get(toolCalls);
	const merged = [...olderMsgs, ...savedMsgs];
	const mergedTc = new Map([...olderTc, ...savedTc]);
	messages.set(merged);
	toolCalls.set(mergedTc);
	eventsHasMore.set(hasMore);
	if (nextCursor) oldestLoadedCursor = nextCursor;
}

// ── User message management ──

export function addUserMessage(
	text: string,
	files?: string[],
	addons?: string[],
	mcps?: string[],
	clientId?: string
): void {
	messages.update((msgs) => [
		...msgs,
		{
			type: 'user',
			text,
			files,
			addons,
			mcps,
			clientId,
			optimistic: !!clientId,
			created_at: new Date().toISOString()
		}
	]);
}

export function rollbackUserMessage(clientId: string): void {
	messages.update((msgs) => msgs.filter((m) => !(m.type === 'user' && m.clientId === clientId)));
}

export function confirmUserMessage(clientId: string): void {
	messages.update((msgs) =>
		msgs.map((m) =>
			m.type === 'user' && m.clientId === clientId ? { ...m, optimistic: false } : m
		)
	);
}

export function addErrorMessage(message: string): void {
	messages.update((msgs) => [...msgs, { type: 'error', message }]);
}

export function updateHitlResponse(requestId: string, response: string): void {
	hitlRequest.set(null);
	messages.update((msgs) =>
		msgs.map((m) => (m.type === 'hitl' && m.requestId === requestId ? { ...m, response } : m))
	);
}

// ── State accessors ──

export function getCurrentRunId(): string | null {
	return _session?.currentRunId ?? null;
}
export function getCurrentConversationId(): string | null {
	return _session?.conversationId ?? null;
}
export function getOldestLoadedSequence(): number {
	return oldestLoadedSequence;
}
export function getOldestLoadedCursor(): PaginationCursor | null {
	if (oldestLoadedCursor) return oldestLoadedCursor;
	if (oldestLoadedSequence < Infinity) return { before_sequence: oldestLoadedSequence };
	return null;
}
export function restorePaginationState(hasMore: boolean, cursor: PaginationCursor | null): void {
	eventsHasMore.set(hasMore);
	oldestLoadedCursor = cursor;
}

// ── Prompt persistence (survives page navigation) ──

export function noteSubmissionStart(): void {
	runStatus.set('connecting');
}
export function setPendingPrompt(text: string): void {
	pendingPromptText = text;
}
export function consumePendingPrompt(): string | null {
	const t = pendingPromptText;
	pendingPromptText = null;
	return t;
}
