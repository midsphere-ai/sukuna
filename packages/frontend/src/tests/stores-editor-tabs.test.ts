import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock sandbox API
const mockReadSandboxFile = vi.fn();
const mockWriteSandboxFile = vi.fn();
vi.mock('$api/sandbox', () => ({
	readSandboxFile: (...args: unknown[]) => mockReadSandboxFile(...args),
	writeSandboxFile: (...args: unknown[]) => mockWriteSandboxFile(...args)
}));

describe('editorTabs store', () => {
	beforeEach(async () => {
		vi.resetModules();
		vi.useFakeTimers();
		mockReadSandboxFile.mockReset();
		mockWriteSandboxFile.mockReset();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('starts with no tabs', async () => {
		const { editorTabs, activeTabPath } = await import('$stores/editorTabs');
		expect(get(editorTabs)).toEqual([]);
		expect(get(activeTabPath)).toBeNull();
	});

	it('openTab creates a tab and loads content', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'hello world' });
		const { editorTabs, activeTabPath, openTab } = await import('$stores/editorTabs');

		await openTab('conv-1', '/src/index.ts');

		const tabs = get(editorTabs);
		expect(tabs).toHaveLength(1);
		expect(tabs[0].path).toBe('/src/index.ts');
		expect(tabs[0].language).toBe('typescript');
		expect(tabs[0].content).toBe('hello world');
		expect(tabs[0].savedContent).toBe('hello world');
		expect(tabs[0].loading).toBe(false);
		expect(tabs[0].dirty).toBe(false);
		expect(get(activeTabPath)).toBe('/src/index.ts');
	});

	it('openTab switches to existing tab', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'code' });
		const { activeTabPath, openTab } = await import('$stores/editorTabs');

		await openTab('conv-1', '/src/a.ts');
		await openTab('conv-1', '/src/b.ts');
		await openTab('conv-1', '/src/a.ts');

		expect(get(activeTabPath)).toBe('/src/a.ts');
	});

	it('openTab handles API errors', async () => {
		mockReadSandboxFile.mockRejectedValue(new Error('Not found'));
		const { editorTabs, openTab } = await import('$stores/editorTabs');

		await openTab('conv-1', '/missing.txt');

		const tabs = get(editorTabs);
		expect(tabs[0].loading).toBe(false);
		expect(tabs[0].error).toBe('Not found');
	});

	it('closeTab removes tab and adjusts active', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: '' });
		const { editorTabs, activeTabPath, openTab, closeTab } = await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		await openTab('conv-1', '/b.ts');
		expect(get(activeTabPath)).toBe('/b.ts');

		closeTab('/b.ts');
		expect(get(editorTabs)).toHaveLength(1);
		expect(get(activeTabPath)).toBe('/a.ts');
	});

	it('closeTab last tab sets active to null', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: '' });
		const { editorTabs, activeTabPath, openTab, closeTab } = await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		closeTab('/a.ts');
		expect(get(editorTabs)).toHaveLength(0);
		expect(get(activeTabPath)).toBeNull();
	});

	it('markTabDirty sets dirty flag', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'original' });
		const { editorTabs, openTab, markTabDirty } = await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		markTabDirty('conv-1', '/a.ts', 'modified');

		const tab = get(editorTabs)[0];
		expect(tab.dirty).toBe(true);
		expect(tab.content).toBe('modified');
	});

	it('markTabDirty with same content as saved clears dirty', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'original' });
		const { editorTabs, openTab, markTabDirty } = await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		markTabDirty('conv-1', '/a.ts', 'modified');
		markTabDirty('conv-1', '/a.ts', 'original');

		expect(get(editorTabs)[0].dirty).toBe(false);
	});

	it('markTabDirty triggers auto-save after 1s', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'original' });
		mockWriteSandboxFile.mockResolvedValue({ success: true });
		const { openTab, markTabDirty } = await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		markTabDirty('conv-1', '/a.ts', 'changed');

		expect(mockWriteSandboxFile).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1000);
		expect(mockWriteSandboxFile).toHaveBeenCalledWith('conv-1', '/a.ts', 'changed');
	});

	it('updateTabContent updates non-dirty tab', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'original' });
		const { editorTabs, openTab, updateTabContent } = await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		updateTabContent('/a.ts', 'agent change');

		const tab = get(editorTabs)[0];
		expect(tab.content).toBe('agent change');
		expect(tab.savedContent).toBe('agent change');
		expect(tab.conflict).toBeNull();
	});

	it('updateTabContent sets conflict on dirty tab', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'original' });
		const { editorTabs, openTab, markTabDirty, updateTabContent } =
			await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		markTabDirty('conv-1', '/a.ts', 'my edit');
		updateTabContent('/a.ts', 'agent edit');

		const tab = get(editorTabs)[0];
		expect(tab.content).toBe('my edit');
		expect(tab.conflict).toEqual({ serverContent: 'agent edit' });
	});

	it('resolveConflict with theirs takes server content', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'original' });
		const { editorTabs, openTab, markTabDirty, updateTabContent, resolveConflict } =
			await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		markTabDirty('conv-1', '/a.ts', 'my edit');
		updateTabContent('/a.ts', 'agent edit');
		resolveConflict('conv-1', '/a.ts', 'theirs');

		const tab = get(editorTabs)[0];
		expect(tab.content).toBe('agent edit');
		expect(tab.dirty).toBe(false);
		expect(tab.conflict).toBeNull();
	});

	it('resolveConflict with mine keeps user content and saves', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: 'original' });
		mockWriteSandboxFile.mockResolvedValue({ success: true });
		const { editorTabs, openTab, markTabDirty, updateTabContent, resolveConflict } =
			await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		markTabDirty('conv-1', '/a.ts', 'my edit');
		updateTabContent('/a.ts', 'agent edit');
		resolveConflict('conv-1', '/a.ts', 'mine');

		const tab = get(editorTabs)[0];
		expect(tab.content).toBe('my edit');
		expect(tab.conflict).toBeNull();
	});

	it('closeAllTabs clears everything', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: '' });
		const { editorTabs, activeTabPath, openTab, closeAllTabs } = await import('$stores/editorTabs');

		await openTab('conv-1', '/a.ts');
		await openTab('conv-1', '/b.py');
		closeAllTabs();

		expect(get(editorTabs)).toEqual([]);
		expect(get(activeTabPath)).toBeNull();
	});

	it('detects language from file extension', async () => {
		mockReadSandboxFile.mockResolvedValue({ content: '' });
		const { editorTabs, openTab } = await import('$stores/editorTabs');

		await openTab('conv-1', '/test.py');
		expect(get(editorTabs)[0].language).toBe('python');

		await openTab('conv-1', '/test.js');
		const jsTab = get(editorTabs).find((t) => t.path === '/test.js');
		expect(jsTab?.language).toBe('javascript');

		await openTab('conv-1', '/test.rs');
		const rsTab = get(editorTabs).find((t) => t.path === '/test.rs');
		expect(rsTab?.language).toBe('rust');

		await openTab('conv-1', '/test.xyz');
		const unknownTab = get(editorTabs).find((t) => t.path === '/test.xyz');
		expect(unknownTab?.language).toBe('text');
	});

	it('agentExecuting and editorWordWrap have defaults', async () => {
		const { agentExecuting, editorWordWrap } = await import('$stores/editorTabs');
		expect(get(agentExecuting)).toBe(false);
		expect(get(editorWordWrap)).toBe(false);
	});
});
