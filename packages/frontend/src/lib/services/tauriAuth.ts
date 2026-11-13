import { isTauri } from '$utils/platform';

/**
 * Start Google OAuth via system browser + deep link callback.
 * Uses implicit flow to get id_token directly (no backend code exchange needed).
 * For Tauri desktop/mobile only.
 */
export async function startGoogleOAuthNative(): Promise<string | null> {
	if (!isTauri()) return null;

	const { open } = await import('@tauri-apps/plugin-shell');
	const { onOpenUrl } = await import('@tauri-apps/plugin-deep-link');

	const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
	if (!clientId) return null;

	const nonce = crypto.randomUUID();
	const redirectUri = 'midsphere://auth/callback';

	const authUrl = new URL('https://accounts.google.com/o/oauth2/v2/auth');
	authUrl.searchParams.set('client_id', clientId);
	authUrl.searchParams.set('redirect_uri', redirectUri);
	authUrl.searchParams.set('response_type', 'id_token');
	authUrl.searchParams.set('scope', 'openid email profile');
	authUrl.searchParams.set('nonce', nonce);

	// Open system browser for OAuth
	await open(authUrl.toString());

	// Wait for deep link callback with id_token
	return new Promise((resolve) => {
		const cleanup = onOpenUrl((urls) => {
			for (const url of urls) {
				try {
					// id_token comes in URL fragment: midsphere://auth/callback#id_token=...
					const hash = url.includes('#') ? url.split('#')[1] : '';
					const params = new URLSearchParams(hash);
					const idToken = params.get('id_token');
					if (idToken) {
						cleanup.then((unlisten) => unlisten());
						resolve(idToken);
						return;
					}
				} catch {
					// Ignore malformed URLs
				}
			}
		});

		// Timeout after 5 minutes
		setTimeout(() => {
			cleanup.then((unlisten) => unlisten());
			resolve(null);
		}, 300_000);
	});
}
