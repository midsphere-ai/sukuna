import { browser } from '$app/environment';

export function createFreshnessTracker(ttlMs = 60_000) {
	let lastFetchedAt = 0;
	let inFlight: Promise<void> | null = null;

	return {
		isFresh: () => Date.now() - lastFetchedAt < ttlMs,
		invalidate: () => {
			lastFetchedAt = 0;
		},
		markFetched: () => {
			lastFetchedAt = Date.now();
		},
		ensureFresh(fetchFn: () => Promise<void>): Promise<void> {
			if (Date.now() - lastFetchedAt < ttlMs) return Promise.resolve();
			if (inFlight) return inFlight;
			inFlight = fetchFn().finally(() => {
				inFlight = null;
				lastFetchedAt = Date.now();
			});
			return inFlight;
		}
	};
}

const SESSION_PREFIX = 'midsphere-freshness-';

export function isSessionFresh(key: string, ttlMs: number): boolean {
	if (!browser) return false;
	try {
		const raw = sessionStorage.getItem(SESSION_PREFIX + key);
		if (!raw) return false;
		return Date.now() - Number(raw) < ttlMs;
	} catch {
		return false;
	}
}

export function markSessionFetched(key: string): void {
	if (!browser) return;
	try {
		sessionStorage.setItem(SESSION_PREFIX + key, String(Date.now()));
	} catch {
		// ignore
	}
}
