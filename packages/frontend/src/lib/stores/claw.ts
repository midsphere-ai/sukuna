import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import {
	getClawStatus,
	getClawConversations,
	activateClawSandbox,
	deactivateClawSandbox
} from '$api/claw';
import type { ClawStatus, ClawConversation } from '$api/claw';

export const clawStatus = writable<ClawStatus | null>(null);
export const clawConversations = writable<ClawConversation[]>([]);
export const clawActivating = writable(false);

let pollTimer: ReturnType<typeof setInterval> | null = null;

export async function fetchClawStatus(): Promise<void> {
	if (!browser) return;
	try {
		const status = await getClawStatus();
		clawStatus.set(status);
	} catch {
		// Silently fail — endpoint may not be available
	}
}

export async function fetchClawConversations(): Promise<void> {
	if (!browser) return;
	try {
		const conversations = await getClawConversations();
		clawConversations.set(conversations);
	} catch {
		// Silently fail
	}
}

export async function activateClaw(): Promise<boolean> {
	clawActivating.set(true);
	try {
		const result = await activateClawSandbox();
		clawStatus.update((s) =>
			s ? { ...s, active: result.active, sandbox_id: result.sandbox_id } : s
		);
		await fetchClawStatus();
		return true;
	} catch {
		return false;
	} finally {
		clawActivating.set(false);
	}
}

export async function deactivateClaw(): Promise<boolean> {
	try {
		await deactivateClawSandbox();
		clawStatus.update((s) => (s ? { ...s, active: false, sandbox_id: null } : s));
		await fetchClawStatus();
		return true;
	} catch {
		return false;
	}
}

export function startClawStatusPolling(): void {
	if (!browser) return;
	stopClawStatusPolling();

	// Initial fetch
	fetchClawStatus();

	// Poll every 5 seconds
	pollTimer = setInterval(fetchClawStatus, 5000);
}

export function stopClawStatusPolling(): void {
	if (pollTimer) {
		clearInterval(pollTimer);
		pollTimer = null;
	}
}
