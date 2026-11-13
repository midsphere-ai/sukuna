<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface ImageItem {
		id?: string;
		title?: string;
		url?: string;
		snippet?: string;
		image_path?: string;
		display_link?: string;
	}

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let query = $derived(
		(typeof resultObj.query === 'string'
			? (resultObj.query as string)
			: Array.isArray(toolCall.args?.queries) && typeof toolCall.args.queries[0] === 'string'
				? (toolCall.args.queries[0] as string)
				: typeof toolCall.args?.query === 'string'
					? (toolCall.args.query as string)
					: '') ?? ''
	);

	let results = $derived(
		Array.isArray(resultObj.results) ? (resultObj.results as ImageItem[]) : []
	);
	let count = $derived(
		typeof resultObj.count === 'number' ? (resultObj.count as number) : results.length
	);

	// Max 9 tiles inline in a masonry layout (3 columns, variable heights)
	const MAX_TILES = 9;
	let visible = $derived(results.slice(0, MAX_TILES));

	let lightboxOpen = $state(false);
	let lightboxIndex = $state(0);

	function openLightbox(i: number): void {
		lightboxIndex = i;
		lightboxOpen = true;
	}
	function closeLightbox(): void {
		lightboxOpen = false;
	}
	function handleKey(e: KeyboardEvent): void {
		if (!lightboxOpen) return;
		if (e.key === 'Escape') closeLightbox();
		else if (e.key === 'ArrowLeft' && lightboxIndex > 0) lightboxIndex--;
		else if (e.key === 'ArrowRight' && lightboxIndex < results.length - 1) lightboxIndex++;
	}
</script>

<svelte:window onkeydown={handleKey} />

<div class="relative" data-testid="image-search-renderer">
	<div class="mb-2 flex items-center justify-between gap-2">
		{#if query}
			<div class="flex min-w-0 items-center gap-1.5 text-[11px] text-subtle">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="12"
					height="12"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="shrink-0"
				>
					<rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
					<circle cx="9" cy="9" r="2" />
					<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
				</svg>
				<span class="truncate font-mono" data-testid="image-search-query">{query}</span>
			</div>
		{/if}
		{#if isError}
			<span
				class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-accent"
			>
				error
			</span>
		{:else if count > 0}
			<span class="shrink-0 font-mono text-[10px] text-subtle" data-testid="image-search-count">
				{count} image{count === 1 ? '' : 's'}
			</span>
		{/if}
	</div>

	{#if isError}
		<div
			class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
			data-testid="image-search-error"
		>
			<div class="font-mono text-[10px] font-medium uppercase text-accent">
				{envelope.error ?? 'error'}
			</div>
			{#if envelope.message}
				<div class="mt-1 text-[11px] text-foreground">{envelope.message}</div>
			{/if}
			{#if envelope.hint}
				<div class="mt-1 text-[10px] italic text-muted">hint: {envelope.hint}</div>
			{/if}
		</div>
	{:else if visible.length > 0}
		<!-- CSS columns-based masonry: preserves natural aspect ratios -->
		<div class="columns-2 gap-1.5 sm:columns-3 [&>*]:mb-1.5" data-testid="image-search-grid">
			{#each visible as r, i (r.id ?? i)}
				<button
					onclick={() => openLightbox(i)}
					class="group relative block w-full break-inside-avoid overflow-hidden rounded-lg border border-border-subtle bg-surface transition-all hover:border-border-strong hover:shadow-sm"
					data-testid="image-search-tile"
				>
					<img
						src={r.image_path || r.url}
						alt={r.title ?? ''}
						class="block h-auto w-full"
						loading="lazy"
					/>
					{#if r.title}
						<div
							class="absolute inset-x-0 bottom-0 bg-surface-2/90 px-1.5 py-0.5 text-[9px] text-foreground opacity-0 transition-opacity group-hover:opacity-100"
						>
							<p class="truncate">{r.title}</p>
						</div>
					{/if}
				</button>
			{/each}
		</div>
		{#if results.length > MAX_TILES}
			<div class="mt-1 text-right text-[10px] text-subtle">
				+{results.length - MAX_TILES} more
			</div>
		{/if}
	{/if}

	{#if lightboxOpen && results[lightboxIndex]}
		{@const item = results[lightboxIndex]}
		<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
		<div
			class="fixed inset-0 z-50 flex items-center justify-center bg-surface-2/95 p-4 backdrop-blur"
			onclick={closeLightbox}
			onkeydown={(e) => {
				if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') closeLightbox();
			}}
			role="button"
			tabindex="0"
			aria-label="Close image"
			data-testid="image-search-lightbox"
		>
			<div class="relative flex max-h-full max-w-full flex-col items-center gap-3">
				<img
					src={item.image_path || item.url}
					alt={item.title ?? ''}
					class="max-h-[80vh] max-w-full rounded-lg border border-border-subtle object-contain"
				/>
				<div class="text-center text-[12px] text-foreground">
					<div class="font-medium">{item.title ?? ''}</div>
					{#if item.display_link}
						<div class="text-[11px] text-muted">{item.display_link}</div>
					{/if}
					<div class="mt-0.5 text-[10px] text-subtle">
						{lightboxIndex + 1} / {results.length}
					</div>
				</div>
				<button
					onclick={(e) => {
						e.stopPropagation();
						closeLightbox();
					}}
					class="absolute right-0 top-0 rounded-full border border-border-subtle bg-surface p-1.5 text-muted hover:bg-surface-2 hover:text-accent"
					aria-label="Close"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="14"
						height="14"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<path d="M18 6 6 18" />
						<path d="m6 6 12 12" />
					</svg>
				</button>
			</div>
		</div>
	{/if}
</div>
