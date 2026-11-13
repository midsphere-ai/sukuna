import { render, screen, cleanup } from '@testing-library/svelte';
import { describe, it, expect, afterEach, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
	shortcuts,
	cheatsheetOpen,
	handleGlobalKeydown,
	formatLabel,
	getCategoryLabel
} from '$stores/shortcuts';
import { sidebarHidden } from '$stores/sidebar';
import ShortcutsCheatsheet from '$components/layout/ShortcutsCheatsheet.svelte';

beforeEach(() => {
	HTMLDialogElement.prototype.showModal =
		HTMLDialogElement.prototype.showModal ||
		function (this: HTMLDialogElement) {
			this.setAttribute('open', '');
		};
	HTMLDialogElement.prototype.close =
		HTMLDialogElement.prototype.close ||
		function (this: HTMLDialogElement) {
			this.removeAttribute('open');
		};
});

afterEach(() => {
	cleanup();
	cheatsheetOpen.set(false);
	sidebarHidden.set(false);
});

function keydown(opts: KeyboardEventInit): KeyboardEvent {
	const e = new KeyboardEvent('keydown', { ...opts, bubbles: true, cancelable: true });
	return e;
}

describe('shortcuts store', () => {
	it('cheatsheetOpen starts closed', () => {
		expect(get(cheatsheetOpen)).toBe(false);
	});

	it('has all 13 shortcuts defined', () => {
		expect(shortcuts.length).toBe(13);
	});

	it('has shortcuts in all 4 categories', () => {
		const categories = new Set(shortcuts.map((s) => s.category));
		expect(categories.has('navigation')).toBe(true);
		expect(categories.has('chat')).toBe(true);
		expect(categories.has('panels')).toBe(true);
		expect(categories.has('general')).toBe(true);
	});
});

describe('handleGlobalKeydown', () => {
	it('Ctrl+/ toggles cheatsheet open', () => {
		const e = keydown({ key: '/', ctrlKey: true });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(true);
		expect(e.defaultPrevented).toBe(true);
	});

	it('Ctrl+/ toggles cheatsheet closed', () => {
		cheatsheetOpen.set(true);
		const e = keydown({ key: '/', ctrlKey: true });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(false);
	});

	it('Escape closes cheatsheet when open', () => {
		cheatsheetOpen.set(true);
		const e = keydown({ key: 'Escape' });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(false);
		expect(e.defaultPrevented).toBe(true);
	});

	it('Escape does nothing when cheatsheet is closed', () => {
		const e = keydown({ key: 'Escape' });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(false);
		expect(e.defaultPrevented).toBe(false);
	});

	it('Ctrl+Shift+S toggles sidebar', () => {
		expect(get(sidebarHidden)).toBe(false);
		const e = keydown({ key: 'S', ctrlKey: true, shiftKey: true });
		handleGlobalKeydown(e);
		expect(get(sidebarHidden)).toBe(true);
		expect(e.defaultPrevented).toBe(true);
	});

	it('does not fire shortcuts when input is focused', () => {
		const input = document.createElement('input');
		document.body.appendChild(input);
		input.focus();

		const e = keydown({ key: '/', ctrlKey: true });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(false);

		document.body.removeChild(input);
	});

	it('does not fire shortcuts when textarea is focused', () => {
		const textarea = document.createElement('textarea');
		document.body.appendChild(textarea);
		textarea.focus();

		const e = keydown({ key: '/', ctrlKey: true });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(false);

		document.body.removeChild(textarea);
	});

	it('does not fire shortcuts when contenteditable is focused', () => {
		const div = document.createElement('div');
		div.setAttribute('contenteditable', 'true');
		// jsdom needs isContentEditable set explicitly
		Object.defineProperty(div, 'isContentEditable', { value: true, writable: false });
		document.body.appendChild(div);
		div.focus();

		const e = keydown({ key: '/', ctrlKey: true });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(false);

		document.body.removeChild(div);
	});

	it('Escape still works when input is focused', () => {
		cheatsheetOpen.set(true);
		const input = document.createElement('input');
		document.body.appendChild(input);
		input.focus();

		const e = keydown({ key: 'Escape' });
		handleGlobalKeydown(e);
		expect(get(cheatsheetOpen)).toBe(false);

		document.body.removeChild(input);
	});

	it('ignores unregistered key combos', () => {
		const e = keydown({ key: 'z', ctrlKey: true });
		handleGlobalKeydown(e);
		expect(e.defaultPrevented).toBe(false);
	});

	it('Ctrl without modifier key alone does not match', () => {
		const e = keydown({ key: 'a', ctrlKey: false });
		handleGlobalKeydown(e);
		expect(e.defaultPrevented).toBe(false);
	});
});

describe('formatLabel', () => {
	it('returns label unchanged on non-Mac', () => {
		const shortcut = shortcuts.find((s) => s.keys.includes('k'))!;
		// In jsdom, navigator.userAgent does not match Mac
		expect(formatLabel(shortcut)).toBe('Ctrl+K');
	});

	it('formats Shift combo', () => {
		const shortcut = shortcuts.find((s) => s.description === 'Toggle sidebar')!;
		expect(formatLabel(shortcut)).toBe('Ctrl+Shift+S');
	});
});

describe('getCategoryLabel', () => {
	it('returns Navigation for navigation', () => {
		expect(getCategoryLabel('navigation')).toBe('Navigation');
	});

	it('returns Chat for chat', () => {
		expect(getCategoryLabel('chat')).toBe('Chat');
	});

	it('returns Panels for panels', () => {
		expect(getCategoryLabel('panels')).toBe('Panels');
	});

	it('returns General for general', () => {
		expect(getCategoryLabel('general')).toBe('General');
	});
});

describe('ShortcutsCheatsheet component', () => {
	it('renders when cheatsheetOpen is true', () => {
		cheatsheetOpen.set(true);
		render(ShortcutsCheatsheet);
		expect(screen.getByText('Keyboard Shortcuts')).toBeInTheDocument();
	});

	it('shows all category headings', () => {
		cheatsheetOpen.set(true);
		render(ShortcutsCheatsheet);
		expect(screen.getByText('Navigation')).toBeInTheDocument();
		expect(screen.getByText('Chat')).toBeInTheDocument();
		expect(screen.getByText('Panels')).toBeInTheDocument();
		expect(screen.getByText('General')).toBeInTheDocument();
	});

	it('shows shortcut descriptions', () => {
		cheatsheetOpen.set(true);
		render(ShortcutsCheatsheet);
		expect(screen.getByText('Open search')).toBeInTheDocument();
		expect(screen.getByText('New chat')).toBeInTheDocument();
		expect(screen.getByText('Toggle sidebar')).toBeInTheDocument();
		expect(screen.getByText('Export chat')).toBeInTheDocument();
	});

	it('shows shortcut key labels', () => {
		cheatsheetOpen.set(true);
		render(ShortcutsCheatsheet);
		expect(screen.getByText('Ctrl+K')).toBeInTheDocument();
		expect(screen.getByText('Ctrl+N')).toBeInTheDocument();
		// Ctrl+/ appears twice (shortcut list + footer hint), use getAllByText
		expect(screen.getAllByText('Ctrl+/').length).toBeGreaterThanOrEqual(1);
	});

	it('has a close button', () => {
		cheatsheetOpen.set(true);
		render(ShortcutsCheatsheet);
		expect(screen.getByLabelText('Close')).toBeInTheDocument();
	});

	it('shows the toggle hint at the bottom', () => {
		cheatsheetOpen.set(true);
		render(ShortcutsCheatsheet);
		expect(screen.getByText(/to toggle this panel/)).toBeInTheDocument();
	});
});
