import { api } from './client';
import type { ActionResponse, BYOMProvider, BYOMProviderInput, BYOMToolSlot } from './types';

export async function listBYOMProviders(): Promise<BYOMProvider[]> {
	return api.get<BYOMProvider[]>('/byom/providers', { skipErrorHandling: true });
}

export async function upsertBYOMProvider(data: BYOMProviderInput): Promise<BYOMProvider> {
	return api.post<BYOMProvider>('/byom/providers', data, { skipErrorHandling: true });
}

export async function deleteBYOMProvider(toolSlot: BYOMToolSlot): Promise<ActionResponse> {
	return api.delete<ActionResponse>(`/byom/providers/${toolSlot}`, undefined, {
		skipErrorHandling: true
	});
}
