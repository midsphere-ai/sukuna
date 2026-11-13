import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

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

describe('consent store', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	});

	it('starts with defaults when no stored consent', async () => {
		const { consentPreferences, hasConsented } = await import('$stores/consent');
		expect(get(consentPreferences)).toEqual({
			essential: true,
			analytics: false,
			errorTracking: false
		});
		expect(get(hasConsented)).toBe(false);
	});

	it('loads stored consent from localStorage', async () => {
		const prefs = { essential: true, analytics: true, errorTracking: false };
		mockStorage['midsphere-cookie-consent'] = JSON.stringify(prefs);
		const { consentPreferences, hasConsented } = await import('$stores/consent');
		expect(get(consentPreferences)).toEqual(prefs);
		expect(get(hasConsented)).toBe(true);
	});

	it('acceptAll enables all and persists', async () => {
		const { consentPreferences, hasConsented, acceptAll } = await import('$stores/consent');
		acceptAll();
		expect(get(consentPreferences)).toEqual({
			essential: true,
			analytics: true,
			errorTracking: true
		});
		expect(get(hasConsented)).toBe(true);
		const stored = JSON.parse(mockStorage['midsphere-cookie-consent']);
		expect(stored.analytics).toBe(true);
		expect(stored.errorTracking).toBe(true);
	});

	it('rejectNonEssential keeps only essential', async () => {
		const { consentPreferences, hasConsented, rejectNonEssential } =
			await import('$stores/consent');
		rejectNonEssential();
		expect(get(consentPreferences)).toEqual({
			essential: true,
			analytics: false,
			errorTracking: false
		});
		expect(get(hasConsented)).toBe(true);
	});

	it('reopenConsentBanner sets hasConsented to false', async () => {
		const { hasConsented, acceptAll, reopenConsentBanner } = await import('$stores/consent');
		acceptAll();
		expect(get(hasConsented)).toBe(true);
		reopenConsentBanner();
		expect(get(hasConsented)).toBe(false);
	});

	it('updateConsent allows partial updates', async () => {
		const { consentPreferences, updateConsent } = await import('$stores/consent');
		updateConsent({ analytics: true });
		expect(get(consentPreferences)).toEqual({
			essential: true,
			analytics: true,
			errorTracking: false
		});
	});

	it('updateConsent always forces essential to true', async () => {
		const { consentPreferences, updateConsent } = await import('$stores/consent');
		updateConsent({ analytics: false, errorTracking: true });
		const prefs = get(consentPreferences);
		expect(prefs.essential).toBe(true);
		expect(prefs.errorTracking).toBe(true);
	});
});
