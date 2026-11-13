import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';
import type { UserSettings, UserSettingsUpdate } from '$api/types';
import { getSettings, updateSettings } from '$api/settings';
import { toasts } from '$stores/toast';

const THEME_KEY = 'midsphere-theme';
const SETTINGS_KEY = 'midsphere-settings';

// --- Settings dialog state ---

export const settingsOpen = writable<boolean>(false);

export function openSettings(): void {
	settingsOpen.set(true);
}

export function closeSettings(): void {
	settingsOpen.set(false);
}

// --- Settings data ---

const defaultSettings: UserSettings = {
	id: '',
	theme: 'system',
	accent_color: 'coral',
	custom_instructions: '',
	nickname: '',
	occupation: '',
	about_you: '',
	onboarding_completed: null,
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
	backend_url: '',
	local_mode: false,
	local_sandbox_url: ''
};

function loadCachedSettings(): UserSettings {
	if (!browser) return defaultSettings;
	try {
		const stored = localStorage.getItem(SETTINGS_KEY);
		if (stored) {
			return { ...defaultSettings, ...JSON.parse(stored) };
		}
	} catch {
		// ignore
	}
	return defaultSettings;
}

function cacheSettings(settings: UserSettings): void {
	if (!browser) return;
	try {
		localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
	} catch {
		// ignore
	}
}

export const userSettings = writable<UserSettings>(loadCachedSettings());
export const settingsLoading = writable<boolean>(false);

export const currentTheme = derived(userSettings, ($s) => $s.theme);
export const accentColor = derived(userSettings, ($s) => $s.accent_color);

// --- Theme application ---

function getSystemTheme(): 'light' | 'dark' {
	if (!browser) return 'light';
	return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function applyTheme(theme: string): void {
	if (!browser) return;
	const resolved = theme === 'system' ? getSystemTheme() : theme;
	document.documentElement.setAttribute('data-theme', resolved === 'dark' ? 'dark' : '');

	try {
		localStorage.setItem(THEME_KEY, theme);
	} catch {
		// ignore
	}
}

// --- Accent color application ---
// Monochrome design: accent colors are fixed by the CSS theme (--ms-coral, --ms-blue, --ms-green).
// This function is preserved for API compatibility but is a no-op.

export function applyAccentColor(_color: string): void {
	void _color;
	// No-op: monochrome design has no user-selectable accent colors.
}

// Listen for system theme changes when user has "system" selected
if (browser) {
	window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
		const stored = localStorage.getItem(THEME_KEY);
		if (stored === 'system' || !stored) {
			applyTheme('system');
		}
	});

	// Apply theme on initial load from localStorage (before backend settings load)
	const savedTheme = localStorage.getItem(THEME_KEY);
	if (savedTheme) {
		applyTheme(savedTheme);
	}
}

// --- Backend sync ---

export async function loadSettings(): Promise<void> {
	settingsLoading.set(true);
	try {
		const settings = await getSettings();
		userSettings.set(settings);
		cacheSettings(settings);
		applyTheme(settings.theme);
		applyAccentColor(settings.accent_color);
	} catch {
		// Use cached/defaults on failure
	} finally {
		settingsLoading.set(false);
	}
}

let saveTimeout: ReturnType<typeof setTimeout> | undefined;

async function persistSettings(updates: UserSettingsUpdate): Promise<void> {
	const result = await updateSettings(updates);
	userSettings.set(result);
	cacheSettings(result);
}

export async function saveSettings(updates: UserSettingsUpdate): Promise<void> {
	// Optimistically update local state
	userSettings.update((current) => {
		const updated = { ...current, ...updates };
		cacheSettings(updated);
		return updated;
	});

	// Apply theme immediately if changed
	if (updates.theme !== undefined) {
		applyTheme(updates.theme);
	}

	// Apply accent color immediately if changed
	if (updates.accent_color !== undefined) {
		applyAccentColor(updates.accent_color);
	}

	// Debounce backend save
	if (saveTimeout) clearTimeout(saveTimeout);
	saveTimeout = setTimeout(async () => {
		try {
			await persistSettings(updates);
		} catch {
			toasts.error('Failed to save settings.');
		}
	}, 500);
}

export async function saveSettingsImmediately(updates: UserSettingsUpdate): Promise<void> {
	// Optimistically update local state
	userSettings.update((current) => {
		const updated = { ...current, ...updates };
		cacheSettings(updated);
		return updated;
	});

	// Apply theme/accent immediately if changed
	if (updates.theme !== undefined) applyTheme(updates.theme);
	if (updates.accent_color !== undefined) applyAccentColor(updates.accent_color);

	if (saveTimeout) {
		clearTimeout(saveTimeout);
		saveTimeout = undefined;
	}

	try {
		await persistSettings(updates);
	} catch {
		toasts.error('Failed to save settings.');
		throw new Error('Failed to save settings');
	}
}
