/**
 * Per-conversation sandbox session cache.
 *
 * After the backend purge, each chat session lives under a JWT minted by
 * `POST /api/v1/chat/sandbox/acquire`. That call returns
 * `{conversation_id, sandbox_host, jwt, expires_at}`; the frontend then talks
 * direct to the sandbox for the run lifecycle.
 *
 * This store caches one session per conversation, surfaces a
 * `SandboxClient` bound to the right host/JWT, and refreshes the JWT
 * ~30 s before expiry (or on demand when the client sees a 401) via
 * `POST /api/v1/chat/sandbox/jwt-refresh`. Home-page "new chat" acquires are
 * keyed by a sentinel `__new__` entry which promotes to the real
 * conversation id once the response lands.
 */
import { get, writable } from 'svelte/store';
import { api } from '$api/client';
import { createSandboxClient, type SandboxClient } from '$api/sandboxClient';

export interface SandboxSession {
	conversationId: string;
	host: string;
	jwt: string;
	expiresAt: string;
}

interface AcquireRequestBody {
	conversation_id?: string;
	project_id?: string;
	prompt_preview?: string;
}

interface AcquireResponse {
	conversation_id: string;
	sandbox_host: string;
	jwt: string;
	expires_at: string;
}

/** Skew: refresh the JWT this far ahead of `expires_at` to avoid racing the clock. */
const REFRESH_SKEW_MS = 30_000;

export const sandboxSessions = writable<Record<string, SandboxSession>>({});

/** Tracks in-flight acquires/refreshes so concurrent callers coalesce onto one HTTP request. */
const inflight = new Map<string, Promise<SandboxSession>>();

function parseExpiresAt(iso: string): number {
	const t = Date.parse(iso);
	return Number.isFinite(t) ? t : 0;
}

function writeSession(session: SandboxSession): void {
	sandboxSessions.update((map) => ({ ...map, [session.conversationId]: session }));
}

function isSessionFresh(session: SandboxSession | undefined): session is SandboxSession {
	if (!session) return false;
	const expiresMs = parseExpiresAt(session.expiresAt);
	return expiresMs - Date.now() > REFRESH_SKEW_MS;
}

async function callAcquire(body: AcquireRequestBody): Promise<SandboxSession> {
	console.debug('[sandboxSession] acquire →', body);
	try {
		const resp = await api.post<AcquireResponse>('/chat/sandbox/acquire', body);
		console.debug('[sandboxSession] acquire ←', {
			conversation_id: resp.conversation_id,
			sandbox_host: resp.sandbox_host,
			expires_at: resp.expires_at,
			jwt_len: resp.jwt?.length ?? 0
		});
		return {
			conversationId: resp.conversation_id,
			host: resp.sandbox_host,
			jwt: resp.jwt,
			expiresAt: resp.expires_at
		};
	} catch (err) {
		console.error('[sandboxSession] acquire failed:', err);
		throw err;
	}
}

async function callRefresh(conversationId: string): Promise<SandboxSession> {
	console.debug('[sandboxSession] refresh →', { conversation_id: conversationId });
	try {
		const resp = await api.post<AcquireResponse>('/chat/sandbox/jwt-refresh', {
			conversation_id: conversationId
		});
		console.debug('[sandboxSession] refresh ←', {
			conversation_id: resp.conversation_id,
			sandbox_host: resp.sandbox_host,
			expires_at: resp.expires_at,
			jwt_len: resp.jwt?.length ?? 0
		});
		return {
			conversationId: resp.conversation_id,
			host: resp.sandbox_host,
			jwt: resp.jwt,
			expiresAt: resp.expires_at
		};
	} catch (err) {
		console.error('[sandboxSession] refresh failed:', err);
		throw err;
	}
}

export function getSession(conversationId: string): SandboxSession | undefined {
	return get(sandboxSessions)[conversationId];
}

/**
 * Acquire (or re-use) a session for a known conversation. If `conversationId` is
 * omitted the backend mints a fresh conversation; the caller should read the
 * returned `conversationId` to navigate into the new chat.
 */
export async function acquireSession(
	options: {
		conversationId?: string;
		projectId?: string;
		promptPreview?: string;
	} = {}
): Promise<SandboxSession> {
	const { conversationId, projectId, promptPreview } = options;

	if (conversationId) {
		const existing = get(sandboxSessions)[conversationId];
		if (isSessionFresh(existing)) return existing;

		const dedupeKey = `acquire:${conversationId}`;
		const inflightExisting = inflight.get(dedupeKey);
		if (inflightExisting) return inflightExisting;

		const promise = callAcquire({
			conversation_id: conversationId,
			project_id: projectId,
			prompt_preview: promptPreview
		}).then((session) => {
			writeSession(session);
			return session;
		});
		inflight.set(dedupeKey, promise);
		void promise.finally(() => inflight.delete(dedupeKey)).catch(() => undefined);
		return promise;
	}

	// New-conversation path: no dedupe (each click is its own conversation).
	const session = await callAcquire({
		project_id: projectId,
		prompt_preview: promptPreview
	});
	writeSession(session);
	return session;
}

/** Force-refresh the JWT for an existing conversation. Used by the 401 retry path. */
export async function refreshSession(conversationId: string): Promise<SandboxSession> {
	const dedupeKey = `refresh:${conversationId}`;
	const inflightExisting = inflight.get(dedupeKey);
	if (inflightExisting) return inflightExisting;

	const promise = callRefresh(conversationId).then((session) => {
		writeSession(session);
		return session;
	});
	inflight.set(dedupeKey, promise);
	void promise.finally(() => inflight.delete(dedupeKey)).catch(() => undefined);
	return promise;
}

/**
 * Ensure a session exists and is fresh, refreshing if it is within the skew
 * window. Consumers that need a guaranteed-valid JWT should call this right
 * before issuing a request that can't tolerate a round-trip failure.
 */
export async function ensureFreshSession(conversationId: string): Promise<SandboxSession> {
	const existing = get(sandboxSessions)[conversationId];
	if (isSessionFresh(existing)) return existing;
	if (existing) return refreshSession(conversationId);
	return acquireSession({ conversationId });
}

export function clearSession(conversationId: string): void {
	sandboxSessions.update((map) => {
		if (!(conversationId in map)) return map;
		const next = { ...map };
		delete next[conversationId];
		return next;
	});
}

export function clearAllSessions(): void {
	sandboxSessions.set({});
	inflight.clear();
}

/**
 * Build a `SandboxClient` for a known-acquired conversation. The client reads
 * the JWT from the store on every call and transparently calls
 * `refreshSession()` on 401 so callers never see a stale token.
 */
export function getSandboxClient(conversationId: string): SandboxClient {
	const session = getSession(conversationId);
	if (!session) {
		throw new Error(
			`No sandbox session for conversation ${conversationId} — call acquireSession first`
		);
	}
	return createSandboxClient({
		host: session.host,
		tokenProvider: () => get(sandboxSessions)[conversationId]?.jwt ?? null,
		refreshToken: async () => {
			const refreshed = await refreshSession(conversationId);
			return refreshed.jwt;
		}
	});
}
