import { writable } from 'svelte/store';

/** Whether the sidebar is completely hidden (desktop) */
export const sidebarHidden = writable(false);

/** Whether the sidebar overlay is open (mobile) */
export const sidebarMobileOpen = writable(false);

/** Whether the full-screen mobile navigation page is open */
export const mobileNavOpen = writable(false);

export function toggleSidebar(): void {
	sidebarHidden.update((v) => !v);
}

export function openMobileSidebar(): void {
	sidebarMobileOpen.set(true);
}

export function closeMobileSidebar(): void {
	sidebarMobileOpen.set(false);
}

export function openMobileNav(): void {
	mobileNavOpen.set(true);
}

export function closeMobileNav(): void {
	mobileNavOpen.set(false);
}
