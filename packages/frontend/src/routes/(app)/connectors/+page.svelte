<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { SvelteMap } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import {
		Skeleton,
		EmptyState,
		LoadingSpinner,
		SearchInput,
		Badge,
		SideNav
	} from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import { getAddons, searchAddons, getUserAddons } from '$api/addons';
	import { pullToRefresh } from '$lib/actions/gestures';
	import { isSessionFresh, markSessionFetched } from '$stores/freshness';
	import type { MarketplaceAddon, UserAddon } from '$api/types';
	import { flagEnabled } from '$stores/featureFlags';

	const customMcpFlag = flagEnabled('enable-custom-mcp');
	let showCustomMcp = $state(false);
	customMcpFlag.subscribe((v) => {
		showCustomMcp = v;
	});

	// ── SessionStorage cache helpers ──
	function loadSessionCache<T>(key: string): T | null {
		try {
			const raw = sessionStorage.getItem(key);
			if (raw) return JSON.parse(raw) as T;
		} catch {
			/* ignore */
		}
		return null;
	}
	function setSessionCache(key: string, data: unknown): void {
		try {
			sessionStorage.setItem(key, JSON.stringify(data));
		} catch {
			/* ignore */
		}
	}

	// ── State — seed from sessionStorage cache ──
	const cachedMarketplace = loadSessionCache<MarketplaceAddon[]>(
		'midsphere-connectors-marketplace'
	);
	const cachedInstalled = loadSessionCache<UserAddon[]>('midsphere-connectors-installed');

	let marketplaceAddons: MarketplaceAddon[] = $state(cachedMarketplace ?? []);
	let installedMap = new SvelteMap<string, UserAddon>();
	let marketplaceLoading = $state(!cachedMarketplace);

	// Rebuild installedMap from cache if available
	if (cachedInstalled) {
		for (const ua of cachedInstalled) {
			installedMap.set(ua.enabled_addon.id, ua);
		}
	}
	let searchQuery = $state('');
	let selectedCategory = $state('All');

	// Status filter
	type StatusFilter = 'all' | 'installed' | 'needs-auth' | 'not-installed';
	let statusFilter: StatusFilter = $state('all');
	let filterDropdownOpen = $state(false);

	// Marketplace pagination
	let marketplacePage = $state(1);
	let marketplaceTotalCount = $state(0);
	let loadingMore = $state(false);

	// Search state
	let searchResults: MarketplaceAddon[] = $state([]);
	let searchPage = $state(1);
	let searchTotalCount = $state(0);
	let searchLoading = $state(false);
	let searchLoadingMore = $state(false);

	let scrollSentinelEl: HTMLDivElement | undefined = $state();
	let observer: IntersectionObserver | null = null;

	// ── Derived ──
	let searchActive = $derived(searchQuery.trim().length > 0);

	let allCategories = $derived.by(() => {
		const tags: string[] = [];
		for (const addon of marketplaceAddons) {
			for (const tag of addon.tags) {
				if (!tags.includes(tag)) tags.push(tag);
			}
		}
		return ['All', ...tags.sort()];
	});

	function capitalizeTag(tag: string): string {
		return tag.replace(/\b\w/g, (c) => c.toUpperCase());
	}

	let categoryNavItems = $derived(
		allCategories.map((c) => ({
			id: c,
			label: c === 'All' ? 'All' : capitalizeTag(c)
		}))
	);

	function getAddonStatus(addonId: string): 'connected' | 'needs-auth' | null {
		const ua = installedMap.get(addonId);
		if (!ua) return null;
		return ua.auth_complete ? 'connected' : 'needs-auth';
	}

	// Addons to display: apply category and status filters
	let displayAddons = $derived.by(() => {
		const source = searchActive ? searchResults : marketplaceAddons;

		let filtered = source;

		// Category filter
		if (selectedCategory !== 'All') {
			filtered = filtered.filter((a) => a.tags.includes(selectedCategory));
		}

		// Status filter
		if (statusFilter !== 'all') {
			filtered = filtered.filter((a) => {
				const status = getAddonStatus(a.id);
				if (statusFilter === 'installed') return status === 'connected';
				if (statusFilter === 'needs-auth') return status === 'needs-auth';
				if (statusFilter === 'not-installed') return status === null;
				return true;
			});
		}

		return filtered;
	});

	let hasMoreMarketplace = $derived(marketplaceAddons.length < marketplaceTotalCount);
	let hasMoreSearch = $derived(searchResults.length < searchTotalCount);

	// ── Data Loading ──
	let searchTimer: ReturnType<typeof setTimeout> | null = null;

	function handleSearchInput(): void {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => {
			searchPage = 1;
			searchResults = [];
			if (searchQuery.trim()) {
				loadSearchResults();
			}
		}, 300);
	}

	function clearSearch(): void {
		searchQuery = '';
		searchResults = [];
		searchPage = 1;
		searchTotalCount = 0;
	}

	async function loadMarketplace(): Promise<void> {
		if (marketplacePage === 1 && marketplaceAddons.length === 0) marketplaceLoading = true;
		else if (marketplacePage > 1) loadingMore = true;

		try {
			const response = await getAddons(marketplacePage);
			if (marketplacePage === 1) {
				marketplaceAddons = response.items;
				setSessionCache('midsphere-connectors-marketplace', response.items);
				markSessionFetched('midsphere-connectors-marketplace');
			} else {
				marketplaceAddons = [...marketplaceAddons, ...response.items];
			}
			marketplaceTotalCount = response.count;
		} catch {
			toasts.error('Failed to load connectors');
		} finally {
			marketplaceLoading = false;
			loadingMore = false;
		}
	}

	async function loadSearchResults(): Promise<void> {
		if (searchPage === 1) searchLoading = true;
		else searchLoadingMore = true;

		try {
			const response = await searchAddons(searchQuery.trim(), searchPage);
			if (searchPage === 1) {
				searchResults = response.items;
			} else {
				searchResults = [...searchResults, ...response.items];
			}
			searchTotalCount = response.count;
		} catch {
			toasts.error('Failed to search connectors');
		} finally {
			searchLoading = false;
			searchLoadingMore = false;
		}
	}

	async function loadInstalledAddons(): Promise<void> {
		try {
			const response = await getUserAddons(1);
			installedMap.clear();
			for (const ua of response.items) {
				installedMap.set(ua.enabled_addon.id, ua);
			}
			setSessionCache('midsphere-connectors-installed', response.items);
			markSessionFetched('midsphere-connectors-installed');
		} catch {
			// Non-critical
		}
	}

	function loadMoreMarketplace(): void {
		if (loadingMore || !hasMoreMarketplace) return;
		marketplacePage += 1;
		loadMarketplace();
	}

	function loadMoreSearch(): void {
		if (searchLoadingMore || !hasMoreSearch) return;
		searchPage += 1;
		loadSearchResults();
	}

	function handleAddonClick(addon: MarketplaceAddon): void {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto(`/connectors/${addon.id}`);
	}

	// Intersection observer for infinite scroll
	function setupIntersectionObserver(): void {
		if (observer) observer.disconnect();
		observer = new IntersectionObserver(
			(entries) => {
				if (!entries[0]?.isIntersecting) return;
				if (searchActive) {
					if (hasMoreSearch && !searchLoadingMore && !searchLoading) loadMoreSearch();
				} else {
					if (hasMoreMarketplace && !loadingMore && !marketplaceLoading) loadMoreMarketplace();
				}
			},
			{ rootMargin: '200px' }
		);
		if (scrollSentinelEl) observer.observe(scrollSentinelEl);
	}

	$effect(() => {
		if (scrollSentinelEl) setupIntersectionObserver();
		return () => {
			if (observer) observer.disconnect();
		};
	});

	async function handlePullRefresh(): Promise<void> {
		marketplacePage = 1;
		marketplaceAddons = [];
		await Promise.all([loadMarketplace(), loadInstalledAddons()]);
	}

	// Filter chip definitions
	const statusChips: { key: StatusFilter; label: string }[] = [
		{ key: 'all', label: 'All' },
		{ key: 'installed', label: 'Connected' },
		{ key: 'needs-auth', label: 'Needs Auth' },
		{ key: 'not-installed', label: 'Not Installed' }
	];

	onMount(() => {
		pageTitle.set('Connectors');
		showHeaderTitle.set(false);
		if (!isSessionFresh('midsphere-connectors-marketplace', 120_000)) loadMarketplace();
		if (!isSessionFresh('midsphere-connectors-installed', 120_000)) loadInstalledAddons();
	});

	onDestroy(() => {
		if (searchTimer) clearTimeout(searchTimer);
	});
</script>

<!-- Click outside handler for dropdowns -->
<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (!target.closest('[data-connectors-dropdown]')) {
			filterDropdownOpen = false;
		}
	}}
/>

<svelte:head>
	<title>Connectors - Jatayu AI</title>
</svelte:head>

<div class="flex w-full" use:pullToRefresh={{ onRefresh: handlePullRefresh }}>
	<SideNav
		bind:value={selectedCategory}
		items={categoryNavItems}
		title="Connectors"
		searchParamKey="section"
		class="px-4 py-8"
	/>

	<div class="min-w-0 flex-1 px-6 py-8">
		<!-- Toolbar -->
		<div class="mb-4 flex items-center gap-3">
			<!-- Left: Search + Filter -->
			<div class="flex flex-1 items-center gap-3">
				<div class="w-56">
					<SearchInput
						bind:value={searchQuery}
						oninput={handleSearchInput}
						placeholder="Search connectors..."
						showCancel={searchActive}
						onclear={clearSearch}
					/>
				</div>

				<!-- Combined filter dropdown -->
				<div class="relative" data-connectors-dropdown>
					<button
						onclick={(e) => {
							e.stopPropagation();
							filterDropdownOpen = !filterDropdownOpen;
						}}
						class="inline-flex h-9 items-center gap-2 rounded-xl border border-border px-3.5 text-sm transition-colors hover:border-border-strong {statusFilter !==
						'all'
							? 'font-medium text-foreground'
							: 'text-subtle'}"
					>
						Filter
						{#if statusFilter !== 'all'}
							<span
								class="flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-surface-2 px-1 text-[10px] font-medium text-foreground"
							>
								1
							</span>
						{/if}
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
							class="text-muted"
						>
							<path d="m6 9 6 6 6-6" />
						</svg>
					</button>

					{#if filterDropdownOpen}
						<div
							class="absolute left-0 z-50 mt-1.5 w-48 animate-[fadeInUp_100ms_ease-out] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-sm"
							role="menu"
							tabindex="-1"
						>
							<!-- Status section -->
							<p class="px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted uppercase">
								Status
							</p>
							{#each statusChips as chip (chip.key)}
								<button
									onclick={() => {
										statusFilter = chip.key;
									}}
									class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors {statusFilter ===
									chip.key
										? 'bg-surface-2 font-medium text-foreground'
										: 'text-subtle hover:bg-surface-2 hover:text-foreground'}"
									role="menuitem"
								>
									{#if chip.key === 'installed'}
										<span class="h-2 w-2 rounded-full bg-success"></span>
									{:else if chip.key === 'needs-auth'}
										<span class="h-2 w-2 rounded-full bg-amber-400"></span>
									{:else if chip.key === 'not-installed'}
										<span class="h-2 w-2 rounded-full bg-surface-2"></span>
									{/if}
									{chip.label}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			</div>

			{#if showCustomMcp}
				<button
					onclick={() => goto('/connectors/mcp')}
					class="inline-flex h-9 items-center gap-1.5 rounded-xl bg-foreground px-3.5 text-sm font-medium text-background transition-all duration-200 hover:opacity-90"
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
						<line x1="12" y1="5" x2="12" y2="19" />
						<line x1="5" y1="12" x2="19" y2="12" />
					</svg>
					Custom MCP
				</button>
			{/if}
		</div>

		<!-- Loading state -->
		{#if marketplaceLoading || (searchActive && searchLoading)}
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
				{#each [0, 1, 2, 3, 4, 5, 6, 7] as i (i)}
					<div class="flex flex-col rounded-xl border border-border-subtle bg-background p-4">
						<Skeleton class="mb-3 rounded-xl" width="48px" height="48px" stagger={i} />
						<Skeleton class="mb-1 rounded" width="70%" height="13px" stagger={i + 1} />
						<Skeleton class="mb-3 rounded" width="90%" height="10px" stagger={i + 2} />
						<div class="mt-auto flex items-center justify-between">
							<Skeleton class="rounded" width="28px" height="10px" />
							<Skeleton class="rounded-full" width="40px" height="20px" />
						</div>
					</div>
				{/each}
			</div>

			<!-- Empty state -->
		{:else if displayAddons.length === 0}
			{#if searchActive}
				<EmptyState
					title={`No results for \u201C${searchQuery}\u201D`}
					description="Try a different search term or check your spelling."
					ctaLabel="Clear search"
					onctaclick={clearSearch}
				>
					{#snippet illustration()}
						<div
							class="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-2 text-muted"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="32"
								height="32"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<circle cx="11" cy="11" r="8" />
								<path d="M21 21l-4.35-4.35" />
								<path d="M8 11h6" />
							</svg>
						</div>
					{/snippet}
				</EmptyState>
			{:else if statusFilter !== 'all' || selectedCategory !== 'All'}
				<EmptyState
					title="No connectors match"
					description="Try changing the filter or category."
					ctaLabel="Clear filters"
					onctaclick={() => {
						statusFilter = 'all';
						selectedCategory = 'All';
					}}
				>
					{#snippet illustration()}
						<div
							class="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-2 text-muted"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="32"
								height="32"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
							</svg>
						</div>
					{/snippet}
				</EmptyState>
			{:else}
				<EmptyState
					title="No connectors available"
					description="Check back soon for new integrations."
				>
					{#snippet illustration()}
						<div
							class="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-2 text-muted"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="32"
								height="32"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<rect x="3" y="3" width="7" height="7" />
								<rect x="14" y="3" width="7" height="7" />
								<rect x="14" y="14" width="7" height="7" />
								<rect x="3" y="14" width="7" height="7" />
							</svg>
						</div>
					{/snippet}
				</EmptyState>
			{/if}

			<!-- Grid -->
		{:else}
			<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
				{#each displayAddons as addon (addon.id)}
					{@const status = getAddonStatus(addon.id)}
					<button
						onclick={() => handleAddonClick(addon)}
						class="group flex flex-col rounded-xl border border-border-subtle bg-background p-4 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-border-strong hover:shadow-lg"
					>
						<!-- Icon -->
						<div
							class="mb-3 flex h-12 w-12 items-center justify-center overflow-hidden rounded-xl border border-border-subtle bg-surface-2"
						>
							{#if addon.logo}
								<img
									src={addon.logo}
									alt={addon.name}
									class="h-full w-full object-contain p-1.5"
									onerror={(e) => {
										const target = e.currentTarget as HTMLImageElement;
										target.style.display = 'none';
										if (target.nextElementSibling)
											(target.nextElementSibling as HTMLElement).style.display = 'flex';
									}}
								/>
								<div
									class="hidden h-full w-full items-center justify-center text-base font-medium text-muted"
								>
									{addon.name.charAt(0)}
								</div>
							{:else}
								<span class="text-base font-medium text-muted">{addon.name.charAt(0)}</span>
							{/if}
						</div>

						<!-- Name + description -->
						<h3 class="mb-0.5 truncate text-sm font-medium text-foreground">{addon.name}</h3>
						<p class="mb-3 line-clamp-2 text-xs leading-relaxed text-subtle">
							{addon.description || 'No description available.'}
						</p>

						<!-- Footer: category + status -->
						<div class="mt-auto flex items-center justify-between">
							<div class="flex items-center gap-2">
								{#if addon.tags[0]}
									<span class="text-[10px] text-muted">{capitalizeTag(addon.tags[0])}</span>
								{/if}
							</div>
							{#if status === 'connected'}
								<Badge variant="green">Connected</Badge>
							{:else if status === 'needs-auth'}
								<Badge variant="warning">Auth</Badge>
							{:else}
								<span
									class="shrink-0 rounded-full bg-accent/10 px-2.5 py-0.5 text-[11px] font-medium text-accent"
									>GET</span
								>
							{/if}
						</div>
					</button>
				{/each}
			</div>

			<!-- Infinite scroll sentinel -->
			{#if searchActive ? hasMoreSearch : hasMoreMarketplace}
				<div bind:this={scrollSentinelEl} class="flex justify-center py-8">
					{#if loadingMore || searchLoadingMore}
						<div class="flex items-center gap-2 text-sm text-muted">
							<LoadingSpinner />
							Loading more...
						</div>
					{/if}
				</div>
			{/if}

			<!-- Result count -->
			{#if displayAddons.length > 0}
				<div class="mt-2 pb-2 text-center text-[11px] text-muted">
					{#if statusFilter !== 'all' || selectedCategory !== 'All'}
						Showing {displayAddons.length} connectors
					{:else if searchActive}
						{searchResults.length} of {searchTotalCount} results
					{:else}
						{marketplaceAddons.length} of {marketplaceTotalCount} connectors
					{/if}
				</div>
			{/if}
		{/if}
	</div>
</div>
