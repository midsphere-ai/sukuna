import { writable } from 'svelte/store';
import { browser } from '$app/environment';
import { debounce } from '$utils/debounce';

const STORAGE_KEY = 'midsphere-workspace-layout';

export type MobileTab = 'files' | 'editor' | 'chat';

export interface WorkspaceLayoutState {
	/** File explorer pane width in pixels */
	fileExplorerWidth: number;
	/** Code editor pane takes remaining space; chat pane width in pixels */
	chatWidth: number;
	/** Whether file explorer pane is collapsed */
	fileExplorerCollapsed: boolean;
	/** Whether chat pane is collapsed */
	chatCollapsed: boolean;
	/** Whether editor pane is collapsed */
	editorCollapsed: boolean;
	/** Active tab on mobile */
	mobileTab: MobileTab;
}

const DEFAULT_STATE: WorkspaceLayoutState = {
	fileExplorerWidth: 240,
	chatWidth: 480,
	fileExplorerCollapsed: false,
	chatCollapsed: false,
	editorCollapsed: false,
	mobileTab: 'chat'
};

function loadState(): WorkspaceLayoutState {
	if (!browser) return { ...DEFAULT_STATE };
	try {
		const stored = localStorage.getItem(STORAGE_KEY);
		if (stored) {
			const parsed = JSON.parse(stored) as Partial<WorkspaceLayoutState>;
			return { ...DEFAULT_STATE, ...parsed };
		}
	} catch {
		// corrupted localStorage — use defaults
	}
	return { ...DEFAULT_STATE };
}

function saveState(state: WorkspaceLayoutState): void {
	if (!browser) return;
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
	} catch {
		// localStorage full or unavailable
	}
}

export const workspaceLayout = writable<WorkspaceLayoutState>(loadState());

// Persist on change (debounced)
workspaceLayout.subscribe(
	debounce((state: WorkspaceLayoutState) => {
		saveState(state);
	}, 500)
);

export function setFileExplorerWidth(width: number): void {
	workspaceLayout.update((s) => ({ ...s, fileExplorerWidth: Math.max(160, Math.min(400, width)) }));
}

export function setChatWidth(width: number): void {
	workspaceLayout.update((s) => ({ ...s, chatWidth: Math.max(320, width) }));
}

export function toggleFileExplorer(): void {
	workspaceLayout.update((s) => ({ ...s, fileExplorerCollapsed: !s.fileExplorerCollapsed }));
}

export function toggleChat(): void {
	workspaceLayout.update((s) => ({ ...s, chatCollapsed: !s.chatCollapsed }));
}

export function toggleEditor(): void {
	workspaceLayout.update((s) => ({ ...s, editorCollapsed: !s.editorCollapsed }));
}

export function setMobileTab(tab: MobileTab): void {
	workspaceLayout.update((s) => ({ ...s, mobileTab: tab }));
}

export function collapsePane(pane: 'fileExplorer' | 'editor' | 'chat'): void {
	workspaceLayout.update((s) => ({
		...s,
		fileExplorerCollapsed: pane === 'fileExplorer' ? true : s.fileExplorerCollapsed,
		editorCollapsed: pane === 'editor' ? true : s.editorCollapsed,
		chatCollapsed: pane === 'chat' ? true : s.chatCollapsed
	}));
}

export function expandPane(pane: 'fileExplorer' | 'editor' | 'chat'): void {
	workspaceLayout.update((s) => ({
		...s,
		fileExplorerCollapsed: pane === 'fileExplorer' ? false : s.fileExplorerCollapsed,
		editorCollapsed: pane === 'editor' ? false : s.editorCollapsed,
		chatCollapsed: pane === 'chat' ? false : s.chatCollapsed
	}));
}

/** Reset layout to defaults */
export function resetWorkspaceLayout(): void {
	workspaceLayout.set({ ...DEFAULT_STATE });
}
