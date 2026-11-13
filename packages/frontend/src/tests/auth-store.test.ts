import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock sessionStorage
const mockSessionStorage: Record<string, string> = {};
vi.stubGlobal('sessionStorage', {
	getItem: vi.fn((key: string) => mockSessionStorage[key] ?? null),
	setItem: vi.fn((key: string, value: string) => {
		mockSessionStorage[key] = value;
	}),
	removeItem: vi.fn((key: string) => {
		delete mockSessionStorage[key];
	}),
	clear: vi.fn(() => {
		Object.keys(mockSessionStorage).forEach((key) => delete mockSessionStorage[key]);
	}),
	length: 0,
	key: vi.fn()
});

describe('auth store', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		Object.keys(mockSessionStorage).forEach((key) => delete mockSessionStorage[key]);
	});

	it('starts with null token and no user', async () => {
		// Re-import to reset module state
		vi.resetModules();
		const { authToken, currentUser, authLoading } = await import('$stores/auth');
		expect(get(authToken)).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authLoading)).toBe(true);
	});

	it('isAuthenticated is derived from token', async () => {
		vi.resetModules();
		const { authToken, isAuthenticated } = await import('$stores/auth');
		expect(get(isAuthenticated)).toBe(false);

		authToken.set('test-token');
		expect(get(isAuthenticated)).toBe(true);

		authToken.set(null);
		expect(get(isAuthenticated)).toBe(false);
	});

	it('setAuth sets token and user', async () => {
		vi.resetModules();
		const { setAuth, authToken, currentUser } = await import('$stores/auth');
		const user = {
			id: '123',
			name: 'Test User',
			email: 'test@test.com',
			avatar: '',
			is_active: true,
			date_joined: '2026-01-01T00:00:00Z',
			last_login: null,
			enterprise_mode: false
		};

		setAuth('my-token', user);
		expect(get(authToken)).toBe('my-token');
		expect(get(currentUser)).toEqual(user);
	});

	it('setAuth works without user', async () => {
		vi.resetModules();
		const { setAuth, authToken, currentUser } = await import('$stores/auth');

		setAuth('my-token');
		expect(get(authToken)).toBe('my-token');
		expect(get(currentUser)).toBeNull();
	});

	it('clearAuth clears everything', async () => {
		vi.resetModules();
		const { setAuth, clearAuth, authToken, currentUser, authLoading } =
			await import('$stores/auth');

		setAuth('token', {
			id: '1',
			name: 'Test',
			email: 'a@b.com',
			avatar: '',
			is_active: true,
			date_joined: '',
			last_login: null,
			enterprise_mode: false
		});
		clearAuth();

		expect(get(authToken)).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authLoading)).toBe(false);
	});

	it('persists token to sessionStorage via setAuth', async () => {
		vi.resetModules();
		const { setAuth } = await import('$stores/auth');

		setAuth('persisted-token');
		expect(mockSessionStorage['midsphere-auth-token']).toBe('persisted-token');
	});

	it('removes token from sessionStorage on clearAuth', async () => {
		vi.resetModules();
		mockSessionStorage['midsphere-auth-token'] = 'old-token';
		const { clearAuth } = await import('$stores/auth');

		clearAuth();
		expect(mockSessionStorage['midsphere-auth-token']).toBeUndefined();
	});

	it('loads token from sessionStorage on init', async () => {
		mockSessionStorage['midsphere-auth-token'] = 'existing-token';
		vi.resetModules();
		const { authToken } = await import('$stores/auth');

		expect(get(authToken)).toBe('existing-token');
	});
});
