import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock localStorage
const mockStorage: Record<string, string> = {};
vi.stubGlobal('localStorage', {
	getItem: vi.fn((key: string) => mockStorage[key] ?? null),
	setItem: vi.fn((key: string, value: string) => {
		mockStorage[key] = value;
	}),
	removeItem: vi.fn((key: string) => {
		delete mockStorage[key];
	}),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

describe('workspaceLayout store', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	});

	it('starts with defaults', async () => {
		const { workspaceLayout } = await import('$stores/workspaceLayout');
		const state = get(workspaceLayout);
		expect(state.fileExplorerWidth).toBe(240);
		expect(state.chatWidth).toBe(380);
		expect(state.fileExplorerCollapsed).toBe(false);
		expect(state.chatCollapsed).toBe(false);
		expect(state.editorCollapsed).toBe(false);
		expect(state.mobileTab).toBe('chat');
	});

	it('setFileExplorerWidth clamps between 160 and 400', async () => {
		const { workspaceLayout, setFileExplorerWidth } = await import('$stores/workspaceLayout');
		setFileExplorerWidth(100);
		expect(get(workspaceLayout).fileExplorerWidth).toBe(160);
		setFileExplorerWidth(500);
		expect(get(workspaceLayout).fileExplorerWidth).toBe(400);
		setFileExplorerWidth(300);
		expect(get(workspaceLayout).fileExplorerWidth).toBe(300);
	});

	it('setChatWidth clamps minimum at 320 with no upper bound', async () => {
		const { workspaceLayout, setChatWidth } = await import('$stores/workspaceLayout');
		setChatWidth(100);
		expect(get(workspaceLayout).chatWidth).toBe(320);
		setChatWidth(1200);
		expect(get(workspaceLayout).chatWidth).toBe(1200);
		setChatWidth(450);
		expect(get(workspaceLayout).chatWidth).toBe(450);
	});

	it('toggleFileExplorer toggles collapsed state', async () => {
		const { workspaceLayout, toggleFileExplorer } = await import('$stores/workspaceLayout');
		expect(get(workspaceLayout).fileExplorerCollapsed).toBe(false);
		toggleFileExplorer();
		expect(get(workspaceLayout).fileExplorerCollapsed).toBe(true);
		toggleFileExplorer();
		expect(get(workspaceLayout).fileExplorerCollapsed).toBe(false);
	});

	it('toggleChat toggles collapsed state', async () => {
		const { workspaceLayout, toggleChat } = await import('$stores/workspaceLayout');
		toggleChat();
		expect(get(workspaceLayout).chatCollapsed).toBe(true);
		toggleChat();
		expect(get(workspaceLayout).chatCollapsed).toBe(false);
	});

	it('toggleEditor toggles collapsed state', async () => {
		const { workspaceLayout, toggleEditor } = await import('$stores/workspaceLayout');
		toggleEditor();
		expect(get(workspaceLayout).editorCollapsed).toBe(true);
	});

	it('setMobileTab sets mobile tab', async () => {
		const { workspaceLayout, setMobileTab } = await import('$stores/workspaceLayout');
		setMobileTab('files');
		expect(get(workspaceLayout).mobileTab).toBe('files');
		setMobileTab('editor');
		expect(get(workspaceLayout).mobileTab).toBe('editor');
	});

	it('collapsePane collapses specific pane', async () => {
		const { workspaceLayout, collapsePane } = await import('$stores/workspaceLayout');
		collapsePane('fileExplorer');
		expect(get(workspaceLayout).fileExplorerCollapsed).toBe(true);
		expect(get(workspaceLayout).chatCollapsed).toBe(false);

		collapsePane('chat');
		expect(get(workspaceLayout).chatCollapsed).toBe(true);

		collapsePane('editor');
		expect(get(workspaceLayout).editorCollapsed).toBe(true);
	});

	it('expandPane expands specific pane', async () => {
		const { workspaceLayout, collapsePane, expandPane } = await import('$stores/workspaceLayout');
		collapsePane('fileExplorer');
		collapsePane('chat');
		expandPane('fileExplorer');
		expect(get(workspaceLayout).fileExplorerCollapsed).toBe(false);
		expect(get(workspaceLayout).chatCollapsed).toBe(true);
	});

	it('resetWorkspaceLayout restores defaults', async () => {
		const { workspaceLayout, setChatWidth, toggleFileExplorer, resetWorkspaceLayout } =
			await import('$stores/workspaceLayout');
		setChatWidth(500);
		toggleFileExplorer();
		resetWorkspaceLayout();
		const state = get(workspaceLayout);
		expect(state.chatWidth).toBe(380);
		expect(state.fileExplorerCollapsed).toBe(false);
	});

	it('persists state to localStorage', async () => {
		const { setChatWidth } = await import('$stores/workspaceLayout');
		setChatWidth(500);
		expect(mockStorage['midsphere-workspace-layout']).toBeDefined();
		const stored = JSON.parse(mockStorage['midsphere-workspace-layout']);
		expect(stored.chatWidth).toBe(500);
	});

	it('loads from localStorage on init', async () => {
		mockStorage['midsphere-workspace-layout'] = JSON.stringify({
			fileExplorerWidth: 300,
			chatWidth: 500,
			mobileTab: 'files'
		});
		const { workspaceLayout } = await import('$stores/workspaceLayout');
		const state = get(workspaceLayout);
		expect(state.fileExplorerWidth).toBe(300);
		expect(state.chatWidth).toBe(500);
		expect(state.mobileTab).toBe('files');
		// Defaults for missing fields
		expect(state.fileExplorerCollapsed).toBe(false);
	});
});
