import { writable, derived, get } from 'svelte/store';
import { browser } from '$app/environment';
import { debounce } from '$utils/debounce';

const BRANCHES_KEY = 'midsphere-conversation-branches';

export interface BranchInfo {
	branchConversationId: string;
	fromMessageIndex: number;
	createdAt: string;
}

export interface BranchParentInfo {
	parentConversationId: string;
	fromMessageIndex: number;
}

/**
 * Map of parent conversation ID -> array of branch info objects.
 * Persisted to localStorage.
 */
type BranchMap = Record<string, BranchInfo[]>;

function loadBranches(): BranchMap {
	if (!browser) return {};
	try {
		const raw = localStorage.getItem(BRANCHES_KEY);
		if (raw) return JSON.parse(raw) as BranchMap;
	} catch {
		// ignore
	}
	return {};
}

function saveBranches(map: BranchMap): void {
	if (!browser) return;
	try {
		localStorage.setItem(BRANCHES_KEY, JSON.stringify(map));
	} catch {
		// ignore
	}
}

export const branchMap = writable<BranchMap>(loadBranches());

if (browser) {
	branchMap.subscribe(
		debounce((map: BranchMap) => {
			saveBranches(map);
		}, 500)
	);
}

/**
 * Derived: reverse lookup from branch conversation ID to parent info.
 */
export const branchParents = derived(branchMap, ($map) => {
	const parents: Record<string, BranchParentInfo> = {};
	for (const [parentId, branches] of Object.entries($map)) {
		for (const branch of branches) {
			parents[branch.branchConversationId] = {
				parentConversationId: parentId,
				fromMessageIndex: branch.fromMessageIndex
			};
		}
	}
	return parents;
});

/**
 * Register a new branch relationship.
 */
export function addBranch(
	parentConversationId: string,
	branchConversationId: string,
	fromMessageIndex: number
): void {
	branchMap.update((map) => {
		const existing = map[parentConversationId] || [];
		// Avoid duplicates
		if (existing.some((b) => b.branchConversationId === branchConversationId)) {
			return map;
		}
		return {
			...map,
			[parentConversationId]: [
				...existing,
				{
					branchConversationId,
					fromMessageIndex,
					createdAt: new Date().toISOString()
				}
			]
		};
	});
}

/**
 * Get branches for a given conversation (as parent).
 */
export function getBranchesForConversation(conversationId: string): BranchInfo[] {
	const map = get(branchMap);
	return map[conversationId] || [];
}

/**
 * Get parent info for a branch conversation.
 */
export function getParentInfo(conversationId: string): BranchParentInfo | null {
	const parents = get(branchParents);
	return parents[conversationId] || null;
}

/**
 * Get all sibling branches (including self) for a conversation.
 * Returns branches of the parent conversation.
 */
export function getSiblingBranches(conversationId: string): {
	parentId: string;
	branches: BranchInfo[];
} | null {
	const parent = getParentInfo(conversationId);
	if (!parent) return null;
	const branches = getBranchesForConversation(parent.parentConversationId);
	return { parentId: parent.parentConversationId, branches };
}

/**
 * Remove branches when a conversation is deleted.
 */
export function removeBranchesForConversation(conversationId: string): void {
	branchMap.update((map) => {
		const next = { ...map };
		// Remove as parent
		delete next[conversationId];
		// Remove as branch from any parent
		for (const [parentId, branches] of Object.entries(next)) {
			const filtered = branches.filter((b) => b.branchConversationId !== conversationId);
			if (filtered.length === 0) {
				delete next[parentId];
			} else if (filtered.length !== branches.length) {
				next[parentId] = filtered;
			}
		}
		return next;
	});
}
