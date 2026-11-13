import { api } from './client';

export interface Authenticator {
	id: number;
	type: 'totp' | 'recovery_codes' | 'webauthn';
	created_at: string | null;
	last_used_at: string | null;
}

export interface MFAState {
	enrolled: boolean;
	has_totp: boolean;
	has_recovery_codes: boolean;
	pending_challenge: boolean;
	authenticators: Authenticator[];
}

export interface TOTPBegin {
	secret: string;
	otpauth_uri: string;
	issuer: string;
	label: string;
}

export interface RecoveryCodes {
	codes: string[];
	unused_count: number;
}

export interface MFAVerifyResult {
	success: boolean;
	method: 'totp' | 'recovery_codes';
}

const BASE = '/users/me/mfa';

export function getMFAState(): Promise<MFAState> {
	return api.get<MFAState>(BASE, { skipErrorHandling: true });
}

export function beginTOTPEnrollment(): Promise<TOTPBegin> {
	return api.post<TOTPBegin>(`${BASE}/totp/begin`, {});
}

export function confirmTOTPEnrollment(secret: string, code: string): Promise<Authenticator> {
	return api.post<Authenticator>(`${BASE}/totp/confirm`, { secret, code });
}

export function generateRecoveryCodes(): Promise<RecoveryCodes> {
	return api.post<RecoveryCodes>(`${BASE}/recovery-codes/generate`, {});
}

export function regenerateRecoveryCodes(): Promise<RecoveryCodes> {
	return api.post<RecoveryCodes>(`${BASE}/recovery-codes/regenerate`, {});
}

export function removeAuthenticator(id: number): Promise<{ success: boolean }> {
	return api.delete<{ success: boolean }>(`${BASE}/${id}`);
}

export function verifyMFA(code: string): Promise<MFAVerifyResult> {
	return api.post<MFAVerifyResult>(`${BASE}/verify`, { code });
}
