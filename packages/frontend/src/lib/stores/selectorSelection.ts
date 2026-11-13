import { writable } from 'svelte/store';
import type { Selection } from '$lib/components/toolRenderers/selector/types';

/**
 * Active element selection from the in-preview component selector.
 *
 * When a user picks an element in the PreviewCanvas iframe, the canvas
 * writes the Selection here. The chat input subscribes and renders a
 * context chip above the textarea, and prepends a `[Selected: ...]`
 * marker to any message sent while a selection is active.
 *
 * Lifecycle:
 * - set on `sandbox-selector:picked` / `:restored`
 * - cleared on `:cleared`, on selector toggle-off, on canvas destroy,
 *   and via the chip's × button (see `clearSelectorSelection`).
 */
export const activeSelectorSelection = writable<Selection | null>(null);

export function clearSelectorSelection(): void {
	activeSelectorSelection.set(null);
}
