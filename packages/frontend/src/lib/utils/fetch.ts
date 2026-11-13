import { isTauri } from '$utils/platform';

let _tauriFetch: typeof globalThis.fetch | null = null;

/**
 * Returns the appropriate fetch function.
 * In Tauri: @tauri-apps/plugin-http (bypasses CORS).
 * In browser: native fetch.
 */
export async function getFetch(): Promise<typeof globalThis.fetch> {
	if (!isTauri()) return globalThis.fetch;
	if (_tauriFetch) return _tauriFetch;
	const { fetch } = await import('@tauri-apps/plugin-http');
	_tauriFetch = fetch;
	return fetch;
}
