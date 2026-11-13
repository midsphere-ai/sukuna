import { writable, derived, get } from 'svelte/store';
import { browser } from '$app/environment';
import { isTauri } from '$utils/platform';

type OsPlatform = 'macos' | 'windows' | 'linux' | 'web';

export const osPlatform = writable<OsPlatform>('web');
export const isMaximized = writable(false);
export const isMacOS = derived(osPlatform, ($os) => $os === 'macos');

let appWindow: Awaited<
	ReturnType<typeof import('@tauri-apps/api/window').getCurrentWindow>
> | null = null;
let cleanupResize: (() => void) | undefined;

/** Initialize Tauri window state. Call once from root layout. */
export async function initTauriWindow(): Promise<void> {
	if (!browser || !isTauri()) return;

	try {
		const { platform } = await import('@tauri-apps/plugin-os');
		const os = await platform();
		if (os === 'macos') osPlatform.set('macos');
		else if (os === 'windows') osPlatform.set('windows');
		else osPlatform.set('linux');
	} catch {
		osPlatform.set('linux');
	}

	const { getCurrentWindow } = await import('@tauri-apps/api/window');
	appWindow = getCurrentWindow();
	isMaximized.set(await appWindow.isMaximized());

	cleanupResize = await appWindow.onResized(async () => {
		if (appWindow) isMaximized.set(await appWindow.isMaximized());
	});
}

export function destroyTauriWindow(): void {
	cleanupResize?.();
	appWindow = null;
}

export const windowActions = {
	minimize: () => appWindow?.minimize(),
	toggleMaximize: () => {
		if (get(isMaximized)) appWindow?.unmaximize();
		else appWindow?.maximize();
	},
	close: () => appWindow?.close()
};
