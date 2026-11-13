import { api } from './client';

export interface EnterpriseModeStatus {
	enabled: boolean;
	available: boolean;
}

export async function getEnterpriseMode(): Promise<EnterpriseModeStatus> {
	return api.get<EnterpriseModeStatus>('/workspace/enterprise-mode');
}

export async function updateEnterpriseMode(
	enabled: boolean,
	currentPassword: string
): Promise<EnterpriseModeStatus> {
	return api.patch<EnterpriseModeStatus>('/workspace/enterprise-mode', {
		enabled,
		current_password: currentPassword
	});
}
