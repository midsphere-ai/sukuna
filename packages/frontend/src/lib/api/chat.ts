import { api } from './client';
import type { PersistedEvent } from '$services/sse';

export interface ConversationStatus {
	conversation_id: string;
	run_id: string | null;
	status:
		| 'idle'
		| 'running'
		| 'completed'
		| 'failed'
		| 'cancelled'
		| 'pending'
		| 'queued'
		| 'provisioning';
	/** @deprecated Use status instead */
	on_going?: boolean;
	/** @deprecated Use status instead */
	has_error?: boolean;
	/** @deprecated Use status instead */
	error?: string | null;
	task?: string | null;
	rating?: number | null;
	direct_stream_url?: string | null;
	direct_stream_token?: string | null;
	direct_stream_expires_at?: string | null;
	my_role?: 'creator' | 'collaborator' | 'viewer' | null;
}

export interface RunEventsResponse {
	events: PersistedEvent[];
}

export interface EventsCursor {
	before_created_at?: string;
	before_run_id?: string;
	before_sequence?: number;
}

export interface PaginatedEventsResponse {
	events: PersistedEvent[];
	total_count: number;
	has_more: boolean;
	oldest_sequence: number | null;
	newest_sequence: number | null;
	next_cursor: EventsCursor | null;
}

export interface EventsQueryParams {
	cursor?: EventsCursor | null;
	beforeSequence?: number;
	limit?: number;
}

function applyEventsQueryParams(query: URLSearchParams, params?: EventsQueryParams): void {
	const cursor = params?.cursor;

	if (cursor?.before_created_at && cursor.before_run_id && cursor.before_sequence != null) {
		query.set('before_created_at', cursor.before_created_at);
		query.set('before_run_id', cursor.before_run_id);
		query.set('before_sequence', String(cursor.before_sequence));
		return;
	}

	if (cursor?.before_sequence != null) {
		query.set('before_sequence', String(cursor.before_sequence));
		return;
	}

	if (params?.beforeSequence != null) {
		query.set('before_sequence', String(params.beforeSequence));
	}
}

export async function getConversationStatus(conversationId: string): Promise<ConversationStatus> {
	return api.get<ConversationStatus>(`/chat/completions/${conversationId}/status`, {
		cache: 'no-store'
	});
}

export async function getSharedConversationStatus(
	conversationId: string
): Promise<ConversationStatus> {
	return api.get<ConversationStatus>(`/chat/shared/${conversationId}/status`, {
		skipAuth: true,
		skipErrorHandling: true
	});
}

export interface SharedConversationInfo {
	id: string;
	title: string;
	date_created: string;
	date_updated: string;
}

export async function getSharedConversation(
	conversationId: string
): Promise<SharedConversationInfo> {
	return api.get<SharedConversationInfo>(`/memory/conversations/${conversationId}/shared`, {
		skipAuth: true,
		skipErrorHandling: true
	});
}

export async function getRunEvents(
	conversationId: string,
	params?: EventsQueryParams
): Promise<PaginatedEventsResponse> {
	const query = new URLSearchParams();
	applyEventsQueryParams(query, params);
	if (params?.limit != null) query.set('limit', String(params.limit));
	const qs = query.toString();
	const url = `/chat/completions/${conversationId}/events${qs ? `?${qs}` : ''}`;

	const data = await api.get<PaginatedEventsResponse | RunEventsResponse | PersistedEvent[]>(url);

	if (Array.isArray(data)) {
		return {
			events: data,
			total_count: data.length,
			has_more: false,
			oldest_sequence: data.length > 0 ? data[0].sequence : null,
			newest_sequence: data.length > 0 ? data[data.length - 1].sequence : null,
			next_cursor: null
		};
	}
	if ('has_more' in data) {
		const paginated = data as PaginatedEventsResponse;
		return { ...paginated, next_cursor: paginated.next_cursor ?? null };
	}
	const events = (data as RunEventsResponse).events || [];
	return {
		events,
		total_count: events.length,
		has_more: false,
		oldest_sequence: events.length > 0 ? events[0].sequence : null,
		newest_sequence: events.length > 0 ? events[events.length - 1].sequence : null,
		next_cursor: null
	};
}

export async function getSharedRunEvents(
	conversationId: string,
	params?: EventsQueryParams
): Promise<PaginatedEventsResponse> {
	const query = new URLSearchParams();
	applyEventsQueryParams(query, params);
	if (params?.limit != null) query.set('limit', String(params.limit));
	const qs = query.toString();
	const url = `/chat/shared/${conversationId}/events${qs ? `?${qs}` : ''}`;

	const data = await api.get<PaginatedEventsResponse | RunEventsResponse | PersistedEvent[]>(url, {
		skipAuth: true,
		skipErrorHandling: true
	});

	if (Array.isArray(data)) {
		return {
			events: data,
			total_count: data.length,
			has_more: false,
			oldest_sequence: data.length > 0 ? data[0].sequence : null,
			newest_sequence: data.length > 0 ? data[data.length - 1].sequence : null,
			next_cursor: null
		};
	}
	if ('has_more' in data) {
		const paginated = data as PaginatedEventsResponse;
		return { ...paginated, next_cursor: paginated.next_cursor ?? null };
	}
	const events = (data as RunEventsResponse).events || [];
	return {
		events,
		total_count: events.length,
		has_more: false,
		oldest_sequence: events.length > 0 ? events[0].sequence : null,
		newest_sequence: events.length > 0 ? events[events.length - 1].sequence : null,
		next_cursor: null
	};
}

export async function submitRunFeedback(
	conversationId: string,
	rating: number
): Promise<{ conversation_id: string; rating: number }> {
	return api.post(`/chat/completions/${conversationId}/feedback`, { rating });
}

export interface DesktopStreamResponse {
	available: boolean;
	stream_url?: string | null;
	expires_at?: string | null;
	reason?: string | null;
}

export async function getDesktopStream(conversationId: string): Promise<DesktopStreamResponse> {
	return api.get<DesktopStreamResponse>(`/chat/completions/${conversationId}/desktop-stream`);
}
