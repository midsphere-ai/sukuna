import { writable, derived, get } from 'svelte/store';
import { browser } from '$app/environment';
import { listProjects } from '$api/projects';
import { createFreshnessTracker } from '$stores/freshness';
import { debounce } from '$utils/debounce';
import type { ProjectListItem } from '$api/types';

const PROJECTS_CACHE_KEY = 'midsphere-projects';

function loadCachedProjects(): ProjectListItem[] {
	if (!browser) return [];
	try {
		const raw = localStorage.getItem(PROJECTS_CACHE_KEY);
		if (raw) return JSON.parse(raw) as ProjectListItem[];
	} catch {
		// ignore
	}
	return [];
}

function cacheProjects(items: ProjectListItem[]): void {
	if (!browser) return;
	try {
		localStorage.setItem(PROJECTS_CACHE_KEY, JSON.stringify(items));
	} catch {
		// ignore
	}
}

export const projects = writable<ProjectListItem[]>(loadCachedProjects());
export const projectsLoading = writable(false);
export const projectsError = writable<string | null>(null);
export const activeProjectId = writable<string | null>(null);

export const activeProject = derived([projects, activeProjectId], ([$projects, $activeId]) => {
	if (!$activeId) return null;
	return $projects.find((p) => p.id === $activeId) ?? null;
});

const projectsFreshness = createFreshnessTracker(60_000);

// Sync projects to localStorage cache (debounced)
if (browser) {
	projects.subscribe(
		debounce((items: ProjectListItem[]) => {
			cacheProjects(items);
		}, 1000)
	);
}

export async function fetchProjects(): Promise<void> {
	if (!browser) return;

	const isEmpty = get(projects).length === 0;
	if (isEmpty) projectsLoading.set(true);
	projectsError.set(null);

	try {
		const response = await listProjects(1);
		projects.set(response.items);
		projectsFreshness.markFetched();
	} catch (err) {
		projectsError.set(err instanceof Error ? err.message : 'Failed to load projects');
	} finally {
		projectsLoading.set(false);
	}
}

export function ensureProjects(): Promise<void> {
	return projectsFreshness.ensureFresh(fetchProjects);
}

export function invalidateProjects(): void {
	projectsFreshness.invalidate();
}

export function addProjectLocal(project: ProjectListItem): void {
	projects.update((existing) => [project, ...existing]);
}

export function updateProjectLocal(projectId: string, updates: Partial<ProjectListItem>): void {
	projects.update((existing) =>
		existing.map((p) => (p.id === projectId ? { ...p, ...updates } : p))
	);
}

export function removeProjectLocal(projectId: string): void {
	projects.update((existing) => existing.filter((p) => p.id !== projectId));
	// Clear active project if it was the deleted one
	if (get(activeProjectId) === projectId) {
		activeProjectId.set(null);
	}
}

export function setActiveProject(projectId: string | null): void {
	activeProjectId.set(projectId);
}
