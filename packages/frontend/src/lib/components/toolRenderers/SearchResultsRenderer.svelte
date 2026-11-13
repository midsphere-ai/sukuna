<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface SearchResultItem {
		id?: string;
		title?: string;
		url?: string;
		snippet?: string;
		display_link?: string;
		formatted_url?: string;
		hint?: string;
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
		Array.isArray(resultObj.results) ? (resultObj.results as SearchResultItem[]) : []
	);
	let count = $derived(
		typeof resultObj.count === 'number' ? (resultObj.count as number) : results.length
	);

	let expanded = $state(false);
	let COLLAPSED = 3;
	let visible = $derived(expanded ? results : results.slice(0, COLLAPSED));

	function getDomain(url: string): string {
		try {
			return new URL(url).hostname.replace('www.', '');
		} catch {
			return url;
		}
	}
</script>

<div data-testid="search-results-renderer">
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
					<circle cx="11" cy="11" r="8" />
					<path d="m21 21-4.3-4.3" />
				</svg>
				<span class="truncate font-mono" data-testid="search-results-query">{query}</span>
			</div>
		{/if}
		{#if isError}
			<span
				class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-accent"
			>
				error
			</span>
		{:else if count > 0}
			<span class="shrink-0 font-mono text-[10px] text-subtle" data-testid="search-results-count">
				{count} result{count === 1 ? '' : 's'}
			</span>
		{/if}
	</div>

	{#if isError}
		<div
			class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
			data-testid="search-results-error"
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
	{:else if results.length > 0}
		<div class="space-y-2" data-testid="search-results-list">
			{#each visible as r, i (r.id ?? i)}
				<div
					class="rounded-lg border border-border-subtle bg-background p-2.5 transition-colors hover:border-border-strong"
					data-testid="search-results-card"
				>
					<div class="mb-0.5 truncate text-[10px] text-muted">
						{r.display_link || r.formatted_url || (r.url ? getDomain(r.url) : '')}
					</div>
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a
						href={r.url}
						target="_blank"
						rel="noopener noreferrer"
						class="block text-[12px] font-medium text-accent hover:underline"
					>
						{r.title || r.url}
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
					{#if r.snippet}
						<p class="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-foreground">
							{r.snippet}
						</p>
					{/if}
				</div>
			{/each}
		</div>
		{#if results.length > COLLAPSED}
			<button
				onclick={() => (expanded = !expanded)}
				class="mt-2 w-full rounded border border-border-subtle bg-surface py-1 text-[11px] text-muted transition-colors hover:bg-surface-2 hover:text-accent"
				data-testid="search-results-toggle"
			>
				{expanded ? 'show less' : `show ${results.length - COLLAPSED} more`}
			</button>
		{/if}
	{:else if typeof toolCall.result === 'string'}
		<div class="text-[11px] leading-relaxed text-subtle">{toolCall.result}</div>
	{:else if envelope.message}
		<div class="text-[11px] italic text-subtle">{envelope.message}</div>
	{/if}
</div>
