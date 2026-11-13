/**
 * Presence store — tracks who is viewing the current conversation.
 *
 * Sends heartbeats every 30s while a conversation is open.
 */

import { writable, derived } from 'svelte/store';
import { api } from '$api/client';

export interface PresenceUser {
	user_id: string;
	display_name: string;
	avatar: string;
}

interface PresenceState {
	conversationId: string | null;
	users: PresenceUser[];
}

const initialState: PresenceState = {
	conversationId: null,
	users: []
};

export const presenceState = writable<PresenceState>(initialState);

export const presentUsers = derived(presenceState, ($s) => $s.users);

let heartbeatInterval: ReturnType<typeof setInterval> | null = null;
let currentConversationId: string | null = null;

/**
 * Start presence tracking for a conversation.
 * Sends initial heartbeat + sets up 30s interval.
 */
export function startPresence(conversationId: string): void {
	stopPresence();
	currentConversationId = conversationId;
	presenceState.update((s) => ({ ...s, conversationId, users: [] }));

	// Send initial heartbeat
	sendHeartbeat(conversationId);

	// Heartbeat every 30s
	heartbeatInterval = setInterval(() => {
		if (currentConversationId === conversationId) {
			sendHeartbeat(conversationId);
		}
	}, 30_000);
}

/**
 * Stop presence tracking. Clears intervals and resets state.
 */
export function stopPresence(): void {
	if (heartbeatInterval) {
		clearInterval(heartbeatInterval);
		heartbeatInterval = null;
	}
	currentConversationId = null;
	presenceState.set(initialState);
}

/**
 * Send a heartbeat to the backend and update present users list.
 */
async function sendHeartbeat(conversationId: string): Promise<void> {
	try {
		const res = await api.post<{ status: string; present_users: PresenceUser[] }>(
			`/chat/completions/${conversationId}/presence`
		);
		if (currentConversationId === conversationId && res.present_users) {
			presenceState.update((s) => ({
				...s,
				users: res.present_users
			}));
		}
	} catch {
		// Silently ignore heartbeat failures
	}
}
