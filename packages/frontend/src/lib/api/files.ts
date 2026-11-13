import { api } from './client';
import type { StoredFile, FileUploadResponse, PaginatedResponse } from './types';

export async function uploadFile(file: File): Promise<FileUploadResponse> {
	const formData = new FormData();
	formData.append('file', file);
	return api.upload<FileUploadResponse>('/memory/files', formData);
}

export async function getUserFiles(page = 1): Promise<PaginatedResponse<StoredFile>> {
	return api.get<PaginatedResponse<StoredFile>>(`/memory/files?page=${page}`);
}

export interface FileDownloadResponse {
	url: string;
	filename: string;
	mime_type: string | null;
	size: number | null;
}

export async function getFileDownloadUrl(fileId: string): Promise<FileDownloadResponse> {
	return api.get<FileDownloadResponse>(`/memory/files/${fileId}/download`);
}
