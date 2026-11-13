import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock $app/navigation
const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => mockGoto(...args)
}));

// Mock sessionStorage
vi.stubGlobal('sessionStorage', {
	getItem: vi.fn(() => null),
	setItem: vi.fn(),
	removeItem: vi.fn(),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

// Mock fetch globally
const mockFetch = vi.fn() as Mock;
vi.stubGlobal('fetch', mockFetch);

function jsonResponse(data: unknown, status = 200): Response {
	return new Response(JSON.stringify(data), {
		status,
		headers: { 'Content-Type': 'application/json' }
	});
}

function textResponse(text: string, status = 200): Response {
	return new Response(text, {
		status,
		headers: { 'Content-Type': 'text/plain' }
	});
}

describe('API client', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetch.mockReset();
	});

	it('makes GET requests', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ id: 1, name: 'Test' }));

		const { api } = await import('$api/client');
		const result = await api.get<{ id: number; name: string }>('/test');

		expect(mockFetch).toHaveBeenCalledTimes(1);
		const [url, options] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/v1/test');
		expect(options.method).toBe('GET');
		expect(result).toEqual({ id: 1, name: 'Test' });
	});

	it('makes POST requests with JSON body', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ success: true }));

		const { api } = await import('$api/client');
		await api.post('/test', { foo: 'bar' });

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('POST');
		expect(options.body).toBe(JSON.stringify({ foo: 'bar' }));
		expect(options.headers.get('Content-Type')).toBe('application/json');
	});

	it('injects Authorization header when token is set', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token-123');
		mockFetch.mockResolvedValueOnce(jsonResponse({}));

		const { api } = await import('$api/client');
		await api.get('/protected');

		const [, options] = mockFetch.mock.calls[0];
		expect(options.headers.get('Authorization')).toBe('Bearer test-token-123');
	});

	it('skips auth header when skipAuth is true', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token-123');
		mockFetch.mockResolvedValueOnce(jsonResponse({}));

		const { api } = await import('$api/client');
		await api.get('/public', { skipAuth: true });

		const [, options] = mockFetch.mock.calls[0];
		expect(options.headers.get('Authorization')).toBeNull();
	});

	it('handles 401 by clearing auth and redirecting to login', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('expired-token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token.' }, 401));

		const { api, ApiClientError } = await import('$api/client');
		await expect(api.get('/protected')).rejects.toThrow(ApiClientError);

		expect(get(authToken)).toBeNull();
		expect(mockGoto).toHaveBeenCalledWith('/login');
	});

	it('handles 403 by clearing auth and redirecting', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('test-token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Forbidden' }, 403));

		const { api, ApiClientError } = await import('$api/client');
		await expect(api.get('/admin')).rejects.toThrow(ApiClientError);

		expect(get(authToken)).toBeNull();
		expect(mockGoto).toHaveBeenCalledWith('/login');
	});

	it('shows toast on 500 errors', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Server error' }, 500));

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api, ApiClientError } = await import('$api/client');

		await expect(api.get('/broken')).rejects.toThrow(ApiClientError);
		expect(errorSpy).toHaveBeenCalledWith('Something went wrong. Please try again later.');
	});

	it('shows toast on network errors', async () => {
		vi.resetModules();
		mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api, ApiClientError } = await import('$api/client');

		await expect(api.get('/offline')).rejects.toThrow(ApiClientError);
		expect(errorSpy).toHaveBeenCalledWith('Network error. Please check your connection.');
	});

	it('skips error handling when skipErrorHandling is true', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Not found' }, 404));

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api, ApiClientError } = await import('$api/client');

		await expect(api.get('/missing', { skipErrorHandling: true })).rejects.toThrow(ApiClientError);
		expect(errorSpy).not.toHaveBeenCalled();
	});

	it('handles text responses', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(textResponse('Success'));

		const { api } = await import('$api/client');
		const result = await api.post<string>('/test');

		expect(result).toBe('Success');
	});

	it('makes PATCH requests', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ updated: true }));

		const { api } = await import('$api/client');
		await api.patch('/update', { name: 'New' });

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('PATCH');
	});

	it('makes DELETE requests', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ deleted: true }));

		const { api } = await import('$api/client');
		await api.delete('/remove');

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('DELETE');
	});

	it('ApiClientError includes status and data', async () => {
		vi.resetModules();
		const { ApiClientError } = await import('$api/client');
		const err = new ApiClientError(404, 'Not Found', { detail: 'missing' });

		expect(err.status).toBe(404);
		expect(err.message).toBe('Not Found');
		expect(err.data).toEqual({ detail: 'missing' });
		expect(err.errorCode).toBeNull();
		expect(err.detail).toBeNull();
		expect(err.toApiError()).toEqual({
			status: 404,
			message: 'Not Found',
			errorCode: null,
			detail: null,
			data: { detail: 'missing' }
		});
	});

	it('ApiClientError carries error_code and detail from standardised error envelope', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(
			jsonResponse(
				{
					error: 'Addon limit exceeded',
					error_code: 'AGENT_LIMIT_EXCEEDED',
					detail: { max_allowed: 5 },
					status: 403
				},
				403
			)
		);

		const { api, ApiClientError } = await import('$api/client');
		try {
			await api.post('/addons', {}, { skipErrorHandling: true });
			expect.fail('Should have thrown');
		} catch (e) {
			expect(e).toBeInstanceOf(ApiClientError);
			const err = e as InstanceType<typeof ApiClientError>;
			expect(err.status).toBe(403);
			expect(err.message).toBe('Addon limit exceeded');
			expect(err.errorCode).toBe('AGENT_LIMIT_EXCEEDED');
			expect(err.detail).toEqual({ max_allowed: 5 });
		}
	});

	it('shows specific error message on 4xx (non-401/403)', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Bad request data' }, 400));

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api, ApiClientError } = await import('$api/client');

		await expect(api.post('/bad', {})).rejects.toThrow(ApiClientError);
		expect(errorSpy).toHaveBeenCalledWith('Bad request data');
	});

	it('handles upload with FormData', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('upload-token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ file_id: '123' }));

		const { api } = await import('$api/client');
		const formData = new FormData();
		formData.append('file', new Blob(['test']), 'test.txt');

		const result = await api.upload<{ file_id: string }>('/memory/files', formData);

		expect(result).toEqual({ file_id: '123' });
		const [url, options] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/v1/memory/files');
		expect(options.headers.get('Authorization')).toBe('Bearer upload-token');
		// Should NOT set Content-Type for FormData (browser handles it)
		expect(options.headers.get('Content-Type')).toBeNull();
	});

	it('uses full URL when path starts with http', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({}));

		const { api } = await import('$api/client');
		await api.get('https://sandbox.e2b.dev/runs/123');

		const [url] = mockFetch.mock.calls[0];
		expect(url).toBe('https://sandbox.e2b.dev/runs/123');
	});

	it('parses error with non_field_errors array', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(
			jsonResponse({ non_field_errors: ['Unable to log in with provided credentials.'] }, 400)
		);

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api } = await import('$api/client');

		await expect(api.post('/login', {})).rejects.toThrow();
		expect(errorSpy).toHaveBeenCalledWith('Unable to log in with provided credentials.');
	});
});
