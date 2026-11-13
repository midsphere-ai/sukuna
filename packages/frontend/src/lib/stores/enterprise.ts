import { derived, writable, type Readable } from 'svelte/store';
import { currentUser } from '$stores/auth';
import type { User } from '$api/types';

/**
 * Derived store that reflects whether enterprise mode is enabled for the
 * current user.  The source of truth is the `enterprise_mode` field on the
 * User object returned by `/users/me`.  No separate API call needed — the
 * value is refreshed automatically whenever `currentUser` updates.
 */
const fallbackCurrentUser = writable<User | null>(null);
const currentUserStore: Readable<User | null> = currentUser ?? fallbackCurrentUser;

export const enterpriseMode = derived(currentUserStore, ($user) => $user?.enterprise_mode ?? false);
