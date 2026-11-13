import { writable } from 'svelte/store';
import { browser } from '$app/environment';

const OPEN_KEY = 'midsphere-debug-panel-open';
const WIDTH_KEY = 'midsphere-debug-panel-width';
const TAB_KEY = 'midsphere-debug-panel-tab';

export type DebugTab =
	'overview' | 'stream' | 'transport' | 'tokens' | 'sandbox' | 'context' | 'ralph' | 'guards';

const DEFAULT_WIDTH = 380;
const MIN_WIDTH = 280;
const MAX_WIDTH = 720;

function loadOpen(): boolean {
	if (!browser) return false;
	try {
		return localStorage.getItem(OPEN_KEY) === '1';
	} catch {
		return false;
	}
}

function loadWidth(): number {
	if (!browser) return DEFAULT_WIDTH;
	try {
		const raw = localStorage.getItem(WIDTH_KEY);
		if (!raw) return DEFAULT_WIDTH;
		const n = Number(raw);
		if (!Number.isFinite(n)) return DEFAULT_WIDTH;
		return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, n));
	} catch {
		return DEFAULT_WIDTH;
	}
}

function loadTab(): DebugTab {
	if (!browser) return 'overview';
	try {
		const raw = localStorage.getItem(TAB_KEY);
		const valid: DebugTab[] = [
			'overview',
			'stream',
			'transport',
			'tokens',
			'sandbox',
			'context',
			'ralph',
			'guards'
		];
		if (raw && (valid as string[]).includes(raw)) return raw as DebugTab;
		return 'overview';
	} catch {
		return 'overview';
	}
}

export const debugPanelOpen = writable<boolean>(loadOpen());
export const debugPanelWidth = writable<number>(loadWidth());
export const debugPanelTab = writable<DebugTab>(loadTab());

if (browser) {
	debugPanelOpen.subscribe((v) => {
		try {
			localStorage.setItem(OPEN_KEY, v ? '1' : '0');
		} catch {
			// ignore
		}
	});
	debugPanelWidth.subscribe((v) => {
		try {
			localStorage.setItem(WIDTH_KEY, String(Math.round(v)));
		} catch {
			// ignore
		}
	});
	debugPanelTab.subscribe((v) => {
		try {
			localStorage.setItem(TAB_KEY, v);
		} catch {
			// ignore
		}
	});
}

export function toggleDebugPanel(): void {
	debugPanelOpen.update((v) => !v);
}

export function setDebugPanelWidth(width: number): void {
	debugPanelWidth.set(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width)));
}

export { MIN_WIDTH as DEBUG_PANEL_MIN_WIDTH, MAX_WIDTH as DEBUG_PANEL_MAX_WIDTH };
