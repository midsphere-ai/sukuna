import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const ONBOARDING_KEY = 'midsphere-onboarding-complete';

function loadOnboardingState(): boolean {
	if (!browser) return false;
	try {
		return localStorage.getItem(ONBOARDING_KEY) === 'true';
	} catch {
		return false;
	}
}

export const onboardingComplete = writable<boolean>(loadOnboardingState());

export function markOnboardingComplete(): void {
	onboardingComplete.set(true);
	if (!browser) return;
	try {
		localStorage.setItem(ONBOARDING_KEY, 'true');
	} catch {
		// localStorage may be unavailable
	}
}

export function resetOnboarding(): void {
	onboardingComplete.set(false);
	if (!browser) return;
	try {
		localStorage.removeItem(ONBOARDING_KEY);
	} catch {
		// localStorage may be unavailable
	}
}
