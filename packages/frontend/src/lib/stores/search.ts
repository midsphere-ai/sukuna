import { writable } from 'svelte/store';

export const searchOpen = writable(false);

export function openSearch(): void {
	searchOpen.set(true);
}

export function closeSearch(): void {
	searchOpen.set(false);
}

export function toggleSearch(): void {
	searchOpen.update((v) => !v);
}
