import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { ProjectListItem } from '$api/types';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock localStorage
const mockStorage: Record<string, string> = {};
vi.stubGlobal('localStorage', {
	getItem: vi.fn((key: string) => mockStorage[key] ?? null),
	setItem: vi.fn((key: string, value: string) => {
		mockStorage[key] = value;
	}),
	removeItem: vi.fn((key: string) => {
		delete mockStorage[key];
	}),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

// Mock projects API
const mockListProjects = vi.fn();
vi.mock('$api/projects', () => ({
	listProjects: (...args: unknown[]) => mockListProjects(...args)
}));

function makeProject(overrides: Partial<ProjectListItem> & { id: string }): ProjectListItem {
	return {
		title: 'Untitled',
		description: '',
		icon: '',
		custom_instructions: '',
		user: 1,
		sandbox: null,
		date_created: '2026-01-01T00:00:00Z',
		date_updated: '2026-01-01T00:00:00Z',
		conversation_count: 0,
		...overrides
	};
}

describe('projects store', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
		mockListProjects.mockReset();
	});

	it('starts empty', async () => {
		const { projects, projectsLoading, projectsError, activeProjectId, activeProject } =
			await import('$stores/projects');
		expect(get(projects)).toEqual([]);
		expect(get(projectsLoading)).toBe(false);
		expect(get(projectsError)).toBeNull();
		expect(get(activeProjectId)).toBeNull();
		expect(get(activeProject)).toBeNull();
	});

	it('fetchProjects loads from API', async () => {
		const items = [
			makeProject({ id: 'p1', title: 'Project 1' }),
			makeProject({ id: 'p2', title: 'Project 2' })
		];
		mockListProjects.mockResolvedValue({ items });
		const { projects, fetchProjects } = await import('$stores/projects');

		await fetchProjects();
		expect(get(projects)).toEqual(items);
		expect(mockListProjects).toHaveBeenCalledWith(1);
	});

	it('fetchProjects handles errors', async () => {
		mockListProjects.mockRejectedValue(new Error('Network fail'));
		const { projectsError, fetchProjects } = await import('$stores/projects');

		await fetchProjects();
		expect(get(projectsError)).toBe('Network fail');
	});

	it('addProjectLocal prepends project', async () => {
		const { projects, addProjectLocal } = await import('$stores/projects');
		const p = makeProject({ id: 'p1', title: 'New' });
		addProjectLocal(p);
		expect(get(projects)[0]).toEqual(p);
	});

	it('updateProjectLocal updates a project', async () => {
		const { projects, addProjectLocal, updateProjectLocal } = await import('$stores/projects');
		addProjectLocal(makeProject({ id: 'p1', title: 'Old' }));
		updateProjectLocal('p1', { title: 'New' });
		expect(get(projects)[0].title).toBe('New');
	});

	it('removeProjectLocal removes a project', async () => {
		const { projects, addProjectLocal, removeProjectLocal } = await import('$stores/projects');
		addProjectLocal(makeProject({ id: 'p1', title: 'Test' }));
		removeProjectLocal('p1');
		expect(get(projects)).toHaveLength(0);
	});

	it('removeProjectLocal clears activeProjectId if deleted', async () => {
		const { activeProjectId, addProjectLocal, setActiveProject, removeProjectLocal } =
			await import('$stores/projects');
		addProjectLocal(makeProject({ id: 'p1', title: 'Test' }));
		setActiveProject('p1');
		expect(get(activeProjectId)).toBe('p1');
		removeProjectLocal('p1');
		expect(get(activeProjectId)).toBeNull();
	});

	it('activeProject derives from projects and activeProjectId', async () => {
		const { activeProject, addProjectLocal, setActiveProject } = await import('$stores/projects');
		const p1 = makeProject({ id: 'p1', title: 'Test' });
		const p2 = makeProject({ id: 'p2', title: 'Other' });
		addProjectLocal(p1);
		addProjectLocal(p2);
		setActiveProject('p1');
		expect(get(activeProject)).toEqual(p1);
	});

	it('activeProject returns null for unknown id', async () => {
		const { activeProject, setActiveProject } = await import('$stores/projects');
		setActiveProject('nonexistent');
		expect(get(activeProject)).toBeNull();
	});
});
