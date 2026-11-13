import { browser } from '$app/environment';
import { get } from 'svelte/store';
import { authToken } from '$stores/auth';
import { conversations } from '$stores/conversations';
import type { Conversation } from '$api/types';
import { createSSEParserState, parseSSELines } from '$lib/utils/sseParser';
import { getFetch } from '$utils/fetch';

const API_BASE = browser ? import.meta.env.VITE_API_BASE_URL || '' : '';
const STREAM_URL = `${API_BASE}/api/v1/memory/conversations/stream/`;
const MAX_RETRIES = 3;
const BASE_RETRY_DELAY_MS = 2000;

export interface ConversationStreamEvent {
	type: 'conversation_updated' | 'conversation_deleted' | 'sync_complete' | 'error';
	conversation?: {
		id: string;
		title: string;
		icon?: string;
		summary: string | null;
		status?: string;
		/** @deprecated Use status instead */
		on_going?: boolean;
		/** @deprecated Use status instead */
		has_error?: boolean;
		requires_user_input: boolean;
		date_updated: string | null;
		project_id?: string | null;
	};
	conversation_id?: string;
	is_new?: boolean;
	count?: number;
	message?: string;
}

let abortController: AbortController | null = null;
let retryCount = 0;
let retryTimeout: ReturnType<typeof setTimeout> | null = null;
let isConnected = false;

function deriveStatus(
	data: NonNullable<ConversationStreamEvent['conversation']>
): Conversation['status'] {
	if (data.status === 'pending') {
		return 'queued';
	}
	if (
		data.status === 'running' ||
		data.status === 'completed' ||
		data.status === 'failed' ||
		data.status === 'cancelled' ||
		data.status === 'idle' ||
		data.status === 'queued' ||
		data.status === 'provisioning'
	) {
		return data.status;
	}
	// Fallback to legacy boolean fields
	if (data.on_going) return 'running';
	if (data.has_error) return 'failed';
	return 'completed';
}

function mapSSEToConversation(
	data: ConversationStreamEvent['conversation']
): Partial<Conversation> {
	if (!data) return {};
	return {
		id: data.id,
		title: data.title,
		icon: data.icon ?? undefined,
		summary: data.summary ?? undefined,
		status: deriveStatus(data),
		date_updated: data.date_updated || new Date().toISOString(),
		project_id: data.project_id ?? undefined
	};
}

function handleEvent(eventType: string, data: ConversationStreamEvent): void {
	switch (eventType) {
		case 'conversation_updated':
			handleConversationUpdated(data);
			break;
		case 'conversation_deleted':
			handleConversationDeleted(data);
			break;
		case 'sync_complete':
			retryCount = 0;
			isConnected = true;
			break;
	}
}

function handleConversationUpdated(data: ConversationStreamEvent): void {
	if (!data.conversation) return;

	const partial = mapSSEToConversation(data.conversation);

	conversations.update((existing) => {
		const idx = existing.findIndex((c) => c.id === data.conversation!.id);
		if (idx >= 0) {
			const updated = { ...existing[idx], ...partial };
			const result = [...existing];
			result[idx] = updated;
			return result;
		} else if (data.is_new) {
			// New conversation — prepend
			const newConv: Conversation = {
				id: data.conversation!.id,
				title: data.conversation!.title || 'New chat',
				icon: data.conversation!.icon || '',
				summary: null,
				error: null,
				status: deriveStatus(data.conversation!),
				date_created: data.conversation!.date_updated || new Date().toISOString(),
				date_updated: data.conversation!.date_updated || new Date().toISOString(),
				metadata: {},
				project_id: data.conversation!.project_id ?? undefined
			};
			return [newConv, ...existing];
		}
		return existing;
	});
}

function handleConversationDeleted(data: ConversationStreamEvent): void {
	const deletedId = data.conversation_id;
	if (!deletedId) return;

	conversations.update((existing) => existing.filter((c) => c.id !== deletedId));
}

async function connectStream(): Promise<void> {
	if (!browser) return;

	const token = get(authToken);
	if (!token) return;

	abortController = new AbortController();

	let response: Response;
	try {
		const httpFetch = await getFetch();
		response = await httpFetch(STREAM_URL, {
			headers: {
				Authorization: `Bearer ${token}`
			},
			signal: abortController.signal
		});
	} catch (err) {
		if ((err as Error).name === 'AbortError') return;
		throw err;
	}

	if (!response.ok || !response.body) {
		throw new Error(`Conversation stream failed: ${response.status}`);
	}

	isConnected = true;
	retryCount = 0;

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	const parserState = createSSEParserState();

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, { stream: true });
			buffer = parseSSELines(buffer, handleEvent, parserState);
		}
	} catch (err) {
		if ((err as Error).name === 'AbortError') return;
		throw err;
	}
}

function scheduleRetry(): void {
	if (retryCount >= MAX_RETRIES) {
		isConnected = false;
		return;
	}

	retryCount++;
	const delay = BASE_RETRY_DELAY_MS * Math.pow(2, retryCount - 1) + Math.random() * 1000;
	retryTimeout = setTimeout(() => {
		connect();
	}, delay);
}

export function connect(): void {
	if (!browser) return;

	const token = get(authToken);
	if (!token) return;

	disconnect();

	connectStream().catch(() => {
		isConnected = false;
		scheduleRetry();
	});
}

export function disconnect(): void {
	if (abortController) {
		abortController.abort();
		abortController = null;
	}
	if (retryTimeout) {
		clearTimeout(retryTimeout);
		retryTimeout = null;
	}
	isConnected = false;
}

export function getIsConnected(): boolean {
	return isConnected;
}
