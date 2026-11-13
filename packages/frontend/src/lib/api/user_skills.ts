import { api } from './client';
import type { PaginatedResponse } from './types';

export type UserSkillSource = 'editor' | 'upload_md' | 'upload_zip' | 'github';

export interface UserSkillSummary {
	id: string;
	slug: string;
	name: string;
	description: string;
	category: string;
	icon: string;
	source: UserSkillSource;
	source_url: string;
	version: string;
	date_created: string;
	date_updated: string;
}

export interface UserSkillDetail extends UserSkillSummary {
	skill_md_content: string;
	skill_files: Record<string, string>;
}

export async function listMySkills(page = 1): Promise<PaginatedResponse<UserSkillSummary>> {
	return api.get<PaginatedResponse<UserSkillSummary>>(`/memory/my-skills?page=${page}`);
}

export async function getMySkill(id: string): Promise<UserSkillDetail> {
	return api.get<UserSkillDetail>(`/memory/my-skills/${id}`);
}

export interface CreateFromEditorBody {
	name: string;
	description: string;
	body: string;
	category?: string;
	icon?: string;
	skill_files?: Record<string, string>;
}

export async function createFromEditor(body: CreateFromEditorBody): Promise<UserSkillDetail> {
	return api.post<UserSkillDetail>('/memory/my-skills', body);
}

export async function createFromGithub(url: string): Promise<UserSkillDetail> {
	return api.post<UserSkillDetail>('/memory/my-skills/from-github', { url });
}

export async function uploadSkillFile(file: File): Promise<UserSkillDetail> {
	const formData = new FormData();
	formData.append('file', file);
	return api.upload<UserSkillDetail>('/memory/my-skills/upload', formData);
}

export interface UpdateMySkillBody {
	name?: string;
	description?: string;
	body?: string;
	category?: string;
	icon?: string;
	skill_files?: Record<string, string> | null;
}

export async function updateMySkill(
	id: string,
	patch: UpdateMySkillBody
): Promise<UserSkillDetail> {
	return api.patch<UserSkillDetail>(`/memory/my-skills/${id}`, patch);
}

export async function deleteMySkill(id: string): Promise<{ id: string; deleted: boolean }> {
	return api.delete<{ id: string; deleted: boolean }>(`/memory/my-skills/${id}`);
}
