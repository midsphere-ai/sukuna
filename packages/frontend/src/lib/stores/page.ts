import { writable } from 'svelte/store';

/** Current page title displayed in the global header */
export const pageTitle = writable('Home');

/** When false, the global header hides its title (page renders its own) */
export const showHeaderTitle = writable(true);

/** Config for the global-header search input. Null hides it. */
export interface HeaderSearchConfig {
	placeholder: string;
	/** Optional keyboard shortcut badge to display inside the input (e.g. "⌘F"). */
	shortcut?: string;
	/** DOM id so pages can focus-shift via document.getElementById. */
	inputId?: string;
}
export const headerSearchConfig = writable<HeaderSearchConfig | null>(null);

/** Live value of the global-header search input. Pages subscribe to this to filter. */
export const headerSearchValue = writable('');

/** Config for the global-header filter button. Null hides it. */
export interface HeaderFilterConfig {
	label?: string;
	onClick: () => void;
}
export const headerFilterConfig = writable<HeaderFilterConfig | null>(null);

/** When true, the global app header is hidden. Used by pages that render
 *  a full-screen overlay (e.g. the Tasks drawer) so the header doesn't
 *  bleed through behind it. */
export const headerHidden = writable(false);
