import { writable, derived } from 'svelte/store';
import { browser } from '$app/environment';
import type { User } from '$api/types';
import { resetAllUserStores } from '$stores/resetAllStores';

const TOKEN_KEY = 'midsphere-auth-token';
const PERSIST_KEY = 'midsphere-persist-session';

function loadPersistSession(): boolean {
	if (!browser) return false;
	try {
		if (typeof localStorage?.getItem !== 'function') return false;
		return localStorage.getItem(PERSIST_KEY) === 'true';
	} catch {
		return false;
	}
}

export const persistSession = writable<boolean>(loadPersistSession());

function loadToken(): string | null {
	if (!browser) return null;
	try {
		const persist = localStorage.getItem(PERSIST_KEY) === 'true';
		if (persist) {
			return localStorage.getItem(TOKEN_KEY);
		}
		return sessionStorage.getItem(TOKEN_KEY);
	} catch {
		return null;
	}
}

function saveToken(token: string | null, persist?: boolean): void {
	if (!browser) return;
	try {
		if (token) {
			if (persist) {
				localStorage.setItem(TOKEN_KEY, token);
				sessionStorage.removeItem(TOKEN_KEY);
				localStorage.setItem(PERSIST_KEY, 'true');
			} else {
				sessionStorage.setItem(TOKEN_KEY, token);
				localStorage.removeItem(TOKEN_KEY);
				localStorage.removeItem(PERSIST_KEY);
			}
		} else {
			sessionStorage.removeItem(TOKEN_KEY);
			localStorage.removeItem(TOKEN_KEY);
			localStorage.removeItem(PERSIST_KEY);
		}
	} catch {
		// storage may be unavailable
	}
}

export const authToken = writable<string | null>(loadToken());
export const currentUser = writable<User | null>(null);
export const authLoading = writable<boolean>(true);

export const isAuthenticated = derived(authToken, ($token) => $token !== null);

export function setAuth(token: string, user?: User, rememberMe?: boolean): void {
	saveToken(token, rememberMe);
	authToken.set(token);
	if (user) {
		currentUser.set(user);
	}
}

// Guard against multiple concurrent clearAuth calls triggering multiple redirects
let clearingAuth = false;

export function clearAuth(): void {
	if (clearingAuth) return;
	clearingAuth = true;
	resetAllUserStores();
	authToken.set(null);
	currentUser.set(null);
	authLoading.set(false);
	saveToken(null);
	queueMicrotask(() => {
		clearingAuth = false;
	});
}
