<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';
	import { renderMarkdown } from '$lib/utils/markdown';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface SearchResultItem {
		id?: string;
		title?: string;
		url?: string;
		snippet?: string;
		source?: string;
		display_link?: string;
		formatted_url?: string;
		image_path?: string;
		hint?: string;
	}

	const SEARCH_TYPES = new Set([
		'info',
		'image',
		'news',
		'research',
		'api',
		'tool',
		'data',
		'youtube_video',
		'wikipedia_search',
		'wikipedia_article',
		'wikipedia_summary',
		'wikipedia_history',
		// Legacy aliases
		'web',
		'images'
	]);

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let rawType = $derived(
		typeof toolCall.args?.type === 'string' ? (toolCall.args.type as string) : 'info'
	);
	// Normalize legacy type names
	const TYPE_NORMALIZE: Record<string, string> = { web: 'info', images: 'image' };
	let type = $derived(SEARCH_TYPES.has(rawType) ? (TYPE_NORMALIZE[rawType] ?? rawType) : 'info');

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
		Array.isArray(resultObj.results) ? (resultObj.results as SearchResultItem[]) : []
	);
	let count = $derived(
		typeof resultObj.count === 'number' ? (resultObj.count as number) : results.length
	);

	// Wikipedia article fields
	let articleTitle = $derived(
		typeof resultObj.title === 'string' ? (resultObj.title as string) : ''
	);
	let articleUrl = $derived(typeof resultObj.url === 'string' ? (resultObj.url as string) : '');
	let articleSummary = $derived(
		typeof resultObj.summary === 'string' ? (resultObj.summary as string) : ''
	);
	let articleContent = $derived(
		typeof resultObj.content === 'string' ? (resultObj.content as string) : ''
	);
	let articleSections = $derived(
		Array.isArray(resultObj.sections) ? (resultObj.sections as string[]) : []
	);

	// Wikipedia history fields
	let historyEditor = $derived(
		typeof resultObj.editor === 'string' ? (resultObj.editor as string) : ''
	);
	let historyComment = $derived(
		typeof resultObj.comment === 'string' ? (resultObj.comment as string) : ''
	);
	let historyActualDate = $derived(
		typeof resultObj.actual_date === 'string' ? (resultObj.actual_date as string) : ''
	);
	let historyRequestedDate = $derived(
		typeof resultObj.requested_date === 'string' ? (resultObj.requested_date as string) : ''
	);

	// YouTube video fields
	let ytFileName = $derived(
		typeof resultObj.file_name === 'string' ? (resultObj.file_name as string) : ''
	);
	let ytFilePath = $derived(
		typeof resultObj.file_path === 'string' ? (resultObj.file_path as string) : ''
	);

	// Lightbox
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

	let sectionsExpanded = $state(false);

	function getDomain(url: string): string {
		try {
			return new URL(url).hostname.replace('www.', '');
		} catch {
			return url;
		}
	}

	const TYPE_LABELS: Record<string, string> = {
		info: 'web',
		image: 'images',
		news: 'news',
		research: 'research',
		api: 'api',
		tool: 'tools',
		data: 'data',
		youtube_video: 'youtube',
		wikipedia_search: 'wiki · search',
		wikipedia_article: 'wiki · article',
		wikipedia_summary: 'wiki · summary',
		wikipedia_history: 'wiki · history'
	};
</script>

<svelte:window onkeydown={handleKey} />

<div class="h-full p-2" data-testid="search-canvas-wrapper">
	<div
		class="relative flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="search-canvas"
	>
		<!-- Title bar -->
		<div
			class="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface px-3 py-2"
		>
			<div class="flex min-w-0 flex-1 items-center gap-2 text-muted">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="13"
					height="13"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="shrink-0"
				>
					<circle cx="11" cy="11" r="8" />
					<path d="m21 21-4.3-4.3" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					search · {TYPE_LABELS[type] ?? type}
				</span>
				{#if query}
					<span
						class="truncate font-mono text-[11px] text-foreground"
						title={query}
						data-testid="search-canvas-query"
					>
						{query}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="search-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						searching
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
						data-testid="search-canvas-error-badge"
					>
						error
					</span>
				{:else if count > 0}
					<span class="font-mono text-[10px] text-subtle" data-testid="search-canvas-count">
						{count} result{count === 1 ? '' : 's'}
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background" data-testid="search-canvas-body">
			{#if isRunning && results.length === 0 && !articleContent && !articleSummary}
				<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Searching…
				</div>
			{:else if isError}
				<div class="p-3" data-testid="search-canvas-error">
					<div class="rounded border border-accent/30 bg-accent/5 px-3 py-2">
						<div class="font-mono text-[10px] font-medium uppercase text-accent">
							{envelope.error ?? 'error'}
						</div>
						{#if envelope.message}
							<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
						{/if}
						{#if envelope.hint}
							<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
						{/if}
					</div>
				</div>
			{:else if type === 'info' || type === 'news' || type === 'research' || type === 'api' || type === 'tool' || type === 'data'}
				<div class="space-y-2 p-3" data-testid="search-canvas-web">
					{#each results as r, i (r.id ?? i)}
						<div
							class="rounded-lg border border-border-subtle bg-surface-2 p-3 transition-colors hover:border-border-strong"
							data-testid="search-canvas-result"
						>
							<div class="mb-1 truncate text-[11px] text-muted">
								{r.display_link || (r.url ? getDomain(r.url) : '')}
							</div>
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a
								href={r.url}
								target="_blank"
								rel="noopener noreferrer"
								class="mb-1 block text-[13px] font-medium text-accent hover:underline"
							>
								{r.title || r.url}
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
							{#if r.snippet}
								<p class="line-clamp-3 text-[12px] leading-relaxed text-foreground">
									{r.snippet}
								</p>
							{/if}
						</div>
					{/each}
				</div>
			{:else if type === 'image'}
				<!-- CSS columns masonry: preserves natural aspect ratios -->
				<div
					class="columns-2 gap-2 p-3 sm:columns-3 lg:columns-4 [&>*]:mb-2"
					data-testid="search-canvas-images"
				>
					{#each results as r, i (r.id ?? i)}
						{#if r.image_path || r.url}
							<button
								onclick={() => openLightbox(i)}
								class="group relative block w-full break-inside-avoid overflow-hidden rounded-lg border border-border-subtle bg-surface hover:border-border-strong hover:shadow-sm"
								data-testid="search-canvas-image-tile"
							>
								<img
									src={r.image_path || r.url}
									alt={r.title ?? ''}
									class="block h-auto w-full"
									loading="lazy"
								/>
								{#if r.title || r.display_link}
									<div
										class="absolute inset-x-0 bottom-0 bg-surface-2/92 px-2 py-1 text-[10px] text-foreground opacity-0 transition-opacity group-hover:opacity-100"
									>
										{#if r.title}
											<p class="truncate font-medium">{r.title}</p>
										{/if}
										{#if r.display_link}
											<p class="truncate text-subtle">{r.display_link}</p>
										{/if}
									</div>
								{/if}
							</button>
						{/if}
					{/each}
				</div>
			{:else if type === 'wikipedia_search'}
				<div class="space-y-2 p-3" data-testid="search-canvas-wiki-search">
					{#each results as r, i (i)}
						<div
							class="rounded-lg border border-border-subtle bg-surface-2 p-3"
							data-testid="search-canvas-result"
						>
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a
								href={r.url}
								target="_blank"
								rel="noopener noreferrer"
								class="block text-[13px] font-medium text-accent hover:underline"
							>
								{r.title}
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
							{#if r.snippet}
								<p class="mt-1 text-[12px] leading-relaxed text-foreground">{r.snippet}</p>
							{/if}
						</div>
					{/each}
				</div>
			{:else if type === 'wikipedia_summary'}
				<div class="p-4" data-testid="search-canvas-wiki-summary">
					<div class="rounded-lg border border-border-subtle bg-surface-2 p-4">
						<div class="mb-2 flex items-center gap-2">
							<span class="text-[14px] font-medium text-foreground">{articleTitle || query}</span>
							{#if articleUrl}
								<!-- eslint-disable svelte/no-navigation-without-resolve -->
								<a
									href={articleUrl}
									target="_blank"
									rel="noopener noreferrer"
									class="text-[11px] text-accent hover:underline"
								>
									source ↗
								</a>
								<!-- eslint-enable svelte/no-navigation-without-resolve -->
							{/if}
						</div>
						<div
							class="prose prose-sm max-w-none text-[12.5px] leading-relaxed text-foreground [&_a]:text-accent [&_code]:bg-surface [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground"
						>
							<!-- eslint-disable-next-line svelte/no-at-html-tags -->
							{@html renderMarkdown(articleSummary || envelope.message || '')}
						</div>
					</div>
				</div>
			{:else if type === 'wikipedia_article'}
				<div class="p-4" data-testid="search-canvas-wiki-article">
					<div class="mb-3 flex items-center gap-2">
						<span class="text-[14px] font-medium text-foreground">{articleTitle || query}</span>
						{#if articleUrl}
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a
								href={articleUrl}
								target="_blank"
								rel="noopener noreferrer"
								class="text-[11px] text-accent hover:underline"
							>
								source ↗
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						{/if}
					</div>
					{#if articleSummary}
						<div
							class="prose prose-sm mb-4 max-w-none text-[12.5px] leading-relaxed text-foreground [&_a]:text-accent [&_code]:bg-surface [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded"
						>
							<!-- eslint-disable-next-line svelte/no-at-html-tags -->
							{@html renderMarkdown(articleSummary)}
						</div>
					{/if}
					{#if articleSections.length > 0}
						<button
							onclick={() => (sectionsExpanded = !sectionsExpanded)}
							class="mb-2 flex items-center gap-1 text-[11px] font-mono uppercase tracking-wide text-muted hover:text-accent"
						>
							{sectionsExpanded ? '▾' : '▸'} sections ({articleSections.length})
						</button>
						{#if sectionsExpanded}
							<ul class="mb-3 list-disc space-y-0.5 pl-6 text-[11px] text-muted">
								{#each articleSections as s (s)}
									<li>{s}</li>
								{/each}
							</ul>
						{/if}
					{/if}
					{#if articleContent}
						<div
							class="prose prose-sm max-w-none text-[12.5px] leading-relaxed text-foreground [&_a]:text-accent [&_code]:bg-surface [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_h1]:text-foreground [&_h2]:text-foreground [&_h3]:text-foreground [&_h4]:text-foreground [&_pre]:bg-surface [&_pre]:border [&_pre]:border-border-subtle"
						>
							<!-- eslint-disable-next-line svelte/no-at-html-tags -->
							{@html renderMarkdown(articleContent)}
						</div>
					{/if}
				</div>
			{:else if type === 'wikipedia_history'}
				<div class="p-3" data-testid="search-canvas-wiki-history">
					<div class="rounded-lg border border-border-subtle bg-surface-2 p-4">
						<div class="mb-2 flex flex-wrap items-center gap-2">
							<span class="text-[13px] font-medium text-foreground">{articleTitle || query}</span>
							{#if historyActualDate}
								<span class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent">
									{historyActualDate}
								</span>
							{/if}
							{#if historyRequestedDate && historyRequestedDate !== historyActualDate}
								<span class="font-mono text-[10px] text-subtle">
									requested {historyRequestedDate}
								</span>
							{/if}
						</div>
						{#if historyEditor}
							<div class="mb-2 text-[11px] text-muted">
								edited by <span class="text-foreground">{historyEditor}</span>
								{#if historyComment}
									— <span class="italic">{historyComment}</span>
								{/if}
							</div>
						{/if}
						{#if articleContent}
							<div
								class="mt-3 max-h-96 overflow-auto whitespace-pre-wrap border-t border-border-subtle pt-3 font-mono text-[11px] leading-relaxed text-foreground"
							>
								{articleContent}
							</div>
						{/if}
					</div>
				</div>
			{:else if type === 'youtube_video'}
				<div class="p-3" data-testid="search-canvas-youtube">
					<div class="rounded-lg border border-border-subtle bg-surface-2 p-4">
						<div class="flex items-start gap-3">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="32"
								height="32"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="shrink-0 text-accent"
							>
								<path d="m22 8-6 4 6 4V8Z" />
								<rect width="14" height="12" x="2" y="6" rx="2" ry="2" />
							</svg>
							<div class="min-w-0 flex-1">
								<div class="text-[13px] font-medium text-foreground">
									{ytFileName || query}
								</div>
								{#if ytFilePath}
									<div class="mt-1 truncate font-mono text-[11px] text-muted">{ytFilePath}</div>
								{/if}
								{#if envelope.message}
									<div class="mt-2 text-[11px] text-subtle">{envelope.message}</div>
								{/if}
							</div>
						</div>
					</div>
				</div>
			{:else}
				<div class="p-3" data-testid="search-canvas-fallback">
					<pre
						class="overflow-auto whitespace-pre-wrap rounded border border-border-subtle bg-surface p-3 font-mono text-[11px] text-foreground">{JSON.stringify(
							resultObj,
							null,
							2
						)}</pre>
				</div>
			{/if}
		</div>

		<!-- Lightbox overlay -->
		{#if lightboxOpen && results[lightboxIndex]}
			{@const item = results[lightboxIndex]}
			<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
			<div
				class="absolute inset-0 z-20 flex items-center justify-center bg-surface-2/95 p-4 backdrop-blur"
				onclick={closeLightbox}
				onkeydown={(e) => {
					if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') closeLightbox();
				}}
				role="button"
				tabindex="0"
				aria-label="Close image"
				data-testid="search-canvas-lightbox"
			>
				<div class="relative flex max-h-full max-w-full flex-col items-center gap-3">
					<img
						src={item.image_path || item.url}
						alt={item.title ?? ''}
						class="max-h-[70vh] max-w-full rounded-lg border border-border-subtle object-contain"
					/>
					<div class="text-center text-[12px] text-foreground">
						<div class="font-medium">{item.title ?? ''}</div>
						{#if item.display_link}
							<div class="text-[11px] text-muted">{item.display_link}</div>
						{/if}
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
</div>
