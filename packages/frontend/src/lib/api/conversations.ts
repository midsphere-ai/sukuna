import { api } from './client';
import type {
	Conversation,
	ConversationCreateResponse,
	PaginatedResponse,
	DeleteResponse
} from './types';

export async function createConversation(): Promise<ConversationCreateResponse> {
	return api.post<ConversationCreateResponse>('/memory/conversations');
}

export async function getConversations(page = 1): Promise<PaginatedResponse<Conversation>> {
	return api.get<PaginatedResponse<Conversation>>(`/memory/conversations?page=${page}`);
}

export async function searchConversations(
	query: string,
	page = 1
): Promise<PaginatedResponse<Conversation>> {
	return api.get<PaginatedResponse<Conversation>>(
		`/memory/conversations/search?query=${encodeURIComponent(query)}&page=${page}`
	);
}

export async function deleteConversation(conversationId: string): Promise<DeleteResponse> {
	return api.delete<DeleteResponse>(`/memory/conversations/${conversationId}`);
}

export async function deleteAllConversations(): Promise<DeleteResponse> {
	return api.delete<DeleteResponse>('/memory/conversations');
}

export async function bulkDeleteConversations(conversationIds: string[]): Promise<DeleteResponse> {
	return api.post<DeleteResponse>('/memory/conversations/bulk-delete', {
		conversation_ids: conversationIds
	});
}

export async function renameConversation(
	conversationId: string,
	title: string
): Promise<Conversation> {
	return api.patch<Conversation>(`/memory/conversations/${conversationId}`, { title });
}

export async function shareConversation(conversationId: string): Promise<Conversation> {
	return api.patch<Conversation>(`/memory/conversations/${conversationId}`, {
		metadata: { shared: true }
	});
}

export async function unshareConversation(conversationId: string): Promise<Conversation> {
	return api.patch<Conversation>(`/memory/conversations/${conversationId}`, {
		metadata: { shared: false }
	});
}
