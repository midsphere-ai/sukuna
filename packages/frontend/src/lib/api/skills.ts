import { api } from './client';
import type { PaginatedResponse } from './types';

export interface SkillCatalog {
	id: string;
	slug: string;
	name: string;
	description: string;
	category: string;
	source_type: string;
	source_repo: string;
	author: string;
	has_scripts: boolean;
	has_templates: boolean;
	tags: string[];
	license: string;
	version: string;
	icon: string;
	install_count: number;
	is_featured: boolean;
	is_installed: boolean;
	date_created: string;
}

export interface SkillDetail extends SkillCatalog {
	skill_md_content: string;
	source_path: string;
	skill_files: Record<string, string>;
}

export interface CategoryCount {
	category: string;
	count: number;
	icon: string;
}

export async function getSkills(
	page = 1,
	category = '',
	sourceType = ''
): Promise<PaginatedResponse<SkillCatalog>> {
	const params = new URLSearchParams({ page: String(page) });
	if (category) params.set('category', category);
	if (sourceType) params.set('source_type', sourceType);
	return api.get<PaginatedResponse<SkillCatalog>>(`/memory/skills?${params}`);
}

export async function searchSkills(
	query: string,
	page = 1
): Promise<PaginatedResponse<SkillCatalog>> {
	return api.get<PaginatedResponse<SkillCatalog>>(
		`/memory/skills/search?q=${encodeURIComponent(query)}&page=${page}`
	);
}

export async function getSkillDetail(slug: string): Promise<SkillDetail> {
	return api.get<SkillDetail>(`/memory/skills/${slug}`);
}

export async function getCategories(): Promise<CategoryCount[]> {
	return api.get<CategoryCount[]>(`/memory/skills/categories`);
}

export async function installSkill(slug: string): Promise<{ slug: string; installed: boolean }> {
	return api.post(`/memory/skills/${slug}/install`);
}

export async function uninstallSkill(slug: string): Promise<{ slug: string; installed: boolean }> {
	return api.delete(`/memory/skills/${slug}/install`);
}

export async function getInstalledSkills(page = 1): Promise<PaginatedResponse<SkillCatalog>> {
	return api.get<PaginatedResponse<SkillCatalog>>(`/memory/skills/installed?page=${page}`);
}
