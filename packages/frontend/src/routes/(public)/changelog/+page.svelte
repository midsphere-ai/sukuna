<script lang="ts">
	import { onMount } from 'svelte';
	import { getPublicHomeBanner, getPublicChangelog } from '$api/cms';
	import type { HomeBanner, ChangelogEntry } from '$api/cms';
	import { marked } from 'marked';

	let banner: HomeBanner | null = $state(null);
	let entries: ChangelogEntry[] = $state([]);
	let loading = $state(true);
	let error = $state('');
	let activeFilter: string = $state('all');

	const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
		feature: { label: 'Feature', color: 'text-accent-positive', bg: 'bg-accent-positive/10' },
		fix: { label: 'Fix', color: 'text-accent-negative', bg: 'bg-accent-negative/10' },
		improvement: {
			label: 'Improvement',
			color: 'text-accent-primary',
			bg: 'bg-accent-primary/10'
		},
		announcement: {
			label: 'Announcement',
			color: 'text-accent-warning',
			bg: 'bg-accent-warning/10'
		}
	};

	function renderMarkdown(text: string): string {
		return marked.parse(text, { async: false, breaks: true, gfm: true }) as string;
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('en-US', {
			month: 'long',
			day: 'numeric',
			year: 'numeric'
		});
	}

	function formatShortDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric'
		});
	}

	let filteredEntries = $derived(
		activeFilter === 'all' ? entries : entries.filter((e) => e.category === activeFilter)
	);

	let groupedEntries = $derived.by(() => {
		const groups: Record<string, ChangelogEntry[]> = {};
		for (const entry of filteredEntries) {
			const monthKey = new Date(entry.date).toLocaleDateString('en-US', {
				month: 'long',
				year: 'numeric'
			});
			if (!groups[monthKey]) groups[monthKey] = [];
			groups[monthKey].push(entry);
		}
		return groups;
	});

	async function loadData(): Promise<void> {
		loading = true;
		error = '';
		try {
			const [bannerData, changelogData] = await Promise.all([
				getPublicHomeBanner(),
				getPublicChangelog()
			]);
			banner = bannerData;
			entries = changelogData?.items ?? [];
		} catch {
			error = 'Failed to load changelog. Please try again later.';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		loadData();
	});
</script>

<svelte:head>
	<title>Changelog - Jatayu AI</title>
	<meta
		name="description"
		content="Stay up to date with the latest Jatayu AI platform updates, changes, and announcements."
	/>
	<meta property="og:title" content="Changelog - Jatayu AI" />
	<meta
		property="og:description"
		content="Stay up to date with the latest Jatayu AI platform updates and announcements."
	/>
	<meta property="og:type" content="website" />
	<meta name="twitter:card" content="summary" />
	<meta name="twitter:title" content="Changelog - Jatayu AI" />
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
	<!-- Header -->
	<div class="mb-12">
		<h1 class="font-junicode text-3xl tracking-tight text-foreground sm:text-4xl">Changelog</h1>
		<p class="mt-3 text-base leading-relaxed text-subtle">
			New updates and improvements to Jatayu AI.
		</p>
	</div>

	{#if loading}
		<!-- Loading skeleton -->
		<div class="space-y-6">
			{#each [0, 1, 2] as i (i)}
				<div class="flex gap-6">
					<div class="hidden w-24 shrink-0 sm:block">
						<div class="h-4 w-16 animate-pulse rounded bg-surface-2"></div>
					</div>
					<div class="flex-1 rounded-xl border border-border-subtle bg-surface p-5">
						<div class="mb-2 flex items-center gap-2">
							<div class="h-5 w-16 animate-pulse rounded-full bg-surface-2"></div>
							<div class="h-4 w-48 animate-pulse rounded bg-surface-2"></div>
						</div>
						<div class="space-y-2">
							<div class="h-3 w-full animate-pulse rounded bg-surface-2"></div>
							<div class="h-3 w-2/3 animate-pulse rounded bg-surface-2"></div>
						</div>
					</div>
				</div>
			{/each}
		</div>
	{:else if error}
		<div class="rounded-xl border border-accent/20 bg-accent/5 p-8 text-center">
			<svg
				class="mx-auto mb-3 h-8 w-8 text-accent/60"
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
			>
				<circle cx="12" cy="12" r="10" />
				<path d="M12 8v4m0 4h.01" />
			</svg>
			<p class="text-sm text-foreground">{error}</p>
			<button
				onclick={loadData}
				class="mt-4 rounded-lg bg-surface-2 px-4 py-2 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
			>
				Try again
			</button>
		</div>
	{:else}
		<!-- Announcement banner -->
		{#if banner?.announcement}
			<div class="mb-10 rounded-xl border border-accent-warning/20 bg-accent-warning/5 p-5">
				<div class="flex items-start gap-3">
					<div
						class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-warning/15"
					>
						<svg
							class="h-3.5 w-3.5 text-accent-warning"
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
						>
							<path
								d="M22 17H2a3 3 0 0 0 3-3V9a7 7 0 0 1 14 0v5a3 3 0 0 0 3 3zm-8.27 4a2 2 0 0 1-3.46 0"
							/>
						</svg>
					</div>
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span class="text-sm font-medium text-foreground">Announcement</span>
							<time class="text-xs text-muted" datetime={banner.announcement.date_created}>
								{formatDate(banner.announcement.date_created)}
							</time>
						</div>
						<p class="mt-1 text-sm leading-relaxed text-foreground">
							{banner.announcement.text}
						</p>
					</div>
				</div>
			</div>
		{/if}

		<!-- Category filter pills -->
		{#if entries.length > 0}
			<div class="mb-8 flex flex-wrap gap-2">
				<button
					onclick={() => (activeFilter = 'all')}
					class="rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors {activeFilter ===
					'all'
						? 'bg-foreground text-white'
						: 'bg-surface-2 text-subtle hover:bg-surface-2 hover:text-foreground'}"
				>
					All
				</button>
				{#each Object.entries(CATEGORY_CONFIG) as [key, config] (key)}
					<button
						onclick={() => (activeFilter = key)}
						class="rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors {activeFilter ===
						key
							? 'bg-foreground text-white'
							: 'bg-surface-2 text-subtle hover:bg-surface-2 hover:text-foreground'}"
					>
						{config.label}
					</button>
				{/each}
			</div>
		{/if}

		<!-- Changelog entries grouped by month -->
		{#if Object.keys(groupedEntries).length > 0}
			<div class="space-y-10">
				{#each Object.entries(groupedEntries) as [month, monthEntries] (month)}
					<section>
						<h2 class="mb-4 text-xs font-medium uppercase tracking-widest text-muted">
							{month}
						</h2>
						<div class="space-y-3">
							{#each monthEntries as entry (entry.id)}
								{@const config = CATEGORY_CONFIG[entry.category] ?? CATEGORY_CONFIG.announcement}
								<article
									class="card-hover group rounded-xl border border-border-subtle bg-surface p-5"
								>
									<div class="mb-2 flex flex-wrap items-center gap-2">
										<span
											class="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium uppercase tracking-wide {config.color} {config.bg}"
										>
											{config.label}
										</span>
										<h3 class="text-sm font-medium text-foreground">{entry.title}</h3>
										<time class="ml-auto text-xs text-muted sm:block" datetime={entry.date}>
											{formatShortDate(entry.date)}
										</time>
									</div>
									{#if entry.body}
										<div class="prose text-sm leading-relaxed text-subtle">
											<!-- eslint-disable svelte/no-at-html-tags -->
											{@html renderMarkdown(entry.body)}
											<!-- eslint-enable svelte/no-at-html-tags -->
										</div>
									{/if}
								</article>
							{/each}
						</div>
					</section>
				{/each}
			</div>
		{/if}

		<!-- Legacy changelog markdown (if no entries but banner exists) -->
		{#if entries.length === 0 && banner?.change_log}
			<div class="rounded-xl border border-border-subtle bg-surface p-6">
				<div class="mb-4 flex items-center gap-2">
					<h2 class="font-junicode text-lg text-foreground">Latest Changes</h2>
					<time class="ml-auto text-xs text-muted" datetime={banner.change_log.date_created}>
						{formatDate(banner.change_log.date_created)}
					</time>
				</div>
				<div class="prose text-sm text-foreground">
					<!-- eslint-disable svelte/no-at-html-tags -->
					{@html renderMarkdown(banner.change_log.markdownText)}
					<!-- eslint-enable svelte/no-at-html-tags -->
				</div>
			</div>
		{/if}

		<!-- Empty state -->
		{#if !banner?.announcement && !banner?.change_log && entries.length === 0}
			<div class="rounded-xl border border-border-subtle bg-surface p-12 text-center">
				<svg
					class="mx-auto mb-3 h-10 w-10 text-muted"
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
					<polyline points="14 2 14 8 20 8" />
				</svg>
				<p class="text-sm text-subtle">No updates yet. Check back soon!</p>
			</div>
		{/if}

		<!-- Filtered empty state -->
		{#if entries.length > 0 && filteredEntries.length === 0}
			<div class="rounded-xl border border-border-subtle bg-surface p-10 text-center">
				<p class="text-sm text-subtle">
					No {CATEGORY_CONFIG[activeFilter]?.label?.toLowerCase() ?? ''} entries yet.
				</p>
			</div>
		{/if}
	{/if}
</div>

<style>
	.prose :global(h1) {
		font-size: 1.5rem;
		font-weight: 500;
		margin-top: 1.5rem;
		margin-bottom: 0.5rem;
	}
	.prose :global(h2) {
		font-size: 1.25rem;
		font-weight: 500;
		margin-top: 1.25rem;
		margin-bottom: 0.5rem;
	}
	.prose :global(h3) {
		font-size: 1.125rem;
		font-weight: 500;
		margin-top: 1rem;
		margin-bottom: 0.5rem;
	}
	.prose :global(p) {
		margin-bottom: 0.75rem;
		line-height: 1.7;
	}
	.prose :global(ul),
	.prose :global(ol) {
		margin-bottom: 0.75rem;
		padding-left: 1.5rem;
	}
	.prose :global(li) {
		margin-bottom: 0.25rem;
	}
	.prose :global(code) {
		font-size: 0.875rem;
		background: var(--ms-elevated);
		padding: 0.15rem 0.35rem;
		border-radius: 0.25rem;
	}
	.prose :global(pre) {
		background: var(--ms-elevated);
		border-radius: 0.5rem;
		padding: 0.75rem;
		margin-bottom: 0.75rem;
		overflow-x: auto;
	}
	.prose :global(pre code) {
		background: none;
		padding: 0;
	}
	.prose :global(a) {
		color: var(--ms-blue);
		text-decoration: underline;
	}
</style>
