<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
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
	import {
		getSkills,
		searchSkills,
		getCategories,
		installSkill,
		uninstallSkill,
		type SkillCatalog,
		type CategoryCount
	} from '$api/skills';
	import {
		listMySkills,
		deleteMySkill,
		uploadSkillFile,
		createFromGithub,
		type UserSkillSummary
	} from '$api/user_skills';
	import { ApiClientError } from '$api/client';

	// ── State ──
	let skills: SkillCatalog[] = $state([]);
	let categories: CategoryCount[] = $state([]);
	let loading = $state(true);
	let searchQuery = $state('');
	let selectedCategory = $state('');
	let selectedSource = $state('');

	// Pagination
	let page = $state(1);
	let totalCount = $state(0);
	let loadingMore = $state(false);

	// Search
	let searchResults: SkillCatalog[] = $state([]);
	let searchPage = $state(1);
	let searchTotalCount = $state(0);
	let searchLoading = $state(false);
	let searchLoadingMore = $state(false);

	// Install actions in progress
	let installingSet = $state(new Set<string>());

	// ── My Skills tab state ──
	type TabId = 'marketplace' | 'mine';
	let activeTab: TabId = $state('marketplace');

	const navItems: { id: TabId; label: string }[] = [
		{ id: 'marketplace', label: 'Marketplace' },
		{ id: 'mine', label: 'My Skills' }
	];

	let mySkills: UserSkillSummary[] = $state([]);
	let myLoading = $state(false);
	let myTotal = $state(0);

	let uploadInputEl: HTMLInputElement | undefined = $state();
	let uploadingFile = $state(false);
	let importingGithub = $state(false);

	let scrollSentinelEl: HTMLDivElement | undefined = $state();
	let observer: IntersectionObserver | null = null;
	let filterDropdownOpen = $state(false);

	// ── Derived ──
	let searchActive = $derived(searchQuery.trim().length > 0);
	let displaySkills = $derived(searchActive ? searchResults : skills);
	let hasMore = $derived(
		searchActive ? searchResults.length < searchTotalCount : skills.length < totalCount
	);

	// Source filter chips
	const sourceChips: { key: string; label: string }[] = [
		{ key: '', label: 'All' },
		{ key: 'official', label: 'Official' },
		{ key: 'community', label: 'Community' }
	];

	// ── Search ──
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

	// ── Data Loading ──
	async function loadSkills(): Promise<void> {
		if (page === 1 && skills.length === 0) loading = true;
		else if (page > 1) loadingMore = true;

		try {
			const response = await getSkills(page, selectedCategory, selectedSource);
			if (page === 1) {
				skills = response.items;
			} else {
				skills = [...skills, ...response.items];
			}
			totalCount = response.count;
		} catch {
			toasts.error('Failed to load skills');
		} finally {
			loading = false;
			loadingMore = false;
		}
	}

	async function loadSearchResults(): Promise<void> {
		if (searchPage === 1) searchLoading = true;
		else searchLoadingMore = true;

		try {
			const response = await searchSkills(searchQuery.trim(), searchPage);
			if (searchPage === 1) {
				searchResults = response.items;
			} else {
				searchResults = [...searchResults, ...response.items];
			}
			searchTotalCount = response.count;
		} catch {
			toasts.error('Failed to search skills');
		} finally {
			searchLoading = false;
			searchLoadingMore = false;
		}
	}

	async function loadCategories(): Promise<void> {
		try {
			categories = await getCategories();
		} catch {
			// Non-critical
		}
	}

	function handleCategoryChange(category: string): void {
		selectedCategory = category;
		page = 1;
		skills = [];
		loadSkills();
	}

	function handleSourceChange(source: string): void {
		selectedSource = source;
		page = 1;
		skills = [];
		loadSkills();
	}

	async function handleInstallToggle(skill: SkillCatalog): Promise<void> {
		if (installingSet.has(skill.slug)) return;
		installingSet = new Set([...installingSet, skill.slug]);

		try {
			if (skill.is_installed) {
				await uninstallSkill(skill.slug);
				skill.is_installed = false;
				skill.install_count = Math.max(0, skill.install_count - 1);
				toasts.success(`Uninstalled ${skill.name}`);
			} else {
				await installSkill(skill.slug);
				skill.is_installed = true;
				skill.install_count += 1;
				toasts.success(`Installed ${skill.name}`);
			}
			// Trigger reactivity
			skills = [...skills];
			if (searchActive) searchResults = [...searchResults];
		} catch {
			toasts.error(`Failed to ${skill.is_installed ? 'uninstall' : 'install'} ${skill.name}`);
		} finally {
			const next = new Set(installingSet);
			next.delete(skill.slug);
			installingSet = next;
		}
	}

	// ── My Skills: loaders + actions ──
	async function loadMySkills(): Promise<void> {
		myLoading = true;
		try {
			const response = await listMySkills(1);
			mySkills = response.items;
			myTotal = response.count;
		} catch {
			toasts.error('Failed to load your skills');
		} finally {
			myLoading = false;
		}
	}

	function openCreatePage(): void {
		goto('/skills/new');
	}

	function openEditPage(skill: UserSkillSummary): void {
		goto(`/skills/my/${skill.id}`);
	}

	async function handleUploadFile(e: Event): Promise<void> {
		const input = e.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		uploadingFile = true;
		try {
			const created = await uploadSkillFile(file);
			mySkills = [created, ...mySkills];
			myTotal += 1;
			toasts.success(`Imported ${created.name}`);
		} catch (err) {
			const msg = err instanceof ApiClientError ? err.message : 'Failed to upload skill';
			toasts.error(msg);
		} finally {
			uploadingFile = false;
			if (input) input.value = '';
		}
	}

	async function handleImportGithub(): Promise<void> {
		const url = prompt(
			'Public GitHub URL (repo root or /tree/branch/path to a directory with SKILL.md):'
		);
		if (!url?.trim()) return;
		importingGithub = true;
		try {
			const created = await createFromGithub(url.trim());
			mySkills = [created, ...mySkills];
			myTotal += 1;
			toasts.success(`Imported ${created.name}`);
		} catch (err) {
			const msg = err instanceof ApiClientError ? err.message : 'Failed to import from GitHub';
			toasts.error(msg);
		} finally {
			importingGithub = false;
		}
	}

	async function handleDeleteMySkill(skill: UserSkillSummary): Promise<void> {
		if (!confirm(`Delete "${skill.name}"? This cannot be undone.`)) return;
		try {
			await deleteMySkill(skill.id);
			mySkills = mySkills.filter((s) => s.id !== skill.id);
			myTotal = Math.max(0, myTotal - 1);
			toasts.success(`Deleted ${skill.name}`);
		} catch {
			toasts.error(`Failed to delete ${skill.name}`);
		}
	}

	function switchTab(tab: TabId): void {
		activeTab = tab;
		if (tab === 'mine' && mySkills.length === 0 && !myLoading) {
			loadMySkills();
		}
	}

	// Intersection observer for infinite scroll
	function setupIntersectionObserver(): void {
		if (observer) observer.disconnect();
		observer = new IntersectionObserver(
			(entries) => {
				if (!entries[0]?.isIntersecting) return;
				if (searchActive) {
					if (searchResults.length < searchTotalCount && !searchLoadingMore && !searchLoading) {
						searchPage += 1;
						loadSearchResults();
					}
				} else {
					if (skills.length < totalCount && !loadingMore && !loading) {
						page += 1;
						loadSkills();
					}
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

	onMount(() => {
		pageTitle.set('Skills');
		showHeaderTitle.set(false);
		loadSkills();
		loadCategories();
	});

	onDestroy(() => {
		if (searchTimer) clearTimeout(searchTimer);
	});
</script>

<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (!target.closest('[data-skills-dropdown]')) {
			filterDropdownOpen = false;
		}
	}}
/>

<svelte:head>
	<title>Skills - Jatayu AI</title>
</svelte:head>

<div class="flex w-full">
	<SideNav
		bind:value={activeTab}
		items={navItems}
		title="Skills"
		searchParamKey="section"
		onchange={(id) => switchTab(id)}
		class="px-4 py-8"
	/>

	<div class="min-w-0 flex-1 px-6 py-8">
		{#if activeTab === 'mine'}
			<div class="mb-4 flex justify-end gap-2">
				<button
					type="button"
					onclick={() => uploadInputEl?.click()}
					disabled={uploadingFile}
					class="rounded-full border border-border px-3 py-1.5 text-sm text-subtle hover:border-border-strong disabled:opacity-50"
					title="Upload a SKILL.md file or .zip bundle"
				>
					{uploadingFile ? 'Uploading...' : 'Upload file'}
				</button>
				<button
					type="button"
					onclick={handleImportGithub}
					disabled={importingGithub}
					class="rounded-full border border-border px-3 py-1.5 text-sm text-subtle hover:border-border-strong disabled:opacity-50"
				>
					{importingGithub ? 'Importing...' : 'Import from GitHub'}
				</button>
				<button
					type="button"
					onclick={openCreatePage}
					class="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90"
				>
					+ New skill
				</button>
				<input
					bind:this={uploadInputEl}
					type="file"
					accept=".md,.markdown,.zip"
					class="hidden"
					onchange={handleUploadFile}
				/>
			</div>
		{/if}

		{#if activeTab === 'marketplace'}
			<!-- Toolbar -->
			<div class="mb-4 flex items-center gap-3">
				<div class="flex flex-1 items-center gap-3">
					<div class="w-56">
						<SearchInput
							bind:value={searchQuery}
							oninput={handleSearchInput}
							placeholder="Search skills..."
							showCancel={searchActive}
							onclear={clearSearch}
						/>
					</div>

					<!-- Filter dropdown -->
					<div class="relative" data-skills-dropdown>
						<button
							onclick={(e) => {
								e.stopPropagation();
								filterDropdownOpen = !filterDropdownOpen;
							}}
							class="inline-flex h-9 items-center gap-2 rounded-xl border border-border px-3.5 text-sm transition-colors hover:border-border-strong {selectedCategory ||
							selectedSource
								? 'font-medium text-foreground'
								: 'text-subtle'}"
						>
							Filter
							{#if selectedCategory || selectedSource}
								<span
									class="flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-surface-2 px-1 text-[10px] font-medium text-foreground"
								>
									{(selectedCategory ? 1 : 0) + (selectedSource ? 1 : 0)}
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
								class="absolute left-0 z-50 mt-1.5 w-52 animate-[fadeInUp_100ms_ease-out] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-sm"
								role="menu"
								tabindex="-1"
							>
								<!-- Source section -->
								<p
									class="px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted uppercase"
								>
									Source
								</p>
								{#each sourceChips as chip (chip.key)}
									<button
										onclick={() => handleSourceChange(chip.key)}
										class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors {selectedSource ===
										chip.key
											? 'bg-surface-2 font-medium text-foreground'
											: 'text-subtle hover:bg-surface-2 hover:text-foreground'}"
										role="menuitem"
									>
										{chip.label}
									</button>
								{/each}

								<!-- Category section -->
								{#if categories.length > 0}
									<div class="mx-2 my-1 border-t border-border-subtle"></div>
									<p
										class="px-3 pt-2 pb-1 text-[11px] font-medium tracking-wide text-muted uppercase"
									>
										Category
									</p>
									<div class="max-h-48 overflow-y-auto">
										<button
											onclick={() => handleCategoryChange('')}
											class="flex w-full items-center rounded-lg px-3 py-2 text-left text-sm transition-colors {selectedCategory ===
											''
												? 'bg-surface-2 font-medium text-foreground'
												: 'text-subtle hover:bg-surface-2 hover:text-foreground'}"
											role="menuitem"
										>
											All
										</button>
										{#each categories as cat (cat.category)}
											<button
												onclick={() => handleCategoryChange(cat.category)}
												class="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors {selectedCategory ===
												cat.category
													? 'bg-surface-2 font-medium text-foreground'
													: 'text-subtle hover:bg-surface-2 hover:text-foreground'}"
												role="menuitem"
											>
												<span>{cat.icon} {cat.category}</span>
												<span class="text-[10px] text-muted">{cat.count}</span>
											</button>
										{/each}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			</div>

			<!-- Loading state -->
			{#if loading || (searchActive && searchLoading)}
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
					{#each [0, 1, 2, 3, 4, 5, 6, 7] as i (i)}
						<div class="flex flex-col rounded-xl border border-border-subtle bg-background p-4">
							<Skeleton class="mb-3 rounded-xl" width="48px" height="48px" stagger={i} />
							<Skeleton class="mb-1 rounded" width="70%" height="13px" stagger={i + 1} />
							<Skeleton class="mb-3 rounded" width="90%" height="10px" stagger={i + 2} />
							<div class="mt-auto flex items-center justify-between">
								<Skeleton class="rounded" width="48px" height="10px" />
								<Skeleton class="rounded-full" width="56px" height="24px" />
							</div>
						</div>
					{/each}
				</div>

				<!-- Empty state -->
			{:else if displaySkills.length === 0}
				{#if searchActive}
					<EmptyState
						title={`No skills matching \u201C${searchQuery}\u201D`}
						description="Try a different search term."
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
				{:else}
					<EmptyState
						title="No skills available"
						description="Run the skill crawler to populate the marketplace."
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
									<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
									<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
								</svg>
							</div>
						{/snippet}
					</EmptyState>
				{/if}

				<!-- Grid -->
			{:else}
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
					{#each displaySkills as skill (skill.id)}
						{@const isInstalling = installingSet.has(skill.slug)}
						<div
							class="card-hover group flex flex-col rounded-xl border border-border-subtle bg-background p-4"
						>
							<!-- Icon + source badge -->
							<div class="mb-3 flex items-start justify-between">
								<div
									class="flex h-12 w-12 items-center justify-center rounded-xl border border-border-subtle bg-surface-2 text-xl"
								>
									{skill.icon || '📦'}
								</div>
								{#if skill.source_type === 'official'}
									<Badge variant="green">Official</Badge>
								{/if}
							</div>

							<!-- Name + description -->
							<button
								onclick={() => goto(`/skills/${skill.slug}`)}
								class="mb-0.5 truncate text-left text-sm font-medium text-foreground hover:underline"
							>
								{skill.name}
							</button>
							<p class="mb-3 line-clamp-2 text-xs leading-relaxed text-subtle">
								{skill.description || 'No description available.'}
							</p>

							<!-- Footer: category + install button -->
							<div class="mt-auto flex items-center justify-between">
								<div class="flex items-center gap-2">
									<span class="text-[10px] text-muted">{skill.category}</span>
									{#if skill.install_count > 0}
										<span class="text-[10px] text-muted"
											>{skill.install_count.toLocaleString()}</span
										>
									{/if}
								</div>
								<button
									onclick={(e) => {
										e.stopPropagation();
										handleInstallToggle(skill);
									}}
									disabled={isInstalling}
									class="shrink-0 rounded-full px-3 py-1 text-[11px] font-medium transition-colors {skill.is_installed
										? 'bg-success/10 text-success hover:bg-red-50 hover:text-red-500'
										: 'bg-accent/10 text-accent hover:bg-accent/20'} disabled:opacity-50"
								>
									{#if isInstalling}
										<LoadingSpinner size="xs" />
									{:else if skill.is_installed}
										Installed
									{:else}
										Install
									{/if}
								</button>
							</div>
						</div>
					{/each}
				</div>

				<!-- Infinite scroll sentinel -->
				{#if hasMore}
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
				{#if displaySkills.length > 0}
					<div class="mt-2 pb-2 text-center text-[11px] text-muted">
						{#if searchActive}
							{searchResults.length} of {searchTotalCount} results
						{:else}
							{skills.length} of {totalCount} skills
						{/if}
					</div>
				{/if}
			{/if}
		{:else}
			<!-- My Skills tab -->
			{#if myLoading}
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
					{#each [0, 1, 2, 3] as i (i)}
						<div class="flex flex-col rounded-xl border border-border-subtle bg-background p-4">
							<Skeleton class="mb-3 rounded-xl" width="48px" height="48px" stagger={i} />
							<Skeleton class="mb-1 rounded" width="70%" height="13px" stagger={i + 1} />
							<Skeleton class="mb-3 rounded" width="90%" height="10px" stagger={i + 2} />
						</div>
					{/each}
				</div>
			{:else if mySkills.length === 0}
				<EmptyState
					title="No skills yet"
					description="Write your own, upload a SKILL.md or .zip bundle, or import from GitHub."
					ctaLabel="Create your first skill"
					onctaclick={openCreatePage}
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
								<path d="M12 20h9" />
								<path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
							</svg>
						</div>
					{/snippet}
				</EmptyState>
			{:else}
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
					{#each mySkills as skill (skill.id)}
						<div
							class="card-hover group flex flex-col rounded-xl border border-border-subtle bg-background p-4"
						>
							<div class="mb-3 flex items-start justify-between">
								<div
									class="flex h-12 w-12 items-center justify-center rounded-xl border border-border-subtle bg-surface-2 text-xl"
								>
									{skill.icon || '📦'}
								</div>
								<span class="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] text-muted">
									{skill.source === 'editor'
										? 'Written'
										: skill.source === 'upload_md'
											? 'Uploaded'
											: skill.source === 'upload_zip'
												? 'Bundle'
												: 'GitHub'}
								</span>
							</div>
							<div class="mb-0.5 truncate text-sm font-medium text-foreground">{skill.name}</div>
							<p class="mb-3 line-clamp-2 text-xs leading-relaxed text-subtle">
								{skill.description || 'No description.'}
							</p>
							<div class="mt-auto flex items-center justify-between">
								<span class="text-[10px] text-muted">{skill.category || '—'}</span>
								<div class="flex gap-1">
									<button
										type="button"
										onclick={() => openEditPage(skill)}
										class="rounded-full bg-surface-2 px-3 py-1 text-[11px] font-medium text-subtle hover:bg-surface-2 hover:text-foreground"
									>
										Edit
									</button>
									<button
										type="button"
										onclick={() => handleDeleteMySkill(skill)}
										class="rounded-full bg-surface-2 px-3 py-1 text-[11px] font-medium text-subtle hover:bg-red-50 hover:text-red-500"
									>
										Delete
									</button>
								</div>
							</div>
						</div>
					{/each}
				</div>
				<div class="mt-2 pb-2 text-center text-[11px] text-muted">
					{mySkills.length} skill{mySkills.length === 1 ? '' : 's'}
				</div>
			{/if}
		{/if}
	</div>
</div>
