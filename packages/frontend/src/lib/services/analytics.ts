import { browser } from '$app/environment';
import { consentPreferences, type ConsentPreferences } from '$stores/consent';

let sentryInitialized = false;
let posthogInitialized = false;

/** Remove all cookies whose name starts with the given prefix. */
function clearCookiesByPrefix(prefix: string): void {
	if (!browser) return;
	const cookies = document.cookie.split(';');
	for (const cookie of cookies) {
		const name = cookie.split('=')[0].trim();
		if (name.startsWith(prefix)) {
			document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/`;
		}
	}
}

async function initSentry(): Promise<void> {
	if (sentryInitialized || !browser) return;

	const dsn = import.meta.env.VITE_SENTRY_DSN;
	if (!dsn) return;

	try {
		const Sentry = await import('@sentry/sveltekit');
		Sentry.init({
			dsn,
			environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || 'development',
			tracesSampleRate: 0.1,
			replaysSessionSampleRate: 0,
			replaysOnErrorSampleRate: 0.5
		});
		sentryInitialized = true;
	} catch {
		// @sentry/sveltekit may fail to resolve in dev; skip silently
	}
}

async function initPostHog(): Promise<void> {
	if (posthogInitialized || !browser) return;

	const apiKey = import.meta.env.VITE_POSTHOG_KEY;
	const apiHost = import.meta.env.VITE_POSTHOG_HOST;
	if (!apiKey) return;

	const { default: posthog } = await import('posthog-js');
	posthog.init(apiKey, {
		api_host: apiHost || 'https://us.i.posthog.com',
		capture_pageview: true,
		capture_pageleave: true,
		persistence: 'localStorage'
	});

	posthogInitialized = true;
}

function teardownPostHog(): void {
	if (!browser) return;
	if (posthogInitialized) {
		import('posthog-js').then(({ default: posthog }) => {
			posthog.opt_out_capturing();
		});
		posthogInitialized = false;
	}
	clearCookiesByPrefix('ph_');
}

function teardownSentry(): void {
	if (!browser) return;
	if (sentryInitialized) {
		import('@sentry/sveltekit')
			.then((Sentry) => {
				const client = Sentry.getClient();
				if (client) {
					client.close();
				}
			})
			.catch(() => {
				// ignore if Sentry failed to load
			});
		sentryInitialized = false;
	}
	clearCookiesByPrefix('sentry-');
}

export function applyConsent(prefs: ConsentPreferences): void {
	if (prefs.errorTracking) {
		initSentry();
	} else {
		teardownSentry();
	}

	if (prefs.analytics) {
		initPostHog();
	} else {
		teardownPostHog();
	}
}

export function initAnalytics(): void {
	if (!browser) return;

	consentPreferences.subscribe((prefs) => {
		applyConsent(prefs);
	});
}
