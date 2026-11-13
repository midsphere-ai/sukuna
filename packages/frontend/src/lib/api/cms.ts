import { api } from './client';
import type { Tutorial, PaginatedResponse } from './types';

export interface HomeBanner {
	change_log: { id: string; markdownText: string; date_created: string } | null;
	announcement: { id: string; text: string; date_created: string } | null;
}

export interface ChangelogEntry {
	id: string;
	title: string;
	body: string;
	date: string;
	category: 'feature' | 'fix' | 'improvement' | 'announcement';
	is_published: boolean;
}

export async function getTutorials(): Promise<PaginatedResponse<Tutorial>> {
	return api.get<PaginatedResponse<Tutorial>>('/cms/tutorials');
}

export async function getTutorialContent(title: string): Promise<Tutorial | null> {
	return api.get<Tutorial | null>(`/cms/tutorials/content?title=${encodeURIComponent(title)}`);
}

export async function getHomeBanner(): Promise<HomeBanner> {
	return api.get<HomeBanner>('/cms/home-banner');
}

export async function getPublicHomeBanner(): Promise<HomeBanner> {
	return api.get<HomeBanner>('/cms/public/home-banner', {
		skipAuth: true,
		skipErrorHandling: true
	});
}

export async function getPublicTutorials(): Promise<PaginatedResponse<Tutorial>> {
	return api.get<PaginatedResponse<Tutorial>>('/cms/public/tutorials', {
		skipAuth: true,
		skipErrorHandling: true
	});
}

export async function getPublicTutorialContent(title: string): Promise<Tutorial | null> {
	return api.get<Tutorial | null>(
		`/cms/public/tutorials/content?title=${encodeURIComponent(title)}`,
		{ skipAuth: true, skipErrorHandling: true }
	);
}

export async function getInfoTutorials(): Promise<PaginatedResponse<Tutorial>> {
	return api.get<PaginatedResponse<Tutorial>>('/cms/tutorials/info', { skipErrorHandling: true });
}

export async function getPublicChangelog(): Promise<PaginatedResponse<ChangelogEntry>> {
	return api.get<PaginatedResponse<ChangelogEntry>>('/cms/changelog', {
		skipAuth: true,
		skipErrorHandling: true
	});
}
