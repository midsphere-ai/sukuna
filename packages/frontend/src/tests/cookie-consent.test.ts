import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import CookieConsent from '$components/ui/CookieConsent.svelte';
import { hasConsented, consentPreferences } from '$stores/consent';

// Mock localStorage for jsdom
const localStorageMock = (() => {
	let store: Record<string, string> = {};
	return {
		getItem: vi.fn((key: string) => store[key] ?? null),
		setItem: vi.fn((key: string, value: string) => {
			store[key] = value;
		}),
		removeItem: vi.fn((key: string) => {
			delete store[key];
		}),
		clear: vi.fn(() => {
			store = {};
		}),
		get length() {
			return Object.keys(store).length;
		},
		key: vi.fn((index: number) => Object.keys(store)[index] ?? null)
	};
})();

vi.stubGlobal('localStorage', localStorageMock);

// Polyfill dialog methods for jsdom
beforeEach(() => {
	HTMLDialogElement.prototype.showModal = function () {
		this.setAttribute('open', '');
	};
	HTMLDialogElement.prototype.close = function () {
		this.removeAttribute('open');
	};
});

// Helper to reset consent state
function resetConsent(): void {
	hasConsented.set(false);
	consentPreferences.set({
		essential: true,
		analytics: false,
		errorTracking: false
	});
	localStorageMock.clear();
}

describe('CookieConsent banner', () => {
	beforeEach(() => {
		resetConsent();
	});

	it('shows banner when user has not consented', () => {
		render(CookieConsent);
		expect(screen.getByRole('region', { name: /cookie consent/i })).toBeInTheDocument();
	});

	it('shows Accept All, Reject, and Customize buttons', () => {
		render(CookieConsent);
		expect(screen.getByText('Accept All')).toBeInTheDocument();
		expect(screen.getByText('Reject')).toBeInTheDocument();
		expect(screen.getByText('Customize')).toBeInTheDocument();
	});

	it('hides banner when user has already consented', () => {
		hasConsented.set(true);
		render(CookieConsent);
		expect(screen.queryByRole('region', { name: /cookie consent/i })).not.toBeInTheDocument();
	});

	it('hides banner and accepts all on Accept All click', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Accept All'));

		expect(screen.queryByRole('region', { name: /cookie consent/i })).not.toBeInTheDocument();
		expect(get(hasConsented)).toBe(true);
		const prefs = get(consentPreferences);
		expect(prefs.analytics).toBe(true);
		expect(prefs.errorTracking).toBe(true);
		expect(prefs.essential).toBe(true);
	});

	it('hides banner and rejects non-essential on Reject click', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Reject'));

		expect(screen.queryByRole('region', { name: /cookie consent/i })).not.toBeInTheDocument();
		expect(get(hasConsented)).toBe(true);
		const prefs = get(consentPreferences);
		expect(prefs.analytics).toBe(false);
		expect(prefs.errorTracking).toBe(false);
		expect(prefs.essential).toBe(true);
	});

	it('persists consent to localStorage on Accept All', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Accept All'));

		expect(localStorageMock.setItem).toHaveBeenCalledWith(
			'midsphere-cookie-consent',
			expect.stringContaining('"analytics":true')
		);
	});

	it('persists consent to localStorage on Reject', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Reject'));

		expect(localStorageMock.setItem).toHaveBeenCalledWith(
			'midsphere-cookie-consent',
			expect.stringContaining('"analytics":false')
		);
	});
});

describe('CookieConsent customize dialog', () => {
	beforeEach(() => {
		resetConsent();
	});

	it('opens customize dialog on Customize click', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Customize'));

		expect(screen.getByText('Cookie settings')).toBeInTheDocument();
		expect(screen.getByText('Essential')).toBeInTheDocument();
		expect(screen.getByText('Analytics')).toBeInTheDocument();
		expect(screen.getByText('Error Tracking')).toBeInTheDocument();
	});

	it('shows Essential toggle as disabled and checked', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Customize'));

		const toggles = screen.getAllByRole('switch');
		// First toggle is Essential — should be disabled
		expect(toggles[0]).toBeDisabled();
		expect(toggles[0]).toBeChecked();
	});

	it('saves custom preferences and hides banner', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Customize'));

		// Toggle analytics on
		const toggles = screen.getAllByRole('switch');
		await fireEvent.click(toggles[1]); // Analytics toggle

		await fireEvent.click(screen.getByText('Save preferences'));

		expect(screen.queryByRole('region', { name: /cookie consent/i })).not.toBeInTheDocument();
		expect(get(hasConsented)).toBe(true);
		const prefs = get(consentPreferences);
		expect(prefs.analytics).toBe(true);
		expect(prefs.errorTracking).toBe(false);
	});

	it('closes customize dialog on Cancel without saving', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Customize'));
		await fireEvent.click(screen.getByText('Cancel'));

		// Banner should still be visible
		expect(screen.getByRole('region', { name: /cookie consent/i })).toBeInTheDocument();
		expect(get(hasConsented)).toBe(false);
	});

	it('persists custom preferences to localStorage', async () => {
		render(CookieConsent);
		await fireEvent.click(screen.getByText('Customize'));

		// Toggle error tracking on
		const toggles = screen.getAllByRole('switch');
		await fireEvent.click(toggles[2]); // Error Tracking toggle

		await fireEvent.click(screen.getByText('Save preferences'));

		expect(localStorageMock.setItem).toHaveBeenCalledWith(
			'midsphere-cookie-consent',
			expect.stringContaining('"errorTracking":true')
		);
	});
});
