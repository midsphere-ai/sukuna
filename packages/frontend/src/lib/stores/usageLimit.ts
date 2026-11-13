import { writable } from 'svelte/store';

export type LimitType =
	'concurrent_tasks' | 'custom_llm' | 'custom_mcp' | 'credits' | 'enterprise_mode' | 'unknown';

export interface UsageLimitInfo {
	limitType: LimitType;
	message: string;
}

function createUsageLimitStore() {
	const { subscribe, set } = writable<UsageLimitInfo | null>(null);

	return {
		subscribe,
		show(info: UsageLimitInfo) {
			set(info);
		},
		dismiss() {
			set(null);
		}
	};
}

export const usageLimitModal = createUsageLimitStore();

// Match error messages from the backend to limit types
const LIMIT_PATTERNS: [RegExp, LimitType][] = [
	[/insufficient credits/i, 'credits'],
	[/concurrent tasks/i, 'concurrent_tasks'],
	[/cannot use custom llm/i, 'custom_llm'],
	[/cannot use custom mcp/i, 'custom_mcp'],
	[/enterprise features require a paid subscription/i, 'enterprise_mode']
];

export function detectLimitError(message: string): UsageLimitInfo | null {
	for (const [pattern, limitType] of LIMIT_PATTERNS) {
		if (pattern.test(message)) {
			return { limitType, message };
		}
	}
	return null;
}
