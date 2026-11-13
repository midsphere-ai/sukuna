import { api } from './client';

export interface ProjectShare {
	id: string;
	project_id: string;
	user_id: number | null;
	user_email: string | null;
	user_name: string | null;
	organization_id: string | null;
	permission_level: string; // 'view' | 'collaborate' | 'admin'
	shared_by_email: string | null;
	shared_at: string;
}

export function listProjectShares(projectId: string): Promise<ProjectShare[]> {
	return api.get<ProjectShare[]>(`/spaces/projects/${projectId}/shares`);
}

export function createProjectShare(
	projectId: string,
	data: { user_id?: number; organization_id?: string; permission_level: string }
): Promise<ProjectShare> {
	return api.post<ProjectShare>(`/spaces/projects/${projectId}/shares`, data);
}

export function updateProjectShare(
	projectId: string,
	shareId: string,
	data: { permission_level: string }
): Promise<ProjectShare> {
	return api.patch<ProjectShare>(`/spaces/projects/${projectId}/shares/${shareId}`, data);
}

export function deleteProjectShare(
	projectId: string,
	shareId: string
): Promise<{ success: boolean; message: string }> {
	return api.delete<{ success: boolean; message: string }>(
		`/spaces/projects/${projectId}/shares/${shareId}`
	);
}
