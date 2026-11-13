import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock sessionStorage (for auth store)
vi.stubGlobal('sessionStorage', {
	getItem: vi.fn(() => null),
	setItem: vi.fn(),
	removeItem: vi.fn(),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

// Mock localStorage
const mockStorage: Record<string, string> = {};
vi.stubGlobal('localStorage', {
	getItem: vi.fn((key: string) => mockStorage[key] ?? null),
	setItem: vi.fn((key: string, value: string) => {
		mockStorage[key] = value;
	}),
	removeItem: vi.fn((key: string) => {
		delete mockStorage[key];
	}),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

// Mock settings API
const mockGetSettings = vi.fn();
const mockUpdateSettings = vi.fn();
vi.mock('$api/settings', () => ({
	getSettings: (...args: unknown[]) => mockGetSettings(...args),
	updateSettings: (...args: unknown[]) => mockUpdateSettings(...args)
}));

describe('settings store', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
		mockGetSettings.mockReset();
		mockUpdateSettings.mockReset();
	});

	it('starts closed with default settings', async () => {
		const { settingsOpen, userSettings, settingsLoading } = await import('$stores/settings');
		expect(get(settingsOpen)).toBe(false);
		expect(get(settingsLoading)).toBe(false);
		const s = get(userSettings);
		expect(s.theme).toBe('system');
		expect(s.accent_color).toBe('coral');
	});

	it('openSettings and closeSettings work', async () => {
		const { settingsOpen, openSettings, closeSettings } = await import('$stores/settings');
		openSettings();
		expect(get(settingsOpen)).toBe(true);
		closeSettings();
		expect(get(settingsOpen)).toBe(false);
	});

	it('currentTheme and accentColor are derived', async () => {
		const { userSettings, currentTheme, accentColor } = await import('$stores/settings');
		expect(get(currentTheme)).toBe('system');
		expect(get(accentColor)).toBe('coral');

		userSettings.update((s) => ({ ...s, theme: 'dark', accent_color: 'blue' }));
		expect(get(currentTheme)).toBe('dark');
		expect(get(accentColor)).toBe('blue');
	});

	it('loadSettings fetches from API and caches', async () => {
		const apiSettings = {
			id: '1',
			theme: 'dark',
			accent_color: 'purple',
			custom_instructions: '',
			nickname: '',
			occupation: '',
			about_you: '',
			web_search: true,
			browser: true,
			shell_commands: true,
			complex_reasoning: true,
			computer_use: true,
			notification_email: true,
			notification_push: true,
			notification_marketing: false,
			data_share_analytics: true,
			data_share_training: false,
			backend_url: ''
		};
		mockGetSettings.mockResolvedValue(apiSettings);
		const { userSettings, loadSettings } = await import('$stores/settings');

		await loadSettings();
		expect(get(userSettings).theme).toBe('dark');
		expect(get(userSettings).accent_color).toBe('purple');
		expect(mockStorage['midsphere-settings']).toBeDefined();
	});

	it('loadSettings falls back to cache on error', async () => {
		mockGetSettings.mockRejectedValue(new Error('offline'));
		const { userSettings, loadSettings } = await import('$stores/settings');

		await loadSettings();
		// Should still have defaults
		expect(get(userSettings).theme).toBe('system');
	});

	it('loads cached settings from localStorage on init', async () => {
		mockStorage['midsphere-settings'] = JSON.stringify({
			theme: 'dark',
			accent_color: 'green'
		});
		const { userSettings } = await import('$stores/settings');
		expect(get(userSettings).theme).toBe('dark');
		expect(get(userSettings).accent_color).toBe('green');
	});

	it('applyTheme sets data-theme attribute', async () => {
		const { applyTheme } = await import('$stores/settings');
		applyTheme('dark');
		expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
		applyTheme('light');
		expect(document.documentElement.getAttribute('data-theme')).toBe('');
	});

	it('applyAccentColor is a no-op in monochrome design', async () => {
		const { applyAccentColor } = await import('$stores/settings');
		applyAccentColor('blue');
		// Monochrome design: accent colors are fixed by CSS, not set dynamically
		expect(document.documentElement.style.getPropertyValue('--color-coral')).toBe('');
	});
});
