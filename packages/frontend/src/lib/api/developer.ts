import { api } from './client';
import type {
	DeveloperAPIKey,
	DeveloperAPIKeyCreated,
	CreateAPIKeyRequest,
	ActionResponse
} from './types';

export async function listAPIKeys(): Promise<DeveloperAPIKey[]> {
	return api.get<DeveloperAPIKey[]>('/developer/api-keys', { skipErrorHandling: true });
}

export async function createAPIKey(data: CreateAPIKeyRequest): Promise<DeveloperAPIKeyCreated> {
	return api.post<DeveloperAPIKeyCreated>('/developer/api-keys', data, {
		skipErrorHandling: true
	});
}

export async function revokeAPIKey(keyId: string): Promise<ActionResponse> {
	return api.delete<ActionResponse>(`/developer/api-keys/${keyId}`, undefined, {
		skipErrorHandling: true
	});
}
