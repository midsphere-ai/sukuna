import { browser } from '$app/environment';
import { get } from 'svelte/store';
import { goto } from '$app/navigation';
import { authToken, clearAuth } from '$stores/auth';
import { toasts } from '$stores/toast';
import { getFetch } from '$utils/fetch';
import type { ApiError } from './types';

const API_BASE = browser ? import.meta.env.VITE_API_BASE_URL || '' : '';

/** Prefix for all versioned public API endpoints. */
export const API_V1 = '/api/v1';

/** Prefixes that are NOT versioned (internal / third-party auth). */
const _UNVERSIONED_PREFIXES = ['/authentication/', '/accounts/', '/health/'];

/** Prepend the version prefix unless the path is unversioned or absolute. */
function versionedUrl(path: string): string {
	if (path.startsWith('http')) return path;
	if (_UNVERSIONED_PREFIXES.some((p) => path.startsWith(p))) return `${API_BASE}${path}`;
	return `${API_BASE}${API_V1}${path}`;
}

export class ApiClientError extends Error {
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
		this.name = 'ApiClientError';
		this.status = status;
		this.data = data;
		this.errorCode = errorCode ?? null;
		this.detail = detail ?? null;
	}

	toApiError(): ApiError {
		return {
			status: this.status,
			message: this.message,
			errorCode: this.errorCode,
			detail: this.detail,
			data: this.data
		};
	}
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
	body?: unknown;
	skipAuth?: boolean;
	skipErrorHandling?: boolean;
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

		// Standardised error envelope: { error, error_code, detail, status }
		const errorCode: string | null = typeof data.error_code === 'string' ? data.error_code : null;
		const errorDetail: unknown | null = data.detail !== undefined ? data.detail : null;

		let message: string;
		if (data.error) {
			message = String(data.error);
		} else if (data.detail && typeof data.detail === 'string') {
			message = data.detail;
		} else if (data.message) {
			message = String(data.message);
		} else if (data.non_field_errors) {
			message = String(data.non_field_errors[0]);
		} else {
			message = JSON.stringify(data);
		}

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

// Deduplication map for in-flight GET requests
const inflight = new Map<string, Promise<unknown>>();

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
	const { body, skipAuth = false, skipErrorHandling = false, ...fetchOptions } = options;

	// Deduplicate concurrent identical GET requests
	const method = (fetchOptions.method ?? 'GET').toUpperCase();
	const dedupeKey = method === 'GET' ? `${method}:${path}` : null;
	if (dedupeKey) {
		const existing = inflight.get(dedupeKey);
		if (existing) return existing as Promise<T>;
	}

	const promise = doRequest<T>(path, body, skipAuth, skipErrorHandling, fetchOptions);

	if (dedupeKey) {
		inflight.set(dedupeKey, promise);
		void promise.finally(() => inflight.delete(dedupeKey)).catch(() => undefined);
	}

	return promise;
}

async function doRequest<T>(
	path: string,
	body: unknown | undefined,
	skipAuth: boolean,
	skipErrorHandling: boolean,
	fetchOptions: Omit<RequestInit, 'body'>
): Promise<T> {
	const headers = new Headers(fetchOptions.headers);

	if (!skipAuth) {
		const token = get(authToken);
		if (token) {
			headers.set('Authorization', `Bearer ${token}`);
		}
	}

	const isFormData = body instanceof FormData;

	if (body !== undefined && !isFormData && !headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json');
	}

	const url = versionedUrl(path);

	let response: Response;
	try {
		const httpFetch = await getFetch();
		response = await httpFetch(url, {
			...fetchOptions,
			headers,
			body: isFormData ? (body as FormData) : body !== undefined ? JSON.stringify(body) : undefined
		});
	} catch (err) {
		if (!skipErrorHandling && browser) {
			toasts.error('Network error. Please check your connection.');
		}
		throw new ApiClientError(0, 'Network error', err);
	}

	if (!response.ok) {
		const parsedError = await parseErrorBody(response);

		if (
			(response.status === 401 || response.status === 403) &&
			!skipAuth &&
			!skipErrorHandling &&
			browser
		) {
			// Only clear auth if we actually sent a token (confirms server rejected it)
			const token = get(authToken);
			if (token) {
				clearAuth();
				// eslint-disable-next-line svelte/no-navigation-without-resolve
				goto('/login');
			}
			throw new ApiClientError(
				response.status,
				response.status === 401 ? 'Session expired. Please log in again.' : 'Access denied.',
				undefined,
				parsedError.errorCode,
				parsedError.detail
			);
		}

		if (!skipErrorHandling && browser) {
			if (response.status >= 500) {
				toasts.error('Something went wrong. Please try again later.');
			} else if (response.status !== 401 && response.status !== 403) {
				toasts.error(parsedError.message);
			}
		}

		throw new ApiClientError(
			response.status,
			parsedError.message,
			undefined,
			parsedError.errorCode,
			parsedError.detail
		);
	}

	const contentType = response.headers.get('content-type');
	if (contentType?.includes('application/json')) {
		return response.json() as Promise<T>;
	}

	const text = await response.text();
	return text as unknown as T;
}

export const api = {
	get<T>(path: string, options?: RequestOptions): Promise<T> {
		return request<T>(path, { ...options, method: 'GET' });
	},

	post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
		return request<T>(path, { ...options, method: 'POST', body });
	},

	patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
		return request<T>(path, { ...options, method: 'PATCH', body });
	},

	put<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
		return request<T>(path, { ...options, method: 'PUT', body });
	},

	delete<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
		return request<T>(path, { ...options, method: 'DELETE', body });
	},

	upload<T>(path: string, formData: FormData, options?: RequestOptions): Promise<T> {
		return request<T>(path, { ...options, method: 'POST', body: formData });
	}
};
