import { api } from './client';

export interface FileTreeNode {
	name: string;
	path: string;
	type: 'file' | 'directory';
	size?: number;
	children?: FileTreeNode[];
}

export interface FileTreeResponse {
	path: string;
	tree: FileTreeNode[];
}

export interface FileReadResponse {
	path: string;
	content: string;
	size: number;
	modified: string;
}

export interface FileWriteResponse {
	path: string;
	size: number;
	status: string;
}

export interface FileCreateResponse {
	path: string;
	type: string;
	status: string;
}

export interface FileDeleteResponse {
	path: string;
	type: string;
	status: string;
}

export async function getSandboxFileTree(
	conversationId: string,
	path = '.'
): Promise<FileTreeResponse> {
	return api.get<FileTreeResponse>(
		`/chat/sandbox/${conversationId}/files/tree?path=${encodeURIComponent(path)}`,
		{ skipErrorHandling: true }
	);
}

export async function readSandboxFile(
	conversationId: string,
	path: string
): Promise<FileReadResponse> {
	return api.get<FileReadResponse>(
		`/chat/sandbox/${conversationId}/files/read?path=${encodeURIComponent(path)}`,
		{ skipErrorHandling: true }
	);
}

export async function writeSandboxFile(
	conversationId: string,
	path: string,
	content: string
): Promise<FileWriteResponse> {
	return api.put<FileWriteResponse>(`/chat/sandbox/${conversationId}/files/write`, {
		path,
		content
	});
}

export async function createSandboxFile(
	conversationId: string,
	path: string,
	type: 'file' | 'directory' = 'file',
	content = ''
): Promise<FileCreateResponse> {
	return api.post<FileCreateResponse>(`/chat/sandbox/${conversationId}/files/create`, {
		path,
		type,
		content
	});
}

export async function deleteSandboxFile(
	conversationId: string,
	path: string
): Promise<FileDeleteResponse> {
	return api.delete<FileDeleteResponse>(
		`/chat/sandbox/${conversationId}/files/delete?path=${encodeURIComponent(path)}`
	);
}
