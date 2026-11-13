import { api } from './client';
import type { UserMCPConfig, MCPConfigInput, PaginatedResponse } from './types';

export async function getMCPConfigs(page = 1): Promise<PaginatedResponse<UserMCPConfig>> {
	return api.get<PaginatedResponse<UserMCPConfig>>(`/memory/mcp-configs?page=${page}`);
}

export async function registerMCPConfig(config: MCPConfigInput): Promise<{ id: string }> {
	return api.post(`/memory/mcp-configs`, config);
}

export async function unregisterMCPConfig(
	configId: string
): Promise<{ id: string; deleted: boolean }> {
	return api.delete(`/memory/mcp-configs/${configId}`);
}
