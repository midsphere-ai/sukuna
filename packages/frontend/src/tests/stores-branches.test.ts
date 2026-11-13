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

describe('branches store', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	});

	it('starts with empty branch map', async () => {
		const { branchMap } = await import('$stores/branches');
		expect(get(branchMap)).toEqual({});
	});

	it('addBranch registers a branch', async () => {
		const { branchMap, addBranch } = await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 3);
		const map = get(branchMap);
		expect(map['parent-1']).toHaveLength(1);
		expect(map['parent-1'][0].branchConversationId).toBe('branch-1');
		expect(map['parent-1'][0].fromMessageIndex).toBe(3);
	});

	it('addBranch avoids duplicates', async () => {
		const { branchMap, addBranch } = await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 3);
		addBranch('parent-1', 'branch-1', 3);
		expect(get(branchMap)['parent-1']).toHaveLength(1);
	});

	it('branchParents provides reverse lookup', async () => {
		const { branchParents, addBranch } = await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 3);
		addBranch('parent-1', 'branch-2', 5);
		const parents = get(branchParents);
		expect(parents['branch-1']).toEqual({
			parentConversationId: 'parent-1',
			fromMessageIndex: 3
		});
		expect(parents['branch-2']).toEqual({
			parentConversationId: 'parent-1',
			fromMessageIndex: 5
		});
	});

	it('getBranchesForConversation returns branches', async () => {
		const { addBranch, getBranchesForConversation } = await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 0);
		addBranch('parent-1', 'branch-2', 2);
		const branches = getBranchesForConversation('parent-1');
		expect(branches).toHaveLength(2);
	});

	it('getBranchesForConversation returns empty array for unknown id', async () => {
		const { getBranchesForConversation } = await import('$stores/branches');
		expect(getBranchesForConversation('unknown')).toEqual([]);
	});

	it('getParentInfo returns parent for known branch', async () => {
		const { addBranch, getParentInfo } = await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 4);
		expect(getParentInfo('branch-1')).toEqual({
			parentConversationId: 'parent-1',
			fromMessageIndex: 4
		});
	});

	it('getParentInfo returns null for unknown conversation', async () => {
		const { getParentInfo } = await import('$stores/branches');
		expect(getParentInfo('unknown')).toBeNull();
	});

	it('getSiblingBranches returns all siblings', async () => {
		const { addBranch, getSiblingBranches } = await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 3);
		addBranch('parent-1', 'branch-2', 5);
		const result = getSiblingBranches('branch-1');
		expect(result).not.toBeNull();
		expect(result!.parentId).toBe('parent-1');
		expect(result!.branches).toHaveLength(2);
	});

	it('getSiblingBranches returns null for non-branch', async () => {
		const { getSiblingBranches } = await import('$stores/branches');
		expect(getSiblingBranches('parent-1')).toBeNull();
	});

	it('removeBranchesForConversation removes as parent', async () => {
		const { branchMap, addBranch, removeBranchesForConversation } =
			await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 0);
		removeBranchesForConversation('parent-1');
		expect(get(branchMap)['parent-1']).toBeUndefined();
	});

	it('removeBranchesForConversation removes as branch from parent', async () => {
		const { branchMap, addBranch, removeBranchesForConversation } =
			await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 0);
		addBranch('parent-1', 'branch-2', 2);
		removeBranchesForConversation('branch-1');
		const map = get(branchMap);
		expect(map['parent-1']).toHaveLength(1);
		expect(map['parent-1'][0].branchConversationId).toBe('branch-2');
	});

	it('removeBranchesForConversation cleans up empty parent entries', async () => {
		const { branchMap, addBranch, removeBranchesForConversation } =
			await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 0);
		removeBranchesForConversation('branch-1');
		expect(get(branchMap)['parent-1']).toBeUndefined();
	});

	it('persists to localStorage', async () => {
		const { addBranch } = await import('$stores/branches');
		addBranch('parent-1', 'branch-1', 0);
		expect(mockStorage['midsphere-conversation-branches']).toBeDefined();
		const stored = JSON.parse(mockStorage['midsphere-conversation-branches']);
		expect(stored['parent-1']).toHaveLength(1);
	});
});
