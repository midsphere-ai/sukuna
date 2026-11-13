import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export interface ConsentPreferences {
	essential: boolean; // Always true
	analytics: boolean; // PostHog
	errorTracking: boolean; // Sentry
}

const CONSENT_KEY = 'midsphere-cookie-consent';

function loadConsent(): ConsentPreferences | null {
	if (!browser) return null;
	try {
		const stored = localStorage.getItem(CONSENT_KEY);
		if (!stored) return null;
		return JSON.parse(stored) as ConsentPreferences;
	} catch {
		return null;
	}
}

function saveConsent(prefs: ConsentPreferences): void {
	if (!browser) return;
	try {
		localStorage.setItem(CONSENT_KEY, JSON.stringify(prefs));
	} catch {
		// localStorage may be unavailable (private browsing, tests)
	}
}

const defaultPreferences: ConsentPreferences = {
	essential: true,
	analytics: false,
	errorTracking: false
};

const stored = loadConsent();

export const consentPreferences = writable<ConsentPreferences>(stored ?? defaultPreferences);

export const hasConsented = writable<boolean>(stored !== null);

export function acceptAll(): void {
	const prefs: ConsentPreferences = {
		essential: true,
		analytics: true,
		errorTracking: true
	};
	saveConsent(prefs);
	consentPreferences.set(prefs);
	hasConsented.set(true);
}

export function rejectNonEssential(): void {
	const prefs: ConsentPreferences = {
		essential: true,
		analytics: false,
		errorTracking: false
	};
	saveConsent(prefs);
	consentPreferences.set(prefs);
	hasConsented.set(true);
}

/** Show the consent banner again so the user can change preferences. */
export function reopenConsentBanner(): void {
	hasConsented.set(false);
}

export function updateConsent(prefs: Partial<ConsentPreferences>): void {
	const updated: ConsentPreferences = {
		essential: true,
		analytics: prefs.analytics ?? false,
		errorTracking: prefs.errorTracking ?? false
	};
	saveConsent(updated);
	consentPreferences.set(updated);
	hasConsented.set(true);
}
