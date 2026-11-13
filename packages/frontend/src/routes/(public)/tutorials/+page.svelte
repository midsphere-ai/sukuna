<script lang="ts">
	import { onMount } from 'svelte';
	import { getPublicTutorials, getPublicTutorialContent } from '$api/cms';
	import { marked } from 'marked';
	import type { Tutorial } from '$api/types';

	let tutorials: Tutorial[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	// Search
	let searchQuery = $state('');

	// Selected tutorial (detail view)
	let selectedTutorial = $state<Tutorial | null>(null);
	let contentLoading = $state(false);
	let contentError = $state('');

	// TOC
	let tocItems: { id: string; text: string; level: number }[] = $state([]);
	let activeTocId = $state('');
	let tocOpen = $state(false);

	let filteredTutorials = $derived.by(() => {
		if (!searchQuery.trim()) return tutorials;
		const q = searchQuery.toLowerCase();
		return tutorials.filter(
			(t) =>
				t.title.toLowerCase().includes(q) || (t.subtitle && t.subtitle.toLowerCase().includes(q))
		);
	});

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('en-US', {
			month: 'long',
			day: 'numeric',
			year: 'numeric'
		});
	}

	function estimateReadTime(text: string): string {
		const words = text.trim().split(/\s+/).length;
		const minutes = Math.max(1, Math.round(words / 200));
		return `${minutes} min read`;
	}

	function renderMarkdown(text: string): string {
		return marked.parse(text, { async: false, breaks: true, gfm: true }) as string;
	}

	function extractToc(html: string): { id: string; text: string; level: number }[] {
		const items: { id: string; text: string; level: number }[] = [];
		const regex = /<h([2-3])[^>]*>(.*?)<\/h[2-3]>/gi;
		let match;
		while ((match = regex.exec(html)) !== null) {
			const text = match[2].replace(/<[^>]*>/g, '').trim();
			const id = text
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, '-')
				.replace(/(^-|-$)/g, '');
			items.push({ id, text, level: parseInt(match[1]) });
		}
		return items;
	}

	function injectHeadingIds(html: string): string {
		return html.replace(/<h([2-3])([^>]*)>(.*?)<\/h[2-3]>/gi, (_match, level, attrs, content) => {
			const text = content.replace(/<[^>]*>/g, '').trim();
			const id = text
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, '-')
				.replace(/(^-|-$)/g, '');
			return `<h${level}${attrs} id="${id}">${content}</h${level}>`;
		});
	}

	async function loadTutorials(): Promise<void> {
		loading = true;
		error = '';
		try {
			const response = await getPublicTutorials();
			const items = response.items ?? (Array.isArray(response) ? (response as Tutorial[]) : []);
			tutorials = items.filter((t) => !t.as_info_button);
		} catch {
			error = 'Failed to load tutorials. Please try again later.';
		} finally {
			loading = false;
		}
	}

	async function openTutorial(tutorial: Tutorial): Promise<void> {
		contentLoading = true;
		contentError = '';
		selectedTutorial = tutorial;
		tocItems = [];
		activeTocId = '';
		tocOpen = false;
		try {
			const full = await getPublicTutorialContent(tutorial.title);
			if (full) {
				selectedTutorial = full;
				if (full.markdownText) {
					const html = renderMarkdown(full.markdownText);
					tocItems = extractToc(html);
					if (tocItems.length > 0) activeTocId = tocItems[0].id;
				}
			} else {
				contentError = 'Tutorial content not found.';
			}
		} catch {
			contentError = 'Failed to load tutorial content.';
		} finally {
			contentLoading = false;
		}
	}

	function backToList(): void {
		selectedTutorial = null;
		contentError = '';
		tocItems = [];
		activeTocId = '';
		tocOpen = false;
	}

	function scrollToHeading(id: string): void {
		const el = document.getElementById(id);
		if (el) {
			el.scrollIntoView({ behavior: 'smooth', block: 'start' });
			activeTocId = id;
			tocOpen = false;
		}
	}

	// Intersection observer for active TOC tracking
	$effect(() => {
		if (tocItems.length === 0 || contentLoading) return;

		// Small delay to let DOM render
		const timeout = setTimeout(() => {
			const headingEls = tocItems
				.map((item) => document.getElementById(item.id))
				.filter(Boolean) as HTMLElement[];

			if (headingEls.length === 0) return;

			let observer: IntersectionObserver;
			observer = new IntersectionObserver(
				(entries) => {
					for (const entry of entries) {
						if (entry.isIntersecting) {
							activeTocId = entry.target.id;
						}
					}
				},
				{ rootMargin: '-80px 0px -70% 0px', threshold: 0 }
			);

			for (const el of headingEls) {
				observer.observe(el);
			}

			return () => observer.disconnect();
		}, 100);

		return () => clearTimeout(timeout);
	});

	// SEO meta
	let pageTitle = $derived(
		selectedTutorial ? `${selectedTutorial.title} - Tutorials - Jatayu AI` : 'Tutorials - Jatayu AI'
	);
	let pageDescription = $derived(
		selectedTutorial?.subtitle || 'Browse tutorials and guides for Jatayu AI platform.'
	);

	onMount(() => {
		loadTutorials();
	});
</script>

<svelte:head>
	<title>{pageTitle}</title>
	<meta name="description" content={pageDescription} />
	<meta property="og:title" content={pageTitle} />
	<meta property="og:description" content={pageDescription} />
	<meta property="og:type" content="website" />
	{#if selectedTutorial?.image}
		<meta property="og:image" content={selectedTutorial.image} />
	{/if}
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content={pageTitle} />
	<meta name="twitter:description" content={pageDescription} />
</svelte:head>

{#if selectedTutorial}
	<!-- Tutorial detail view -->
	<div class="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
		<div class="mb-8">
			<button
				onclick={backToList}
				class="mb-6 flex items-center gap-1.5 text-sm text-subtle transition-colors hover:text-foreground"
			>
				<svg
					class="h-4 w-4"
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<path d="M15 18l-6-6 6-6" />
				</svg>
				Back to tutorials
			</button>
		</div>

		{#if contentLoading}
			<div class="space-y-4">
				<div class="h-8 w-2/3 animate-pulse rounded bg-surface-2"></div>
				<div class="h-4 w-1/3 animate-pulse rounded bg-surface-2"></div>
				<div class="mt-8 space-y-3">
					<div class="h-4 w-full animate-pulse rounded bg-surface-2"></div>
					<div class="h-4 w-full animate-pulse rounded bg-surface-2"></div>
					<div class="h-4 w-5/6 animate-pulse rounded bg-surface-2"></div>
				</div>
			</div>
		{:else if contentError}
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
				<p class="text-sm text-foreground">{contentError}</p>
				<button
					onclick={() => selectedTutorial && openTutorial(selectedTutorial)}
					class="mt-4 rounded-lg bg-surface-2 px-4 py-2 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
				>
					Try again
				</button>
			</div>
		{:else}
			<div class="flex gap-10">
				<!-- Main article content -->
				<article class="min-w-0 flex-1">
					{#if selectedTutorial.image}
						<img
							src={selectedTutorial.image}
							alt={selectedTutorial.title}
							class="mb-8 h-64 w-full rounded-xl object-cover"
						/>
					{/if}

					<h1 class="font-junicode text-3xl tracking-tight text-foreground sm:text-4xl">
						{selectedTutorial.title}
					</h1>

					{#if selectedTutorial.subtitle}
						<p class="mt-3 text-base leading-relaxed text-subtle">{selectedTutorial.subtitle}</p>
					{/if}

					<div class="mt-4 flex items-center gap-3 text-sm text-muted">
						<time datetime={selectedTutorial.date_created}>
							{formatDate(selectedTutorial.date_created)}
						</time>
						{#if selectedTutorial.markdownText}
							<span class="text-muted">·</span>
							<span>{estimateReadTime(selectedTutorial.markdownText)}</span>
						{/if}
					</div>

					<!-- Mobile TOC toggle -->
					{#if tocItems.length > 0}
						<div class="mt-6 lg:hidden">
							<button
								onclick={() => (tocOpen = !tocOpen)}
								class="flex w-full items-center justify-between rounded-lg border border-border bg-surface px-4 py-3 text-sm font-medium text-foreground"
							>
								<span class="flex items-center gap-2">
									<svg
										class="h-4 w-4 text-muted"
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="1.5"
									>
										<path d="M4 6h16M4 12h16M4 18h7" />
									</svg>
									On this page
								</span>
								<svg
									class="h-4 w-4 text-muted transition-transform {tocOpen ? 'rotate-180' : ''}"
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
								>
									<path d="M6 9l6 6 6-6" />
								</svg>
							</button>
							{#if tocOpen}
								<nav class="mt-2 rounded-lg border border-border-subtle bg-surface p-3">
									<ul class="space-y-1">
										{#each tocItems as item (item.id)}
											<li>
												<button
													onclick={() => scrollToHeading(item.id)}
													class="w-full rounded px-3 py-1.5 text-left text-sm transition-colors {item.level ===
													3
														? 'pl-6'
														: ''} {activeTocId === item.id
														? 'bg-surface-2 font-medium text-foreground'
														: 'text-subtle hover:text-foreground'}"
												>
													{item.text}
												</button>
											</li>
										{/each}
									</ul>
								</nav>
							{/if}
						</div>
					{/if}

					{#if selectedTutorial.markdownText}
						<div class="prose mt-10 max-w-none text-foreground">
							<!-- eslint-disable svelte/no-at-html-tags -->
							{@html injectHeadingIds(renderMarkdown(selectedTutorial.markdownText))}
							<!-- eslint-enable svelte/no-at-html-tags -->
						</div>
					{/if}
				</article>

				<!-- Desktop sidebar TOC -->
				{#if tocItems.length > 0}
					<aside class="hidden w-56 shrink-0 lg:block">
						<nav class="sticky top-24">
							<h4 class="mb-3 text-xs font-medium uppercase tracking-widest text-muted">
								On this page
							</h4>
							<ul class="space-y-0.5 border-l border-border-subtle">
								{#each tocItems as item (item.id)}
									<li>
										<button
											onclick={() => scrollToHeading(item.id)}
											class="block w-full -ml-px border-l-2 py-1.5 text-left text-[13px] leading-snug transition-colors {item.level ===
											3
												? 'pl-5'
												: 'pl-3'} {activeTocId === item.id
												? 'border-accent text-foreground font-medium'
												: 'border-transparent text-subtle hover:text-foreground hover:border-border-strong'}"
										>
											{item.text}
										</button>
									</li>
								{/each}
							</ul>
						</nav>
					</aside>
				{/if}
			</div>
		{/if}
	</div>
{:else}
	<!-- Tutorial list view -->
	<div class="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
		<!-- Header -->
		<div class="mb-12">
			<h1 class="font-junicode text-3xl tracking-tight text-foreground sm:text-4xl">Tutorials</h1>
			<p class="mt-3 text-base leading-relaxed text-subtle">
				Learn how to use Jatayu AI with step-by-step guides and tutorials.
			</p>
		</div>

		<!-- Search -->
		<div class="mb-8">
			<div class="relative">
				<svg
					class="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
				>
					<circle cx="11" cy="11" r="8" />
					<path d="M21 21l-4.35-4.35" />
				</svg>
				<input
					type="text"
					bind:value={searchQuery}
					placeholder="Search tutorials..."
					class="w-full rounded-xl border border-border bg-surface py-3 pl-11 pr-4 text-sm text-foreground placeholder:text-muted focus:border-border-strong focus:outline-none focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				/>
				{#if searchQuery}
					<button
						onclick={() => (searchQuery = '')}
						aria-label="Clear search"
						class="absolute right-3 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted hover:text-subtle"
					>
						<svg
							class="h-4 w-4"
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
						>
							<path d="M18 6L6 18M6 6l12 12" />
						</svg>
					</button>
				{/if}
			</div>
		</div>

		{#if loading}
			<!-- Loading skeleton -->
			<div class="space-y-4">
				{#each [0, 1, 2, 3, 4] as i (i)}
					<div class="rounded-xl border border-border-subtle bg-surface p-5">
						<div class="flex items-start gap-4">
							<div
								class="hidden h-20 w-28 shrink-0 animate-pulse rounded-lg bg-surface-2 sm:block"
							></div>
							<div class="flex-1">
								<div class="mb-2 h-5 w-3/4 animate-pulse rounded bg-surface-2"></div>
								<div class="mb-3 h-4 w-full animate-pulse rounded bg-surface-2"></div>
								<div class="h-3 w-1/4 animate-pulse rounded bg-surface-2"></div>
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
					onclick={loadTutorials}
					class="mt-4 rounded-lg bg-surface-2 px-4 py-2 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
				>
					Try again
				</button>
			</div>
		{:else if filteredTutorials.length === 0}
			<div class="rounded-xl border border-border-subtle bg-surface p-12 text-center">
				<svg
					class="mx-auto mb-3 h-10 w-10 text-muted"
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
					<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
				</svg>
				{#if searchQuery}
					<p class="text-sm text-subtle">No tutorials match &ldquo;{searchQuery}&rdquo;</p>
					<button
						onclick={() => (searchQuery = '')}
						class="mt-3 text-xs text-muted hover:text-subtle"
					>
						Clear search
					</button>
				{:else}
					<p class="text-sm text-subtle">No tutorials available yet</p>
				{/if}
			</div>
		{:else}
			<!-- Tutorial list -->
			<div class="space-y-3">
				{#each filteredTutorials as tutorial (tutorial.id)}
					<!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
					<article
						role="button"
						tabindex="0"
						onclick={() => openTutorial(tutorial)}
						onkeydown={(e) => e.key === 'Enter' && openTutorial(tutorial)}
						class="group cursor-pointer rounded-xl border border-border-subtle bg-surface p-5 transition-[border-color] duration-200 hover:border-border-strong"
					>
						<div class="flex items-start gap-4">
							{#if tutorial.image}
								<img
									src={tutorial.image}
									alt=""
									class="hidden h-20 w-28 shrink-0 rounded-lg object-cover sm:block"
								/>
							{:else}
								<div
									class="hidden h-20 w-28 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent/10 to-accent/10 sm:flex"
								>
									<svg
										class="h-8 w-8 text-muted"
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="1.5"
									>
										<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
										<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
									</svg>
								</div>
							{/if}
							<div class="min-w-0 flex-1">
								<h2
									class="text-sm font-medium text-foreground group-hover:text-foreground line-clamp-1"
								>
									{tutorial.title}
								</h2>
								{#if tutorial.subtitle}
									<p class="mt-1 text-sm leading-relaxed text-subtle line-clamp-2">
										{tutorial.subtitle}
									</p>
								{/if}
								<div class="mt-2 flex items-center gap-2 text-xs text-muted">
									<time datetime={tutorial.date_created}>
										{formatDate(tutorial.date_created)}
									</time>
									{#if tutorial.markdownText}
										<span class="text-muted">·</span>
										<span>{estimateReadTime(tutorial.markdownText)}</span>
									{/if}
								</div>
							</div>
							<svg
								class="mt-1 hidden h-4 w-4 shrink-0 text-muted transition-transform group-hover:translate-x-0.5 group-hover:text-muted sm:block"
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
							>
								<path d="M9 18l6-6-6-6" />
							</svg>
						</div>
					</article>
				{/each}
			</div>

			<!-- Result count -->
			{#if searchQuery && filteredTutorials.length > 0}
				<p class="mt-4 text-center text-xs text-muted">
					{filteredTutorials.length} tutorial{filteredTutorials.length === 1 ? '' : 's'} found
				</p>
			{/if}
		{/if}
	</div>
{/if}

<style>
	.prose :global(h1) {
		font-size: 1.75rem;
		font-weight: 500;
		margin-top: 2rem;
		margin-bottom: 0.75rem;
	}
	.prose :global(h2) {
		font-size: 1.375rem;
		font-weight: 500;
		margin-top: 1.75rem;
		margin-bottom: 0.5rem;
		scroll-margin-top: 5rem;
	}
	.prose :global(h3) {
		font-size: 1.125rem;
		font-weight: 500;
		margin-top: 1.5rem;
		margin-bottom: 0.5rem;
		scroll-margin-top: 5rem;
	}
	.prose :global(p) {
		margin-bottom: 1rem;
		line-height: 1.7;
	}
	.prose :global(ul),
	.prose :global(ol) {
		margin-bottom: 1rem;
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
		padding: 1rem;
		margin-bottom: 1rem;
		overflow-x: auto;
	}
	.prose :global(pre code) {
		background: none;
		padding: 0;
	}
	.prose :global(blockquote) {
		border-left: 3px solid var(--ms-border-strong);
		padding-left: 1rem;
		margin-bottom: 1rem;
		color: var(--ms-subtle-text);
	}
	.prose :global(a) {
		color: var(--ms-blue);
		text-decoration: underline;
	}
	.prose :global(img) {
		max-width: 100%;
		border-radius: 0.5rem;
		margin: 1rem 0;
	}
</style>
