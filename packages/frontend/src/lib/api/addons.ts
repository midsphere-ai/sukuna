import { api } from './client';
import type { MarketplaceAddon, UserAddon, PaginatedResponse } from './types';

export async function getAddons(
	page = 1,
	options?: { skipErrorHandling?: boolean }
): Promise<PaginatedResponse<MarketplaceAddon>> {
	return api.get<PaginatedResponse<MarketplaceAddon>>(`/memory/addons?page=${page}`, options);
}

export async function searchAddons(
	query: string,
	page = 1
): Promise<PaginatedResponse<MarketplaceAddon>> {
	return api.get<PaginatedResponse<MarketplaceAddon>>(
		`/memory/addons/search?query=${encodeURIComponent(query)}&page=${page}`
	);
}

export async function getAddonDetail(addonId: string): Promise<{
	marketplace_addon: MarketplaceAddon;
	user_addon: UserAddon | null;
	features: Record<string, unknown>[];
}> {
	return api.get(`/memory/addons/${addonId}`);
}

export async function registerAddon(
	addonId: string,
	options?: { skipErrorHandling?: boolean }
): Promise<{ user_addon_id: string; is_new: boolean }> {
	return api.post(`/memory/addons/register`, { addon_id: addonId }, options);
}

export async function unregisterAddon(
	userAddonId: string
): Promise<{ user_addon_id: string; removed: boolean }> {
	return api.delete(`/memory/user-addons/${userAddonId}`);
}

export async function getAddonAuthLink(
	userAddonId: string,
	options?: { skipErrorHandling?: boolean }
): Promise<{ user_addon_id: string; auth_link: string }> {
	return api.get(`/memory/user-addons/${userAddonId}/auth-link`, options);
}

export async function checkAddonAuthStatus(
	userAddonId: string,
	options?: { skipErrorHandling?: boolean }
): Promise<{ user_addon_id: string; is_authorised: boolean }> {
	return api.post(`/memory/user-addons/${userAddonId}/refresh-auth`, undefined, options);
}

export async function getUserAddons(page = 1): Promise<PaginatedResponse<UserAddon>> {
	return api.get<PaginatedResponse<UserAddon>>(`/memory/user-addons?page=${page}`);
}

export async function searchUserAddons(
	query: string,
	authComplete?: boolean,
	page = 1
): Promise<PaginatedResponse<UserAddon>> {
	const params = new URLSearchParams({ query, page: String(page) });
	if (authComplete !== undefined) {
		params.set('auth_complete', String(authComplete));
	}
	return api.get<PaginatedResponse<UserAddon>>(`/memory/user-addons/search?${params}`);
}
