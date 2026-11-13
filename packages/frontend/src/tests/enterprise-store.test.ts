import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get, writable } from 'svelte/store';
import type { User } from '$api/types';

describe('enterprise store', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	afterEach(() => {
		vi.doUnmock('$stores/auth');
	});

	it('falls back safely when currentUser export is unavailable', async () => {
		vi.doMock('$stores/auth', () => ({
			currentUser: undefined
		}));

		const { enterpriseMode } = await import('$stores/enterprise');
		expect(get(enterpriseMode)).toBe(false);
	});

	it('derives enterprise_mode from currentUser when auth store is available', async () => {
		const currentUser = writable<User | null>(null);
		vi.doMock('$stores/auth', () => ({ currentUser }));

		const { enterpriseMode } = await import('$stores/enterprise');
		expect(get(enterpriseMode)).toBe(false);

		currentUser.set({ enterprise_mode: true } as User);
		expect(get(enterpriseMode)).toBe(true);
	});
});
