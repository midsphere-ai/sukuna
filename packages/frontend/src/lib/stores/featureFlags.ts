import { writable, derived, type Readable } from 'svelte/store';
import { browser } from '$app/environment';

const STORAGE_KEY = 'midsphere-feature-flags';

// Tri-state: null = default, true = force-enabled, false = force-disabled
export type FlagState = boolean | null;

export interface FeatureFlag {
	id: string;
	name: string;
	description: string;
	state: FlagState;
	defaultValue: boolean;
}

interface FlagDefinition {
	id: string;
	name: string;
	description: string;
	defaultValue: boolean;
}

const FLAG_DEFINITIONS: FlagDefinition[] = [
	{
		id: 'debug-mode',
		name: 'Debug Mode',
		description:
			'Show debug information in the UI including request IDs, timing data, and model metadata in chat messages.',
		defaultValue: false
	},
	{
		id: 'experimental-markdown',
		name: 'Experimental Markdown Renderer',
		description:
			'Use the new markdown rendering engine with improved code block highlighting and LaTeX support.',
		defaultValue: false
	},
	{
		id: 'compact-sidebar',
		name: 'Compact Sidebar',
		description:
			'Reduce spacing in sidebar conversation list to show more items without scrolling.',
		defaultValue: false
	},
	{
		id: 'show-token-usage',
		name: 'Show Token Usage',
		description: 'Display token count and cost estimate for each conversation message.',
		defaultValue: false
	},
	{
		id: 'keyboard-vim-mode',
		name: 'Vim Keybindings',
		description: 'Enable vim-style keybindings in the message input area.',
		defaultValue: false
	},
	{
		id: 'auto-scroll-lock',
		name: 'Smart Auto-Scroll',
		description:
			'Pause auto-scrolling when you scroll up during streaming, resume when you scroll back to bottom.',
		defaultValue: false
	},
	{
		id: 'enable-local-mode',
		name: 'Local Mode',
		description: 'Show local agent server configuration in Advanced settings.',
		defaultValue: true
	},
	{
		id: 'enable-claw',
		name: 'Claw',
		description: 'Enable Claw persistent sandbox with Telegram and Slack integration.',
		defaultValue: true
	},
	{
		id: 'enable-skills',
		name: 'Skills Marketplace',
		description: 'Enable skill catalog browsing and installation.',
		defaultValue: true
	},
	{
		id: 'enable-connectors',
		name: 'Connectors',
		description: 'Enable addon marketplace and connector management.',
		defaultValue: true
	},
	{
		id: 'enable-custom-mcp',
		name: 'Custom MCP Servers',
		description: 'Show custom Model Context Protocol server configuration in Advanced settings.',
		defaultValue: true
	},
	{
		id: 'enable-projects',
		name: 'Projects',
		description: 'Enable project organization and grouping.',
		defaultValue: true
	},
	{
		id: 'enable-library',
		name: 'Library',
		description: 'Enable shared conversation library.',
		defaultValue: true
	}
];

function loadFlags(): FeatureFlag[] {
	let stored: Record<string, FlagState> = {};
	if (browser) {
		try {
			const raw = localStorage.getItem(STORAGE_KEY);
			if (raw) stored = JSON.parse(raw);
		} catch {
			// ignore
		}
	}

	return FLAG_DEFINITIONS.map((def) => ({
		...def,
		state: stored[def.id] ?? null
	}));
}

function persistFlags(flags: FeatureFlag[]): void {
	if (!browser) return;
	try {
		const data: Record<string, FlagState> = {};
		for (const flag of flags) {
			if (flag.state !== null) {
				data[flag.id] = flag.state;
			}
		}
		localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
	} catch {
		// ignore
	}
}

export const featureFlags = writable<FeatureFlag[]>(loadFlags());

export const modifiedCount = derived(
	featureFlags,
	($flags) => $flags.filter((f) => f.state !== null).length
);

export function setFlagState(id: string, state: FlagState): void {
	featureFlags.update((flags) => {
		const updated = flags.map((f) => (f.id === id ? { ...f, state } : f));
		persistFlags(updated);
		return updated;
	});
}

export function resetFlag(id: string): void {
	setFlagState(id, null);
}

export function resetAllFlags(): void {
	featureFlags.update((flags) => {
		const updated = flags.map((f) => ({ ...f, state: null }));
		persistFlags(updated);
		return updated;
	});
}

/**
 * Returns a derived store that resolves to true/false for a given flag.
 * Usage: const debug = flagEnabled('debug-mode'); then use $debug in templates.
 */
export function flagEnabled(id: string): Readable<boolean> {
	return derived(featureFlags, ($flags) => {
		const flag = $flags.find((f) => f.id === id);
		if (!flag) return false;
		return flag.state === null ? flag.defaultValue : flag.state;
	});
}
