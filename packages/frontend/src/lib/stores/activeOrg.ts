import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';
import { getActiveOrg, switchOrg } from '$api/organizations';
import type { ActiveOrg } from '$api/organizations';

const ACTIVE_ORG_KEY = 'midsphere-active-org';

function loadCached(): ActiveOrg | null {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(ACTIVE_ORG_KEY);
		if (raw) return JSON.parse(raw) as ActiveOrg;
	} catch {
		// ignore
	}
	return null;
}

function cacheActiveOrg(org: ActiveOrg | null): void {
	if (!browser) return;
	try {
		if (org) {
			localStorage.setItem(ACTIVE_ORG_KEY, JSON.stringify(org));
		} else {
			localStorage.removeItem(ACTIVE_ORG_KEY);
		}
	} catch {
		// ignore
	}
}

export const activeOrg = writable<ActiveOrg | null>(loadCached());
export const activeOrgLoading = writable(false);

// Sync to localStorage
if (browser) {
	activeOrg.subscribe((org) => {
		cacheActiveOrg(org);
	});
}

export async function fetchActiveOrg(): Promise<void> {
	if (!browser) return;
	activeOrgLoading.set(true);
	try {
		const result = await getActiveOrg();
		if (result.organization_id) {
			activeOrg.set(result);
		} else {
			activeOrg.set(null);
		}
	} catch {
		activeOrg.set(null);
	} finally {
		activeOrgLoading.set(false);
	}
}

export async function setActiveOrg(organizationId: string | null): Promise<void> {
	activeOrgLoading.set(true);
	try {
		const result = await switchOrg(organizationId);
		if (result.organization_id) {
			activeOrg.set(result);
		} else {
			activeOrg.set(null);
		}
	} catch {
		// Keep current state on error
	} finally {
		activeOrgLoading.set(false);
	}
}
