import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';
import { getCreditBalance } from '$api/billing';
import { createFreshnessTracker } from '$stores/freshness';
import { debounce } from '$utils/debounce';
import type { CreditBalance } from '$api/types';

const CREDIT_CACHE_KEY = 'midsphere-credit-balance';

function loadCachedBalance(): CreditBalance | null {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(CREDIT_CACHE_KEY);
		if (raw) return JSON.parse(raw) as CreditBalance;
	} catch {
		// ignore
	}
	return null;
}

function cacheBalance(bal: CreditBalance | null): void {
	if (!browser) return;
	try {
		if (bal) {
			localStorage.setItem(CREDIT_CACHE_KEY, JSON.stringify(bal));
		} else {
			localStorage.removeItem(CREDIT_CACHE_KEY);
		}
	} catch {
		// ignore
	}
}

export const creditBalance = writable<CreditBalance | null>(loadCachedBalance());
export const creditBalanceLoading = writable(false);

// Sync to localStorage (debounced)
if (browser) {
	creditBalance.subscribe(
		debounce((bal: CreditBalance | null) => {
			cacheBalance(bal);
		}, 500)
	);
}

const creditFreshness = createFreshnessTracker(60_000);

export async function fetchCreditBalance(): Promise<void> {
	if (!browser) return;

	const isEmpty = get(creditBalance) === null;
	if (isEmpty) creditBalanceLoading.set(true);

	try {
		const bal = await getCreditBalance();
		creditBalance.set(bal);
		creditFreshness.markFetched();
	} catch {
		// Keep cached value if available
	} finally {
		creditBalanceLoading.set(false);
	}
}

/** Ensure credit balance is fetched if not fresh (within TTL) */
export function ensureCreditBalance(): void {
	creditFreshness.ensureFresh(fetchCreditBalance);
}

/** Invalidate cached balance (e.g. after purchase or task completion) */
export function invalidateCreditBalance(): void {
	creditFreshness.invalidate();
}
