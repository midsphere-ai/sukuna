<script lang="ts">
	/**
	 * Parent-side visual overlay for the iframe component selector.
	 *
	 * The iframe-side client (packages/sandbox/templates/_shared/sandbox-selector)
	 * posts `sandbox-selector:hover` and `sandbox-selector:picked` messages with
	 * `boundingRect` values in iframe-document coordinates. This component
	 * renders the actual outline in the parent window — so we get:
	 *   1. Consistent styling using sukuna design tokens.
	 *   2. Overlays visible even when the iframe points at a mock URL that
	 *      doesn't load the selector client (e.g. the dev playground).
	 *   3. A single source of truth for the outline look.
	 *
	 * Positioning strategy: the iframe rect lives in iframe coords, so we track
	 * the parent iframe element's viewport position via ResizeObserver + scroll
	 * listeners and render the overlays with `position: fixed`, translating
	 * iframe coords onto the parent viewport by adding the iframe's top-left.
	 * This handles DeviceSkin padding and any other wrapper chrome transparently
	 * because the iframe element itself is the reference point.
	 */
	import type { Selection, SelectorBoundingRect } from './types';
	import { getFriendlyElementLabel } from './labels';

	interface Props {
		iframeEl: HTMLIFrameElement | null;
		hoverRect: SelectorBoundingRect | null;
		selectedRect: SelectorBoundingRect | null;
		selection: Selection | null;
	}

	let { iframeEl, hoverRect, selectedRect, selection }: Props = $props();

	// Viewport-space position of the iframe element. Updated whenever the
	// iframe moves (scroll, resize, DeviceSkin toggle).
	let iframeViewportX = $state(0);
	let iframeViewportY = $state(0);

	$effect(() => {
		const el = iframeEl;
		if (!el) return;
		const update = (): void => {
			const r = el.getBoundingClientRect();
			iframeViewportX = r.x;
			iframeViewportY = r.y;
		};
		update();
		let ro: ResizeObserver | null = null;
		if (typeof ResizeObserver !== 'undefined') {
			ro = new ResizeObserver(update);
			ro.observe(el);
		}
		window.addEventListener('scroll', update, true);
		window.addEventListener('resize', update);
		return () => {
			if (ro) ro.disconnect();
			window.removeEventListener('scroll', update, true);
			window.removeEventListener('resize', update);
		};
	});

	// Hide the hover outline once a selection is locked — the selected outline
	// already marks the element, and keeping both is noisy.
	const showHover = $derived(hoverRect != null && selectedRect == null);

	// Friendly label for the selected element: prefer its visible text,
	// fall back to a category name ("Heading", "Button", ...).
	const selectedLabel = $derived.by(() => {
		if (!selection) return '';
		return getFriendlyElementLabel(selection);
	});

	// Compact size chip, only for boxes wide enough to fit it without clutter.
	const selectedSize = $derived.by(() => {
		if (!selectedRect || selectedRect.width <= 80) return '';
		return `${Math.round(selectedRect.width)} × ${Math.round(selectedRect.height)}`;
	});

	// If the selected rect sits near the top of the viewport, flip the label
	// below the box instead of above it so it stays on-screen.
	const labelBelow = $derived(selectedRect != null && iframeViewportY + selectedRect.y < 24);
</script>

{#if showHover && hoverRect}
	<div
		class="pointer-events-none fixed z-40 rounded-sm border border-accent/60 transition-[transform,width,height] duration-75"
		style="left: {iframeViewportX + hoverRect.x}px; top: {iframeViewportY +
			hoverRect.y}px; width: {hoverRect.width}px; height: {hoverRect.height}px;"
		data-testid="selection-overlay-hover"
		aria-hidden="true"
	></div>
{/if}

{#if selectedRect}
	<div
		class="pointer-events-none fixed z-40 rounded-sm border-2 border-accent bg-accent/5"
		style="left: {iframeViewportX + selectedRect.x}px; top: {iframeViewportY +
			selectedRect.y}px; width: {selectedRect.width}px; height: {selectedRect.height}px;"
		data-testid="selection-overlay-selected"
		aria-hidden="true"
	>
		{#if selectedLabel}
			<span
				class="pointer-events-none absolute left-0 inline-flex max-w-[200px] items-center gap-1.5 truncate rounded-sm bg-accent px-2 py-0.5 font-sans text-[11px] text-white"
				style={labelBelow ? 'top: 100%; margin-top: 2px;' : 'top: -1.5rem;'}
				data-testid="selection-overlay-label"
			>
				<span class="truncate">{selectedLabel}</span>
				{#if selectedSize}
					<span class="text-[9px] opacity-70">{selectedSize}</span>
				{/if}
			</span>
		{/if}
	</div>
{/if}
