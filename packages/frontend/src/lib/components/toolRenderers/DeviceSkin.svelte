<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		variant?: 'android' | 'iphone';
		/** 1.0 = full realistic size, <1 shrinks via CSS transform. */
		scale?: number;
		children?: Snippet;
	};

	let { variant = 'android', scale = 1, children }: Props = $props();

	// Base body dimensions including bezel — logical phone pixels.
	// iPhone 14/15 Pro: inner screen 390x844; body ≈ 412x892
	// Android Pixel-ish: inner screen 360x780; body ≈ 382x822
	const bodyWidth = $derived(variant === 'iphone' ? 412 : 382);
	const bodyHeight = $derived(variant === 'iphone' ? 892 : 822);

	// The outer wrapper reports the *scaled* size to layout so flex/grid
	// parents lay it out based on visible footprint, not unscaled base.
	const outerWidth = $derived(bodyWidth * scale);
	const outerHeight = $derived(bodyHeight * scale);
</script>

<div
	class="relative inline-block"
	style="width: {outerWidth}px; height: {outerHeight}px;"
	data-testid="device-skin"
	data-variant={variant}
>
	{#if variant === 'iphone'}
		<div
			class="absolute left-0 top-0 rounded-[2.75rem] bg-foreground p-3 shadow-2xl"
			style="width: {bodyWidth}px; height: {bodyHeight}px; transform: scale({scale}); transform-origin: top left;"
		>
			<div class="relative h-full w-full overflow-hidden rounded-[2.25rem] bg-surface-2">
				<!-- Dynamic island -->
				<div
					class="pointer-events-none absolute left-1/2 top-2 z-10 h-7 w-[32%] -translate-x-1/2 rounded-full bg-foreground"
					aria-hidden="true"
				></div>
				<div class="absolute inset-0 h-full w-full">
					{@render children?.()}
				</div>
			</div>
		</div>
	{:else}
		<div
			class="absolute left-0 top-0 rounded-[2rem] bg-foreground p-2.5 shadow-2xl"
			style="width: {bodyWidth}px; height: {bodyHeight}px; transform: scale({scale}); transform-origin: top left;"
		>
			<div class="relative h-full w-full overflow-hidden rounded-[1.75rem] bg-surface-2">
				<!-- Status-bar tint -->
				<div
					class="pointer-events-none absolute inset-x-0 top-0 z-10 h-6 bg-foreground/5"
					aria-hidden="true"
				></div>
				<div class="absolute inset-0 h-full w-full">
					{@render children?.()}
				</div>
				<!-- Home indicator -->
				<div
					class="pointer-events-none absolute bottom-2 left-1/2 z-10 h-1 w-1/3 -translate-x-1/2 rounded-full bg-muted/50"
					aria-hidden="true"
				></div>
			</div>
		</div>
	{/if}
</div>
