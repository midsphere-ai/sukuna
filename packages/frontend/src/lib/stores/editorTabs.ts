import { writable, get } from 'svelte/store';
import { readSandboxFile, writeSandboxFile } from '$api/sandbox';
import type { FileReadResponse } from '$api/sandbox';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface EditorTab {
	path: string;
	language: string;
	content: string;
	/** The last content known to be on the server (after load or save) */
	savedContent: string;
	loading: boolean;
	error: string | null;
	dirty: boolean;
	saveStatus: SaveStatus;
	saveError: string | null;
	/** Set when agent modifies a file the user has unsaved edits on */
	conflict: { serverContent: string } | null;
}

/** Open editor tabs */
export const editorTabs = writable<EditorTab[]>([]);

/** Currently active tab path */
export const activeTabPath = writable<string | null>(null);

/** Whether the agent is currently running (editor should be read-only) */
export const agentExecuting = writable(false);

/** Word wrap toggle */
export const editorWordWrap = writable(false);

function getLanguageFromPath(path: string): string {
	const ext = path.split('.').pop()?.toLowerCase() ?? '';
	const langMap: Record<string, string> = {
		ts: 'typescript',
		tsx: 'tsx',
		js: 'javascript',
		jsx: 'jsx',
		py: 'python',
		rb: 'ruby',
		rs: 'rust',
		go: 'go',
		java: 'java',
		html: 'html',
		css: 'css',
		scss: 'scss',
		json: 'json',
		yaml: 'text',
		yml: 'text',
		toml: 'text',
		md: 'markdown',
		sh: 'bash',
		bash: 'bash',
		sql: 'sql',
		svelte: 'svelte',
		vue: 'vue',
		xml: 'xml',
		c: 'c',
		cpp: 'cpp',
		h: 'c',
		kt: 'kotlin',
		swift: 'text',
		dart: 'text',
		php: 'php'
	};
	return langMap[ext] || 'text';
}

// --- Auto-save debounce timers per file path ---
const autoSaveTimers = new Map<string, ReturnType<typeof setTimeout>>();

function clearAutoSaveTimer(path: string): void {
	const timer = autoSaveTimers.get(path);
	if (timer) {
		clearTimeout(timer);
		autoSaveTimers.delete(path);
	}
}

/** Open a file in a new tab or switch to it if already open */
export async function openTab(conversationId: string, path: string): Promise<void> {
	const tabs = get(editorTabs);
	const existing = tabs.find((t) => t.path === path);

	if (existing) {
		activeTabPath.set(path);
		return;
	}

	// Add tab in loading state
	const newTab: EditorTab = {
		path,
		language: getLanguageFromPath(path),
		content: '',
		savedContent: '',
		loading: true,
		error: null,
		dirty: false,
		saveStatus: 'idle',
		saveError: null,
		conflict: null
	};

	editorTabs.update((t) => [...t, newTab]);
	activeTabPath.set(path);

	// Load content
	try {
		const resp: FileReadResponse = await readSandboxFile(conversationId, path);
		editorTabs.update((t) =>
			t.map((tab) =>
				tab.path === path
					? { ...tab, content: resp.content, savedContent: resp.content, loading: false }
					: tab
			)
		);
	} catch (e) {
		editorTabs.update((t) =>
			t.map((tab) =>
				tab.path === path
					? {
							...tab,
							loading: false,
							error: e instanceof Error ? e.message : 'Failed to read file'
						}
					: tab
			)
		);
	}
}

/** Close a tab */
export function closeTab(path: string): void {
	const tabs = get(editorTabs);
	const index = tabs.findIndex((t) => t.path === path);
	if (index === -1) return;

	clearAutoSaveTimer(path);

	const wasActive = get(activeTabPath) === path;
	editorTabs.update((t) => t.filter((tab) => tab.path !== path));

	if (wasActive) {
		const remaining = get(editorTabs);
		if (remaining.length > 0) {
			// Switch to adjacent tab
			const newIndex = Math.min(index, remaining.length - 1);
			activeTabPath.set(remaining[newIndex].path);
		} else {
			activeTabPath.set(null);
		}
	}
}

/** Mark a tab's content as changed by the user, schedule auto-save */
export function markTabDirty(conversationId: string, path: string, newContent: string): void {
	editorTabs.update((t) =>
		t.map((tab) =>
			tab.path === path
				? {
						...tab,
						content: newContent,
						dirty: newContent !== tab.savedContent,
						saveStatus: 'idle' as SaveStatus,
						saveError: null
					}
				: tab
		)
	);

	// Schedule auto-save after 1s of no typing
	clearAutoSaveTimer(path);
	const tab = get(editorTabs).find((t) => t.path === path);
	if (tab && tab.dirty) {
		const timer = setTimeout(() => {
			autoSaveTimers.delete(path);
			saveTab(conversationId, path);
		}, 1000);
		autoSaveTimers.set(path, timer);
	}
}

/** Save a tab's content to the sandbox */
export async function saveTab(conversationId: string, path: string): Promise<void> {
	const tabs = get(editorTabs);
	const tab = tabs.find((t) => t.path === path);
	if (!tab || !tab.dirty) return;

	const contentToSave = tab.content;

	// Set saving status
	editorTabs.update((t) =>
		t.map((tb) =>
			tb.path === path ? { ...tb, saveStatus: 'saving' as SaveStatus, saveError: null } : tb
		)
	);

	try {
		await writeSandboxFile(conversationId, path, contentToSave);
		editorTabs.update((t) =>
			t.map((tb) => {
				if (tb.path !== path) return tb;
				// Only mark clean if content hasn't changed since we started saving
				const stillClean = tb.content === contentToSave;
				return {
					...tb,
					savedContent: contentToSave,
					dirty: !stillClean,
					saveStatus: 'saved' as SaveStatus,
					saveError: null,
					conflict: null
				};
			})
		);
	} catch (e) {
		editorTabs.update((t) =>
			t.map((tb) =>
				tb.path === path
					? {
							...tb,
							saveStatus: 'error' as SaveStatus,
							saveError: e instanceof Error ? e.message : 'Save failed'
						}
					: tb
			)
		);
	}
}

/** Update content of a tab from SSE file watch (agent-side change).
 *  If the tab is dirty, set a conflict instead of overwriting. */
export function updateTabContent(path: string, content: string): void {
	editorTabs.update((t) =>
		t.map((tab) => {
			if (tab.path !== path) return tab;
			if (tab.dirty) {
				// Conflict: user has unsaved changes and agent modified the file
				return { ...tab, conflict: { serverContent: content } };
			}
			// No conflict — update both content and savedContent
			return { ...tab, content, savedContent: content };
		})
	);
}

/** Resolve a conflict by choosing the user's version or the server's version */
export function resolveConflict(
	conversationId: string,
	path: string,
	keep: 'mine' | 'theirs'
): void {
	editorTabs.update((t) =>
		t.map((tab) => {
			if (tab.path !== path || !tab.conflict) return tab;
			if (keep === 'theirs') {
				return {
					...tab,
					content: tab.conflict.serverContent,
					savedContent: tab.conflict.serverContent,
					dirty: false,
					conflict: null,
					saveStatus: 'idle' as SaveStatus
				};
			}
			// keep === 'mine' — keep user's content, discard conflict, stay dirty
			return { ...tab, conflict: null };
		})
	);

	// If user chose to keep their version, save it
	if (keep === 'mine') {
		saveTab(conversationId, path);
	}
}

/** Close all tabs */
export function closeAllTabs(): void {
	// Clear all auto-save timers
	for (const [, timer] of autoSaveTimers) {
		clearTimeout(timer);
	}
	autoSaveTimers.clear();

	editorTabs.set([]);
	activeTabPath.set(null);
}
