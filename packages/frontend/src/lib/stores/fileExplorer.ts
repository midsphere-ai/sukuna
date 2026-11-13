import { writable, get } from 'svelte/store';
import { browser } from '$app/environment';
import type { FileTreeNode, FileReadResponse } from '$api/sandbox';
import { API_V1 } from '$api/client';
import {
	getSandboxFileTree,
	readSandboxFile,
	createSandboxFile,
	deleteSandboxFile
} from '$api/sandbox';
import { authToken } from '$stores/auth';

/** The full file tree from the sandbox */
export const fileTree = writable<FileTreeNode[]>([]);

/** Whether a tree load is in progress */
export const fileTreeLoading = writable(false);

/** Set of expanded directory paths */
export const expandedDirs = writable<Set<string>>(new Set());

/** Currently selected file path (open in editor) */
export const selectedFilePath = writable<string | null>(null);

/** Currently open file content */
export const openFileContent = writable<FileReadResponse | null>(null);

/** Whether file content is loading */
export const fileContentLoading = writable(false);

/** Error message for file operations */
export const fileExplorerError = writable<string | null>(null);

/** The conversation ID the explorer is bound to */
export const fileExplorerConversationId = writable<string | null>(null);

/** Whether user is currently renaming a file */
export const renamingPath = writable<string | null>(null);

/** Path being created (new file/folder inline input) */
export const creatingIn = writable<{ parentPath: string; type: 'file' | 'directory' } | null>(null);

// ---------------------------------------------------------------------------
// Centralised file-watch SSE
// ---------------------------------------------------------------------------
// A single SSE connection shared by FileExplorer (tree reload) and
// CodeEditorPanel (editor tab content reload). Driven by startFileWatch /
// stopFileWatch — callers decide *when* to connect based on canvas tab state.

type FileEventListener = (event: { type: string; path: string }) => void;

let watchAbortController: AbortController | null = null;
let watchConversationId: string | null = null;
let reloadDebounce: ReturnType<typeof setTimeout> | null = null;
const fileEventListeners = new Set<FileEventListener>();

/** Register a callback for raw file-change SSE events (e.g. editor tab reload). */
export function onFileEvent(listener: FileEventListener): () => void {
	fileEventListeners.add(listener);
	return () => {
		fileEventListeners.delete(listener);
	};
}

/**
 * Start watching a conversation's sandbox files via SSE.
 * Safe to call repeatedly — restarts only when the conversationId changes.
 */
export function startFileWatch(conversationId: string): void {
	if (!browser) return;
	const token = get(authToken);
	if (!token) return;

	// Already watching the same conversation — no-op.
	if (watchAbortController && watchConversationId === conversationId) return;

	stopFileWatch();
	watchConversationId = conversationId;
	watchAbortController = new AbortController();

	const apiBase = import.meta.env.VITE_API_BASE_URL || '';
	const url = `${apiBase}${API_V1}/chat/sandbox/${conversationId}/files/watch?path=.`;

	fetch(url, {
		signal: watchAbortController.signal,
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (response) => {
			if (!response.ok || !response.body) return;
			const reader = response.body.getReader();
			const decoder = new TextDecoder();
			let buffer = '';

			for (;;) {
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });

				const lines = buffer.split('\n');
				buffer = lines.pop() || '';

				let hasTreeChange = false;
				for (const line of lines) {
					// Notify raw-event listeners (CodeEditorPanel uses this)
					if (line.startsWith('data: ')) {
						try {
							const event = JSON.parse(line.slice(6));
							for (const listener of fileEventListeners) {
								listener(event);
							}
						} catch {
							// skip malformed SSE data
						}
					}
					// Detect tree-level changes for debounced tree reload
					if (
						line.startsWith('event: file_created') ||
						line.startsWith('event: file_modified') ||
						line.startsWith('event: file_deleted')
					) {
						hasTreeChange = true;
					}
				}

				if (hasTreeChange) {
					if (reloadDebounce) clearTimeout(reloadDebounce);
					reloadDebounce = setTimeout(() => {
						loadFileTree(conversationId);
					}, 500);
				}
			}
		})
		.catch(() => {
			// Silently ignore — sandbox may not be ready or request was aborted.
		});
}

/** Stop the current file-watch SSE connection. */
export function stopFileWatch(): void {
	if (watchAbortController) {
		watchAbortController.abort();
		watchAbortController = null;
	}
	if (reloadDebounce) {
		clearTimeout(reloadDebounce);
		reloadDebounce = null;
	}
	watchConversationId = null;
}

export function toggleDir(path: string): void {
	expandedDirs.update((set) => {
		const next = new Set(set);
		if (next.has(path)) {
			next.delete(path);
		} else {
			next.add(path);
		}
		return next;
	});
}

export function expandDir(path: string): void {
	expandedDirs.update((set) => {
		const next = new Set(set);
		next.add(path);
		return next;
	});
}

export async function loadFileTree(conversationId: string): Promise<void> {
	fileTreeLoading.set(true);
	fileExplorerError.set(null);
	fileExplorerConversationId.set(conversationId);
	try {
		const resp = await getSandboxFileTree(conversationId);
		fileTree.set(resp.tree);
	} catch (e) {
		fileExplorerError.set(e instanceof Error ? e.message : 'Failed to load file tree');
		fileTree.set([]);
	} finally {
		fileTreeLoading.set(false);
	}
}

export async function selectFile(conversationId: string, path: string): Promise<void> {
	selectedFilePath.set(path);
	fileContentLoading.set(true);
	fileExplorerError.set(null);
	try {
		const resp = await readSandboxFile(conversationId, path);
		openFileContent.set(resp);
	} catch (e) {
		fileExplorerError.set(e instanceof Error ? e.message : 'Failed to read file');
		openFileContent.set(null);
	} finally {
		fileContentLoading.set(false);
	}
}

export async function createFileOrFolder(
	conversationId: string,
	parentPath: string,
	name: string,
	type: 'file' | 'directory'
): Promise<boolean> {
	const fullPath = parentPath === '.' ? name : `${parentPath}/${name}`;
	try {
		await createSandboxFile(conversationId, fullPath, type);
		// Expand parent so new item is visible
		expandDir(parentPath);
		// Reload tree
		await loadFileTree(conversationId);
		return true;
	} catch {
		return false;
	}
}

export async function deleteFileOrFolder(conversationId: string, path: string): Promise<boolean> {
	try {
		await deleteSandboxFile(conversationId, path);
		// Clear selected file if it was the deleted one
		if (get(selectedFilePath) === path) {
			selectedFilePath.set(null);
			openFileContent.set(null);
		}
		await loadFileTree(conversationId);
		return true;
	} catch {
		return false;
	}
}

export function resetFileExplorer(): void {
	stopFileWatch();
	fileTree.set([]);
	fileTreeLoading.set(false);
	expandedDirs.set(new Set());
	selectedFilePath.set(null);
	openFileContent.set(null);
	fileContentLoading.set(false);
	fileExplorerError.set(null);
	fileExplorerConversationId.set(null);
	renamingPath.set(null);
	creatingIn.set(null);
}
