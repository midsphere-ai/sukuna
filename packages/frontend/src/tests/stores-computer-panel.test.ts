import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

describe('computerPanel store', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it('starts with all panels closed', async () => {
		const {
			computerPanelOpen,
			codeEditorPanelOpen,
			computerPanelMobileOpen,
			codeEditorPanelMobileOpen,
			sidePanelMode,
			sidePanelMobileMode
		} = await import('$stores/computerPanel');
		expect(get(computerPanelOpen)).toBe(false);
		expect(get(codeEditorPanelOpen)).toBe(false);
		expect(get(computerPanelMobileOpen)).toBe(false);
		expect(get(codeEditorPanelMobileOpen)).toBe(false);
		expect(get(sidePanelMode)).toBe('none');
		expect(get(sidePanelMobileMode)).toBe('none');
	});

	it('toggleComputerPanel opens computer mode', async () => {
		const { computerPanelOpen, sidePanelMode, toggleComputerPanel } =
			await import('$stores/computerPanel');
		toggleComputerPanel();
		expect(get(sidePanelMode)).toBe('computer');
		expect(get(computerPanelOpen)).toBe(true);
	});

	it('toggleComputerPanel closes when already computer', async () => {
		const { computerPanelOpen, sidePanelMode, toggleComputerPanel } =
			await import('$stores/computerPanel');
		toggleComputerPanel();
		toggleComputerPanel();
		expect(get(sidePanelMode)).toBe('none');
		expect(get(computerPanelOpen)).toBe(false);
	});

	it('toggleCodeEditorPanel opens editor mode', async () => {
		const { codeEditorPanelOpen, sidePanelMode, toggleCodeEditorPanel } =
			await import('$stores/computerPanel');
		toggleCodeEditorPanel();
		expect(get(sidePanelMode)).toBe('editor');
		expect(get(codeEditorPanelOpen)).toBe(true);
	});

	it('openComputerPanel sets computer mode', async () => {
		const { computerPanelOpen, codeEditorPanelOpen, sidePanelMode, openComputerPanel } =
			await import('$stores/computerPanel');
		openComputerPanel();
		expect(get(sidePanelMode)).toBe('computer');
		expect(get(computerPanelOpen)).toBe(true);
		expect(get(codeEditorPanelOpen)).toBe(false);
	});

	it('closeComputerPanel sets none mode', async () => {
		const { computerPanelOpen, sidePanelMode, openComputerPanel, closeComputerPanel } =
			await import('$stores/computerPanel');
		openComputerPanel();
		closeComputerPanel();
		expect(get(sidePanelMode)).toBe('none');
		expect(get(computerPanelOpen)).toBe(false);
	});

	it('switching from computer to editor closes computer', async () => {
		const {
			computerPanelOpen,
			codeEditorPanelOpen,
			sidePanelMode,
			openComputerPanel,
			toggleCodeEditorPanel
		} = await import('$stores/computerPanel');
		openComputerPanel();
		toggleCodeEditorPanel();
		expect(get(sidePanelMode)).toBe('editor');
		expect(get(computerPanelOpen)).toBe(false);
		expect(get(codeEditorPanelOpen)).toBe(true);
	});

	it('mobile panel functions work independently', async () => {
		const {
			computerPanelMobileOpen,
			codeEditorPanelMobileOpen,
			sidePanelMobileMode,
			openComputerPanelMobile,
			closeComputerPanelMobile,
			openCodeEditorPanelMobile,
			closeCodeEditorPanelMobile
		} = await import('$stores/computerPanel');

		openComputerPanelMobile();
		expect(get(sidePanelMobileMode)).toBe('computer');
		expect(get(computerPanelMobileOpen)).toBe(true);
		expect(get(codeEditorPanelMobileOpen)).toBe(false);

		closeComputerPanelMobile();
		expect(get(sidePanelMobileMode)).toBe('none');

		openCodeEditorPanelMobile();
		expect(get(sidePanelMobileMode)).toBe('editor');
		expect(get(codeEditorPanelMobileOpen)).toBe(true);

		closeCodeEditorPanelMobile();
		expect(get(sidePanelMobileMode)).toBe('none');
	});

	it('openComputerPanelAtIndex sets index, pins, and clears VNC', async () => {
		const {
			computerPanelToolIndex,
			computerPanelPinned,
			computerPanelVncActive,
			openComputerPanelAtIndex
		} = await import('$stores/computerPanel');
		computerPanelVncActive.set(true);
		openComputerPanelAtIndex(5);
		expect(get(computerPanelToolIndex)).toBe(5);
		expect(get(computerPanelPinned)).toBe(true);
		expect(get(computerPanelVncActive)).toBe(false);
	});

	it('default panel width is 480', async () => {
		const { computerPanelWidth } = await import('$stores/computerPanel');
		expect(get(computerPanelWidth)).toBe(480);
	});
});
