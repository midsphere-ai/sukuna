import { api } from './client';
import type {
	PaginatedResponse,
	ProjectListItem,
	ProjectDetail,
	ProjectCreateRequest,
	ProjectCreateResponse,
	ProjectUpdateRequest,
	ProjectUpdateResponse,
	ProjectDeleteResponse,
	ProjectFile,
	ProjectFileUploadResponse,
	ProjectFileDeleteResponse,
	ProjectSandboxStatus,
	MoveProjectResult,
	ProjectToolkit,
	ProjectToolkitUpdateRequest,
	ProjectSkillEntry,
	ProjectMCPConfigEntry,
	ProjectMCPConfigCreateRequest,
	ProjectAddonEntry
} from './types';

export async function listProjects(page = 1): Promise<PaginatedResponse<ProjectListItem>> {
	return api.get<PaginatedResponse<ProjectListItem>>(`/spaces/projects?page=${page}`);
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
	return api.get<ProjectDetail>(`/spaces/projects/${projectId}`);
}

export async function createProject(data: ProjectCreateRequest): Promise<ProjectCreateResponse> {
	return api.post<ProjectCreateResponse>('/spaces/projects', data);
}

export async function updateProject(
	projectId: string,
	data: ProjectUpdateRequest
): Promise<ProjectUpdateResponse> {
	return api.patch<ProjectUpdateResponse>(`/spaces/projects/${projectId}`, data);
}

export async function deleteProject(projectId: string): Promise<ProjectDeleteResponse> {
	return api.delete<ProjectDeleteResponse>(`/spaces/projects/${projectId}`);
}

export async function uploadProjectFile(
	projectId: string,
	file: File
): Promise<ProjectFileUploadResponse> {
	const formData = new FormData();
	formData.append('file', file);
	return api.upload<ProjectFileUploadResponse>(`/spaces/projects/${projectId}/files`, formData);
}

export async function listProjectFiles(projectId: string): Promise<ProjectFile[]> {
	return api.get<ProjectFile[]>(`/spaces/projects/${projectId}/files`);
}

export async function deleteProjectFile(
	projectId: string,
	fileId: string
): Promise<ProjectFileDeleteResponse> {
	return api.delete<ProjectFileDeleteResponse>(`/spaces/projects/${projectId}/files/${fileId}`);
}

export async function getProjectSandboxStatus(projectId: string): Promise<ProjectSandboxStatus> {
	return api.get<ProjectSandboxStatus>(`/spaces/projects/${projectId}/sandbox-status`);
}

export async function moveProject(
	projectId: string,
	organizationId: string | null
): Promise<MoveProjectResult> {
	return api.post<MoveProjectResult>(`/spaces/projects/${projectId}/move`, {
		organization_id: organizationId
	});
}

// --- Project Toolkit ---

export async function getProjectToolkit(projectId: string): Promise<ProjectToolkit> {
	return api.get<ProjectToolkit>(`/spaces/projects/${projectId}/toolkit`);
}

export async function updateProjectToolkit(
	projectId: string,
	data: ProjectToolkitUpdateRequest
): Promise<ProjectToolkit> {
	return api.put<ProjectToolkit>(`/spaces/projects/${projectId}/toolkit`, data);
}

export async function addProjectSkill(
	projectId: string,
	skillId: string,
	configOverrides?: Record<string, unknown>
): Promise<ProjectSkillEntry> {
	return api.post<ProjectSkillEntry>(`/spaces/projects/${projectId}/skills`, {
		skill_id: skillId,
		config_overrides: configOverrides
	});
}

export async function removeProjectSkill(
	projectId: string,
	skillEntryId: string
): Promise<{ skill_entry_id: string; deleted: boolean }> {
	return api.delete(`/spaces/projects/${projectId}/skills/${skillEntryId}`);
}

export async function addProjectMCPConfig(
	projectId: string,
	config: ProjectMCPConfigCreateRequest
): Promise<ProjectMCPConfigEntry> {
	return api.post<ProjectMCPConfigEntry>(`/spaces/projects/${projectId}/mcp-configs`, config);
}

export async function updateProjectMCPConfig(
	projectId: string,
	configId: string,
	data: Partial<ProjectMCPConfigCreateRequest>
): Promise<ProjectMCPConfigEntry> {
	return api.patch<ProjectMCPConfigEntry>(
		`/spaces/projects/${projectId}/mcp-configs/${configId}`,
		data
	);
}

export async function deleteProjectMCPConfig(
	projectId: string,
	configId: string
): Promise<{ config_id: string; deleted: boolean }> {
	return api.delete(`/spaces/projects/${projectId}/mcp-configs/${configId}`);
}

export async function addProjectAddon(
	projectId: string,
	addonId: string,
	config?: Record<string, unknown>
): Promise<ProjectAddonEntry> {
	return api.post<ProjectAddonEntry>(`/spaces/projects/${projectId}/addons`, {
		addon_id: addonId,
		config
	});
}

export async function removeProjectAddon(
	projectId: string,
	addonEntryId: string
): Promise<{ addon_entry_id: string; deleted: boolean }> {
	return api.delete(`/spaces/projects/${projectId}/addons/${addonEntryId}`);
}
