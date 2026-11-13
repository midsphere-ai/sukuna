/**
 * Thin bearer-auth fetch wrapper for direct-to-sandbox calls.
 *
 * Each sandbox session consists of `{host, jwt}` minted by the backend's
 * `/chat/sandbox/acquire` endpoint. This client binds a host + a JWT
 * provider (async, so the token can be refreshed transparently) and exposes
 * JSON get/post/put/delete plus raw fetch escape hatches for SSE and
 * `StreamingHttpResponse` payloads.
 *
 * On a 401 the client calls `refreshToken()` and retries the request once
 * with the new JWT; on the second 401 it surfaces a `SandboxClientError` so
 * the caller can re-acquire a session.
 */
import { getFetch } from '$utils/fetch';

export interface SandboxClient {
	host: string;
	get<T>(path: string, options?: SandboxRequestOptions): Promise<T>;
	post<T>(path: string, body?: unknown, options?: SandboxRequestOptions): Promise<T>;
	put<T>(path: string, body?: unknown, options?: SandboxRequestOptions): Promise<T>;
	del<T>(path: string, body?: unknown, options?: SandboxRequestOptions): Promise<T>;
	/** Raw fetch for SSE / streaming responses; the caller owns the `Response`. */
	rawFetch(path: string, options?: SandboxRequestOptions): Promise<Response>;
	/** Build an absolute sandbox URL for a given sub-path (no leading slash normalisation). */
	buildUrl(path: string): string;
}

export interface SandboxRequestOptions extends Omit<RequestInit, 'body'> {
	body?: unknown;
	/** Omit the bearer header entirely — used for public health probes. */
	skipAuth?: boolean;
	/** Include an explicit `api_key` query param (browser EventSource flow). */
	apiKey?: string;
}

export interface SandboxClientDeps {
	host: string;
	tokenProvider: () => string | null | undefined;
	refreshToken: () => Promise<string | null>;
}

export class SandboxClientError extends Error {
	status: number;
	errorCode: string | null;
	detail: unknown | null;
	data: unknown;

	constructor(
		status: number,
		message: string,
		data?: unknown,
		errorCode?: string | null,
		detail?: unknown | null
	) {
		super(message);
		this.name = 'SandboxClientError';
		this.status = status;
		this.data = data;
		this.errorCode = errorCode ?? null;
		this.detail = detail ?? null;
	}
}

interface ParsedError {
	message: string;
	errorCode: string | null;
	detail: unknown | null;
}

async function parseErrorBody(response: Response): Promise<ParsedError> {
	try {
		const data = await response.json();
		if (typeof data === 'string') return { message: data, errorCode: null, detail: null };

		const errorCode: string | null = typeof data.error_code === 'string' ? data.error_code : null;
		const errorDetail: unknown | null = data.detail !== undefined ? data.detail : null;

		let message: string;
		if (data.error) message = String(data.error);
		else if (typeof data.detail === 'string') message = data.detail;
		else if (data.message) message = String(data.message);
		else message = JSON.stringify(data);

		return { message, errorCode, detail: errorDetail };
	} catch {
		try {
			const text = await response.text();
			return { message: text, errorCode: null, detail: null };
		} catch {
			return {
				message: response.statusText || 'Unknown error',
				errorCode: null,
				detail: null
			};
		}
	}
}

function joinHostPath(host: string, path: string): string {
	if (path.startsWith('http://') || path.startsWith('https://')) return path;
	// E2B's sandbox.get_host(port) returns a bare hostname like
	// "8000-<id>.e2b.dev" — fetch() treats scheme-less strings as same-origin
	// relative paths, so we must add https:// for cross-origin sandbox calls.
	const hostWithScheme =
		host.startsWith('http://') || host.startsWith('https://') ? host : `https://${host}`;
	const cleanHost = hostWithScheme.replace(/\/$/, '');
	const cleanPath = path.startsWith('/') ? path : `/${path}`;
	return `${cleanHost}${cleanPath}`;
}

export function createSandboxClient(deps: SandboxClientDeps): SandboxClient {
	const { host, tokenProvider, refreshToken } = deps;

	async function sendRaw(
		path: string,
		options: SandboxRequestOptions,
		token: string | null | undefined
	): Promise<Response> {
		const { body, skipAuth = false, apiKey, headers: extraHeaders, ...rest } = options;

		const headers = new Headers(extraHeaders);
		if (!skipAuth && token) headers.set('Authorization', `Bearer ${token}`);

		const isFormData = body instanceof FormData;
		if (body !== undefined && !isFormData && !headers.has('Content-Type')) {
			headers.set('Content-Type', 'application/json');
		}

		let url = joinHostPath(host, path);
		if (apiKey) {
			const separator = url.includes('?') ? '&' : '?';
			url = `${url}${separator}api_key=${encodeURIComponent(apiKey)}`;
		}

		const httpFetch = await getFetch();
		return httpFetch(url, {
			...rest,
			headers,
			body: isFormData ? (body as FormData) : body !== undefined ? JSON.stringify(body) : undefined
		});
	}

	async function request<T>(path: string, options: SandboxRequestOptions): Promise<T> {
		let token = tokenProvider() ?? null;
		const method = (options.method || 'GET').toUpperCase();
		const url = joinHostPath(host, path);
		const started = performance.now();
		const tokenPreview = token ? `${token.slice(0, 8)}…(${token.length})` : '(none)';
		console.debug(`[sandboxClient] ${method} ${url} token=${tokenPreview}`);

		let response: Response;
		try {
			response = await sendRaw(path, options, token);
		} catch (err) {
			console.error(`[sandboxClient] ${method} ${url} network error:`, err);
			throw new SandboxClientError(0, 'Network error', err);
		}

		if (response.status === 401 && !options.skipAuth) {
			console.warn(`[sandboxClient] ${method} ${url} → 401, attempting token refresh`);
			let refreshed: string | null = null;
			try {
				refreshed = await refreshToken();
			} catch (err) {
				console.error(`[sandboxClient] ${method} ${url} token refresh threw:`, err);
			}
			if (refreshed) {
				token = refreshed;
				console.debug(
					`[sandboxClient] ${method} ${url} retrying with refreshed token (len=${refreshed.length})`
				);
				try {
					response = await sendRaw(path, options, token);
				} catch (err) {
					console.error(`[sandboxClient] ${method} ${url} retry network error:`, err);
					throw new SandboxClientError(0, 'Network error', err);
				}
			} else {
				console.warn(`[sandboxClient] ${method} ${url} token refresh returned empty`);
			}
		}

		const elapsedMs = Math.round(performance.now() - started);

		if (!response.ok) {
			const parsed = await parseErrorBody(response);
			console.error(
				`[sandboxClient] ${method} ${url} → ${response.status} (${elapsedMs}ms)`,
				parsed
			);
			throw new SandboxClientError(
				response.status,
				parsed.message,
				undefined,
				parsed.errorCode,
				parsed.detail
			);
		}

		console.debug(`[sandboxClient] ${method} ${url} → ${response.status} (${elapsedMs}ms)`);

		const contentType = response.headers.get('content-type');
		if (contentType?.includes('application/json')) {
			return response.json() as Promise<T>;
		}
		// Caller likely asked for text (tiny /health bodies, etc).
		const text = await response.text();
		return text as unknown as T;
	}

	async function rawFetch(path: string, options: SandboxRequestOptions = {}): Promise<Response> {
		const token = tokenProvider() ?? null;
		return sendRaw(path, options, token);
	}

	return {
		host,
		get<T>(path: string, options?: SandboxRequestOptions) {
			return request<T>(path, { ...(options ?? {}), method: 'GET' });
		},
		post<T>(path: string, body?: unknown, options?: SandboxRequestOptions) {
			return request<T>(path, { ...(options ?? {}), method: 'POST', body });
		},
		put<T>(path: string, body?: unknown, options?: SandboxRequestOptions) {
			return request<T>(path, { ...(options ?? {}), method: 'PUT', body });
		},
		del<T>(path: string, body?: unknown, options?: SandboxRequestOptions) {
			return request<T>(path, { ...(options ?? {}), method: 'DELETE', body });
		},
		rawFetch,
		buildUrl(path: string) {
			return joinHostPath(host, path);
		}
	};
}
