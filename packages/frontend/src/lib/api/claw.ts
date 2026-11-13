import { api } from './client';

// ── Types ───────────────────────────────────────────────────────────────────

export interface ClawStatus {
	active: boolean;
	sandbox_state: string;
	sandbox_id: string | null;
	uptime_seconds: number;
	last_used_at: string | null;
	created_at: string | null;
}

export interface ClawActivateResponse {
	active: boolean;
	sandbox_id: string;
	message: string;
}

export interface ClawDeactivateResponse {
	active: boolean;
	message: string;
}

export interface ClawMessageRequest {
	prompt: string;
	conversation_id?: string;
	model?: string;
	platform?: string;
	platform_user_id?: string;
}

export interface ClawMessageResponse {
	conversation_id: string;
	run_id: string;
	status: string;
	message: string;
	recovered: boolean;
}

export interface ClawConversation {
	id: string;
	title: string;
	created_at: string;
	updated_at: string;
	on_going: boolean;
}

export interface TelegramLinkResponse {
	status: string;
	telegram_chat_id: string;
	telegram_username: string;
}

export interface SlackLinkResponse {
	status: string;
	slack_user_id: string;
	slack_username: string;
}

export interface SlackInstallResponse {
	authorize_url: string;
}

// ── API calls ───────────────────────────────────────────────────────────────

const BASE = '/claw';

export function activateClawSandbox(): Promise<ClawActivateResponse> {
	return api.post<ClawActivateResponse>(`${BASE}/activate`);
}

export function getClawStatus(): Promise<ClawStatus> {
	return api.get<ClawStatus>(`${BASE}/status`, { skipErrorHandling: true });
}

export function deactivateClawSandbox(): Promise<ClawDeactivateResponse> {
	return api.post<ClawDeactivateResponse>(`${BASE}/deactivate`);
}

export function sendClawMessage(data: ClawMessageRequest): Promise<ClawMessageResponse> {
	return api.post<ClawMessageResponse>(`${BASE}/message`, data);
}

export function getClawConversations(): Promise<ClawConversation[]> {
	return api.get<ClawConversation[]>(`${BASE}/conversations`);
}

// ── Platform Linking ─────────────────────────────────────────────────���──────

export function linkTelegram(data: { token: string }): Promise<TelegramLinkResponse> {
	return api.post<TelegramLinkResponse>(`${BASE}/telegram/link`, data);
}

export function linkSlack(data: { token: string }): Promise<SlackLinkResponse> {
	return api.post<SlackLinkResponse>(`${BASE}/slack/link`, data);
}

export function getSlackInstallUrl(): Promise<SlackInstallResponse> {
	return api.get<SlackInstallResponse>(`${BASE}/slack/install`);
}
