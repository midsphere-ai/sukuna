import { get, writable } from 'svelte/store';
import { expandPane } from '$stores/workspaceLayout';

export type SidePanelMode = 'none' | 'computer' | 'editor';

/** Whether the computer panel is visible (desktop) */
export const computerPanelOpen = writable(false);

/** Whether the code editor panel is visible (desktop) */
export const codeEditorPanelOpen = writable(false);

/** Desktop panel width in pixels */
export const computerPanelWidth = writable(480);

/** Whether the mobile drawer is open */
export const computerPanelMobileOpen = writable(false);

/** Whether the code editor mobile drawer is open */
export const codeEditorPanelMobileOpen = writable(false);

/** Active desktop side panel mode */
export const sidePanelMode = writable<SidePanelMode>('none');

/** Active mobile side panel mode */
export const sidePanelMobileMode = writable<SidePanelMode>('none');

/** Index of the currently viewed tool call in the panel */
export const computerPanelToolIndex = writable(-1);

/** Whether the user has pinned the current tool view (prevents auto-switch) */
export const computerPanelPinned = writable(false);

/** Whether VNC view is active in the panel */
export const computerPanelVncActive = writable(false);

/** Trigger to open the chat files dialog from the layout-level ChatHeader */
export const chatFilesDialogOpen = writable(false);

function applyDesktopMode(mode: SidePanelMode): void {
	sidePanelMode.set(mode);
	computerPanelOpen.set(mode === 'computer');
	codeEditorPanelOpen.set(mode === 'editor');
}

function applyMobileMode(mode: SidePanelMode): void {
	sidePanelMobileMode.set(mode);
	computerPanelMobileOpen.set(mode === 'computer');
	codeEditorPanelMobileOpen.set(mode === 'editor');
}

export function toggleComputerPanel(): void {
	const next: SidePanelMode = get(sidePanelMode) === 'computer' ? 'none' : 'computer';
	applyDesktopMode(next);
}

export function toggleCodeEditorPanel(): void {
	const next: SidePanelMode = get(sidePanelMode) === 'editor' ? 'none' : 'editor';
	applyDesktopMode(next);
}

export function openComputerPanel(): void {
	applyDesktopMode('computer');
}

export function openCodeEditorPanel(): void {
	applyDesktopMode('editor');
}

export function closeComputerPanel(): void {
	applyDesktopMode('none');
}

export function closeCodeEditorPanel(): void {
	applyDesktopMode('none');
}

export function openComputerPanelMobile(): void {
	applyMobileMode('computer');
}

export function openCodeEditorPanelMobile(): void {
	applyMobileMode('editor');
}

export function closeComputerPanelMobile(): void {
	applyMobileMode('none');
}

export function closeCodeEditorPanelMobile(): void {
	applyMobileMode('none');
}

/** Open the computer panel and navigate to a specific tool call by its index */
export function openComputerPanelAtIndex(index: number): void {
	computerPanelToolIndex.set(index);
	computerPanelPinned.set(true);
	computerPanelVncActive.set(false);
	// Desktop: ensure the editor pane is visible
	expandPane('editor');
	// Mobile: open the bottom-sheet drawer
	applyMobileMode('computer');
}
