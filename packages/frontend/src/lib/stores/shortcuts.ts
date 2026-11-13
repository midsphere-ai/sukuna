import { writable, get } from 'svelte/store';
import { goto } from '$app/navigation';
import { toggleSidebar } from './sidebar';
import { sidebarMobileOpen, closeMobileSidebar } from './sidebar';
import { searchOpen, closeSearch, openSearch } from './search';
import { toggleComputerPanel } from './computerPanel';
import { conversations } from './conversations';
import { openSettings } from './settings';

export interface Shortcut {
	keys: string[];
	label: string;
	description: string;
	category: 'navigation' | 'chat' | 'panels' | 'general';
	action: () => void;
	/** When true, shortcut is shown in cheatsheet but not handled by the global keydown handler */
	displayOnly?: boolean;
}

export const cheatsheetOpen = writable(false);

// Context-dependent action callbacks — set by pages that support them
export const onStopAgent = writable<(() => void) | null>(null);
export const onExportChat = writable<(() => void) | null>(null);

function closeCheatsheet(): void {
	cheatsheetOpen.set(false);
}

function toggleCheatsheet(): void {
	cheatsheetOpen.update((v) => !v);
}

function navigateNewChat(): void {
	// eslint-disable-next-line svelte/no-navigation-without-resolve -- programmatic navigation from keyboard shortcut
	goto('/');
}

function navigateConversation(direction: 'up' | 'down'): void {
	const convs = get(conversations);
	if (convs.length === 0) return;

	const path = typeof window !== 'undefined' ? window.location.pathname : '';
	const match = path.match(/\/chat\/([^/]+)/);
	const currentId = match ? match[1] : null;

	const currentIndex = currentId ? convs.findIndex((c) => c.id === currentId) : -1;

	let targetIndex: number;
	if (direction === 'up') {
		targetIndex = currentIndex <= 0 ? convs.length - 1 : currentIndex - 1;
	} else {
		targetIndex = currentIndex >= convs.length - 1 ? 0 : currentIndex + 1;
	}

	const target = convs[targetIndex];
	if (target) {
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- programmatic navigation from keyboard shortcut
		goto(`/chat/${target.id}`);
	}
}

function invokeStopAgent(): void {
	const cb = get(onStopAgent);
	if (cb) cb();
}

function invokeExportChat(): void {
	const cb = get(onExportChat);
	if (cb) cb();
}

export const shortcuts: Shortcut[] = [
	{
		keys: ['mod', 'k'],
		label: 'Ctrl+K',
		description: 'Open search',
		category: 'navigation',
		action: openSearch
	},
	{
		keys: ['mod', 'n'],
		label: 'Ctrl+N',
		description: 'New chat',
		category: 'navigation',
		action: navigateNewChat
	},
	{
		keys: ['Escape'],
		label: 'Esc',
		description: 'Close topmost dialog',
		category: 'general',
		action: closeCheatsheet
	},
	{
		keys: ['mod', 'shift', 's'],
		label: 'Ctrl+Shift+S',
		description: 'Toggle sidebar',
		category: 'panels',
		action: toggleSidebar
	},
	{
		keys: ['Enter'],
		label: 'Enter',
		description: 'Send message',
		category: 'chat',
		action: () => {},
		displayOnly: true
	},
	{
		keys: ['shift', 'Enter'],
		label: 'Shift+Enter',
		description: 'New line in message',
		category: 'chat',
		action: () => {},
		displayOnly: true
	},
	{
		keys: ['mod', '.'],
		label: 'Ctrl+.',
		description: 'Stop agent',
		category: 'chat',
		action: invokeStopAgent
	},
	{
		keys: ['mod', 'ArrowUp'],
		label: 'Ctrl+Up',
		description: 'Previous chat',
		category: 'navigation',
		action: () => navigateConversation('up')
	},
	{
		keys: ['mod', 'ArrowDown'],
		label: 'Ctrl+Down',
		description: 'Next chat',
		category: 'navigation',
		action: () => navigateConversation('down')
	},
	{
		keys: ['mod', 'shift', 'c'],
		label: 'Ctrl+Shift+C',
		description: 'Toggle computer panel',
		category: 'panels',
		action: toggleComputerPanel
	},
	{
		keys: ['mod', 'e'],
		label: 'Ctrl+E',
		description: 'Export chat',
		category: 'chat',
		action: invokeExportChat
	},
	{
		keys: ['mod', ','],
		label: 'Ctrl+,',
		description: 'Open settings',
		category: 'general',
		action: openSettings
	},
	{
		keys: ['mod', '/'],
		label: 'Ctrl+/',
		description: 'Open shortcut cheatsheet',
		category: 'general',
		action: toggleCheatsheet
	}
];

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);

/** Format a shortcut label for the current OS */
export function formatLabel(shortcut: Shortcut): string {
	if (isMac) {
		return shortcut.label
			.replace('Ctrl+Shift+', '\u2318\u21E7')
			.replace('Ctrl+', '\u2318')
			.replace('Up', '\u2191')
			.replace('Down', '\u2193');
	}
	return shortcut.label;
}

/** Get the category display name */
export function getCategoryLabel(category: Shortcut['category']): string {
	const labels: Record<Shortcut['category'], string> = {
		navigation: 'Navigation',
		chat: 'Chat',
		panels: 'Panels',
		general: 'General'
	};
	return labels[category];
}

function isInputFocused(): boolean {
	const el = document.activeElement;
	if (!el) return false;
	const tag = el.tagName;
	if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
	if ((el as HTMLElement).isContentEditable) return true;
	return false;
}

function matchesShortcut(e: KeyboardEvent, shortcut: Shortcut): boolean {
	const keys = shortcut.keys;
	const mod = isMac ? e.metaKey : e.ctrlKey;
	const needsMod = keys.includes('mod');
	const needsShift = keys.includes('shift');

	if (needsMod && !mod) return false;
	if (!needsMod && mod) return false;
	if (needsShift && !e.shiftKey) return false;
	if (!needsShift && e.shiftKey && needsMod) return false;

	// Find the actual key (not 'mod' or 'shift')
	const actualKey = keys.find((k) => k !== 'mod' && k !== 'shift');
	if (!actualKey) return false;

	return e.key.toLowerCase() === actualKey.toLowerCase() || e.key === actualKey;
}

export function handleGlobalKeydown(e: KeyboardEvent): void {
	// Escape cascades through overlays: cheatsheet → search → mobile sidebar
	if (e.key === 'Escape') {
		if (get(cheatsheetOpen)) {
			closeCheatsheet();
			e.preventDefault();
			return;
		}
		if (get(searchOpen)) {
			closeSearch();
			e.preventDefault();
			return;
		}
		if (get(sidebarMobileOpen)) {
			closeMobileSidebar();
			e.preventDefault();
			return;
		}
		return;
	}

	// Don't fire shortcuts when typing in inputs
	if (isInputFocused()) return;

	// '?' opens cheatsheet (plain key, no modifier)
	if (e.key === '?') {
		e.preventDefault();
		toggleCheatsheet();
		return;
	}

	for (const shortcut of shortcuts) {
		if (shortcut.keys[0] === 'Escape') continue; // handled above
		if (shortcut.displayOnly) continue; // display-only, handled locally
		if (matchesShortcut(e, shortcut)) {
			e.preventDefault();
			shortcut.action();
			return;
		}
	}
}
