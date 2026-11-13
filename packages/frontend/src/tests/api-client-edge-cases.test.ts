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

describe('API client - error parsing edge cases', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetch.mockReset();
	});

	it('parses error with message field', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ message: 'Validation failed' }, 422));

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api } = await import('$api/client');

		await expect(api.post('/validate', {})).rejects.toThrow();
		expect(errorSpy).toHaveBeenCalledWith('Validation failed');
	});

	it('parses error when body is a plain string', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(
			new Response(JSON.stringify('Unexpected error'), {
				status: 400,
				headers: { 'Content-Type': 'application/json' }
			})
		);

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api } = await import('$api/client');

		await expect(api.post('/test', {})).rejects.toThrow();
		expect(errorSpy).toHaveBeenCalledWith('Unexpected error');
	});

	it('falls back to JSON.stringify when no known fields', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ code: 'ERR_001', info: 'Something' }, 400));

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api } = await import('$api/client');

		await expect(api.post('/test', {})).rejects.toThrow();
		expect(errorSpy).toHaveBeenCalledWith(JSON.stringify({ code: 'ERR_001', info: 'Something' }));
	});

	it('falls back to text when JSON parsing fails', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(
			new Response('Not JSON at all', {
				status: 500,
				headers: { 'Content-Type': 'text/plain' }
			})
		);

		const { toasts } = await import('$stores/toast');
		const errorSpy = vi.spyOn(toasts, 'error');
		const { api } = await import('$api/client');

		await expect(api.get('/broken')).rejects.toThrow();
		// 500 errors show generic message, not the parsed error
		expect(errorSpy).toHaveBeenCalledWith('Something went wrong. Please try again later.');
	});

	it('sets Content-Type for POST with body', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));

		const { api } = await import('$api/client');
		await api.post('/data', { key: 'value' });

		const [, options] = mockFetch.mock.calls[0];
		expect(options.headers.get('Content-Type')).toBe('application/json');
	});

	it('does not set Content-Type when no body', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));

		const { api } = await import('$api/client');
		await api.post('/action');

		const [, options] = mockFetch.mock.calls[0];
		expect(options.headers.get('Content-Type')).toBeNull();
	});
});

describe('API client - PUT method', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetch.mockReset();
	});

	it('makes PUT requests with body', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ updated: true }));

		const { api } = await import('$api/client');
		await api.put('/resource/1', { name: 'Updated' });

		const [url, options] = mockFetch.mock.calls[0];
		expect(url).toBe('/api/v1/resource/1');
		expect(options.method).toBe('PUT');
		expect(options.body).toBe(JSON.stringify({ name: 'Updated' }));
	});
});

describe('API client - upload error handling', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetch.mockReset();
	});

	it('handles 401 on upload by clearing auth and redirecting', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('upload-token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid token' }, 401));

		const { api, ApiClientError } = await import('$api/client');
		const formData = new FormData();
		formData.append('file', new Blob(['data']), 'test.txt');

		await expect(api.upload('/memory/files', formData)).rejects.toThrow(ApiClientError);
		expect(get(authToken)).toBeNull();
		expect(mockGoto).toHaveBeenCalledWith('/login');
	});

	it('throws ApiClientError with status on upload failure', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'File too large' }, 413));

		const { api, ApiClientError } = await import('$api/client');
		const formData = new FormData();
		formData.append('file', new Blob(['data']), 'big.zip');

		try {
			await api.upload('/memory/files', formData);
			expect.fail('Should have thrown');
		} catch (e) {
			expect(e).toBeInstanceOf(ApiClientError);
			expect((e as InstanceType<typeof ApiClientError>).status).toBe(413);
			expect((e as InstanceType<typeof ApiClientError>).message).toBe('File too large');
		}
	});

	it('upload uses full URL when path starts with http', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ uploaded: true }));

		const { api } = await import('$api/client');
		const formData = new FormData();
		formData.append('file', new Blob(['data']), 'test.txt');

		await api.upload('https://sandbox.e2b.dev/uploads', formData);

		const [url] = mockFetch.mock.calls[0];
		expect(url).toBe('https://sandbox.e2b.dev/uploads');
	});
});

describe('API client - DELETE with body', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetch.mockReset();
	});

	it('makes DELETE request with JSON body', async () => {
		vi.resetModules();
		mockFetch.mockResolvedValueOnce(jsonResponse({ deleted: true }));

		const { api } = await import('$api/client');
		await api.delete('/items', { ids: [1, 2, 3] });

		const [, options] = mockFetch.mock.calls[0];
		expect(options.method).toBe('DELETE');
		expect(options.body).toBe(JSON.stringify({ ids: [1, 2, 3] }));
	});
});

describe('API client - auth header behavior', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetch.mockReset();
	});

	it('does not include Authorization header when no token is set', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set(null);
		mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));

		const { api } = await import('$api/client');
		await api.get('/public-endpoint');

		const [, options] = mockFetch.mock.calls[0];
		expect(options.headers.get('Authorization')).toBeNull();
	});

	it('does not clear auth on 401 when no token was sent', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set(null);
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Auth required' }, 401));

		const { api } = await import('$api/client');
		// This should NOT redirect to login since we didn't have a token
		await expect(api.get('/protected')).rejects.toThrow();
		expect(mockGoto).not.toHaveBeenCalled();
	});

	it('does not clear auth on 401 when skipAuth is true', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('valid-token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Unauthorized' }, 401));

		const { api } = await import('$api/client');
		await expect(api.get('/endpoint', { skipAuth: true })).rejects.toThrow();
		// Token should still be set because skipAuth skips the auth clearing logic
		expect(get(authToken)).toBe('valid-token');
		expect(mockGoto).not.toHaveBeenCalled();
	});

	it('ApiClientError has correct message for 401', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Invalid' }, 401));

		const { api } = await import('$api/client');
		try {
			await api.get('/protected');
			expect.fail('Should have thrown');
		} catch (e) {
			expect((e as Error).message).toBe('Session expired. Please log in again.');
		}
	});

	it('ApiClientError has correct message for 403', async () => {
		vi.resetModules();
		const { authToken } = await import('$stores/auth');
		authToken.set('token');
		mockFetch.mockResolvedValueOnce(jsonResponse({ detail: 'Forbidden' }, 403));

		const { api } = await import('$api/client');
		try {
			await api.get('/admin');
			expect.fail('Should have thrown');
		} catch (e) {
			expect((e as Error).message).toBe('Access denied.');
		}
	});
});
