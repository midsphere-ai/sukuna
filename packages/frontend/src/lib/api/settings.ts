import { api } from './client';
import type { UserSettings, UserSettingsUpdate } from './types';

export async function getSettings(): Promise<UserSettings> {
	return api.get<UserSettings>('/memory/settings', { skipErrorHandling: true });
}

export async function updateSettings(data: UserSettingsUpdate): Promise<UserSettings> {
	return api.patch<UserSettings>('/memory/settings', data, { skipErrorHandling: true });
}
