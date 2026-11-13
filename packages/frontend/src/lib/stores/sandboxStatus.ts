import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';
import { getProjectSandboxStatus } from '$api/projects';
import type { ProjectSandboxStatus } from '$api/types';

const POLL_INTERVAL_MS = 3000;

export const sandboxStatus = writable<ProjectSandboxStatus | null>(null);
export const sandboxStatusLoading = writable(false);

let pollTimer: ReturnType<typeof setInterval> | null = null;
let activeProjectId: string | null = null;
let activeConversationId: string | null = null;

/**
 * Derive sandbox busy state for the current conversation from the conversations store.
 * Returns the busy conversation info if the project sandbox is occupied by another conversation.
 */
export const projectSandboxBusy = derived([sandboxStatus], ([$status]) => {
	if (
		!$status ||
		!$status.busy ||
		!activeConversationId ||
		$status.active_conversation_id === activeConversationId
	) {
		return null;
	}
	return {
		conversationId: $status.active_conversation_id,
		conversationTitle: $status.active_conversation_title
	};
});

async function fetchStatus(): Promise<void> {
	if (!activeProjectId) return;

	try {
		const status = await getProjectSandboxStatus(activeProjectId);
		sandboxStatus.set(status);
	} catch {
		// Silently fail — endpoint may not be available
	}
}

/**
 * Start polling sandbox status for a project.
 * Only polls when a conversation belongs to a project.
 */
export function startSandboxStatusPolling(projectId: string, conversationId: string): void {
	if (!browser) return;

	stopSandboxStatusPolling();

	activeProjectId = projectId;
	activeConversationId = conversationId;

	// Initial fetch
	fetchStatus();

	// Poll periodically
	pollTimer = setInterval(fetchStatus, POLL_INTERVAL_MS);
}

/**
 * Stop polling and clear status.
 */
export function stopSandboxStatusPolling(): void {
	if (pollTimer) {
		clearInterval(pollTimer);
		pollTimer = null;
	}
	activeProjectId = null;
	activeConversationId = null;
	sandboxStatus.set(null);
}
