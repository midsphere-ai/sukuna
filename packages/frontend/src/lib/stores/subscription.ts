import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';
import { getUserSubscription } from '$api/billing';
import { createFreshnessTracker } from '$stores/freshness';
import { debounce } from '$utils/debounce';
import type { UserSubscription } from '$api/types';

const SUBSCRIPTION_CACHE_KEY = 'midsphere-subscription';

function loadCachedSubscription(): UserSubscription | null {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(SUBSCRIPTION_CACHE_KEY);
		if (raw) return JSON.parse(raw) as UserSubscription;
	} catch {
		// ignore
	}
	return null;
}

function cacheSubscription(sub: UserSubscription | null): void {
	if (!browser) return;
	try {
		if (sub) {
			localStorage.setItem(SUBSCRIPTION_CACHE_KEY, JSON.stringify(sub));
		} else {
			localStorage.removeItem(SUBSCRIPTION_CACHE_KEY);
		}
	} catch {
		// ignore
	}
}

export const subscription = writable<UserSubscription | null>(loadCachedSubscription());
export const subscriptionLoading = writable(false);

// Sync to localStorage (debounced)
if (browser) {
	subscription.subscribe(
		debounce((sub: UserSubscription | null) => {
			cacheSubscription(sub);
		}, 500)
	);
}

const subscriptionFreshness = createFreshnessTracker(120_000);

export async function fetchSubscription(): Promise<void> {
	if (!browser) return;

	const isEmpty = get(subscription) === null;
	if (isEmpty) subscriptionLoading.set(true);

	try {
		const sub = await getUserSubscription({ skipErrorHandling: true });
		subscription.set(sub);
		subscriptionFreshness.markFetched();
	} catch {
		// Keep cached value if available
	} finally {
		subscriptionLoading.set(false);
	}
}

/** Ensure subscription is fetched if not fresh (within TTL) */
export function ensureSubscription(): void {
	subscriptionFreshness.ensureFresh(fetchSubscription);
}
