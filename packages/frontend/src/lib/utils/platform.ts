import { browser } from '$app/environment';

/** Whether the app is running inside a Tauri webview (desktop or mobile). */
export function isTauri(): boolean {
	if (!browser) return false;
	return '__TAURI_INTERNALS__' in window;
}

/** Whether this is a Tauri build (compile-time check, tree-shakeable). */
export const IS_TAURI_BUILD = import.meta.env.VITE_TAURI === 'true';

export type Platform = 'web' | 'desktop' | 'android' | 'ios';

/** Detect the current runtime platform. */
export async function getPlatform(): Promise<Platform> {
	if (!isTauri()) return 'web';

	try {
		const { platform } = await import('@tauri-apps/plugin-os');
		const os = await platform();
		if (os === 'android') return 'android';
		if (os === 'ios') return 'ios';
		return 'desktop';
	} catch {
		return 'desktop';
	}
}
