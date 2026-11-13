<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { fade, fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import {
		Badge,
		Skeleton,
		EmptyState,
		ConfirmationDialog,
		SearchInput,
		LoadingSpinner
	} from '$components/ui';
	import FilePreviewDialog from '$components/chat/FilePreviewDialog.svelte';
	import ShareAccessDialog from '$components/chat/ShareAccessDialog.svelte';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import {
		toggleFavourite,
		favouriteIds,
		isFavourite,
		formatRelativeTime,
		renameConversationLocal,
		removeConversationLocal,
		setConversationSharedLocal
	} from '$stores/conversations';
	import {
		getConversations,
		searchConversations,
		deleteConversation,
		renameConversation
	} from '$api/conversations';
	import { getUserFiles, getFileDownloadUrl } from '$api/files';
	import { pullToRefresh } from '$lib/actions/gestures';
	import { tooltip } from '$lib/actions/tooltip';
	import { conversations as conversationsStore } from '$stores/conversations';
	import { isSessionFresh, markSessionFetched } from '$stores/freshness';
	import { get } from 'svelte/store';
	import type { Conversation, StoredFile } from '$api/types';

	// Active tab
	type Tab = 'chats' | 'files';
	let activeTab: Tab = $state('chats');

	// Filter state
	type ChatFilter = 'all' | 'favourites' | 'running' | 'shared';
	let activeFilter: ChatFilter = $state('all');

	// View mode
	type ViewMode = 'list' | 'grid';
	let viewMode: ViewMode = $state('list');

	// Conversations state — seed from sidebar store to avoid loading flash
	const cachedConvs = get(conversationsStore);
	let conversations: Conversation[] = $state(cachedConvs.length > 0 ? cachedConvs : []);
	let loading = $state(cachedConvs.length === 0);
	let loadingMore = $state(false);
	let searchQuery = $state('');
	let page = $state(1);
	let totalCount = $state(0);
	let scrollSentinelEl: HTMLDivElement | undefined = $state();
	let observer: IntersectionObserver | null = null;

	let hasMore = $derived(conversations.length < totalCount);

	// Favourites subscription
	let favs = $state<Set<string>>(new Set());
	favouriteIds.subscribe((v) => (favs = v));

	// Filtered conversations
	let filteredConversations = $derived.by(() => {
		if (activeFilter === 'all') return conversations;
		if (activeFilter === 'favourites') return conversations.filter((c) => isFavourite(c.id, favs));
		if (activeFilter === 'running')
			return conversations.filter((c) => c.status === 'running' || c.on_going);
		if (activeFilter === 'shared')
			return conversations.filter((c) => !!(c.metadata as Record<string, unknown>)?.shared);
		return conversations;
	});

	// Inline rename state
	let renamingId: string | null = $state(null);
	let renameValue = $state('');
	let renameInputEl: HTMLInputElement | undefined = $state();

	// Delete confirmation
	let deleteConfirmId: string | null = $state(null);
	let deleteConfirmTitle = $state('');

	// Active dropdown
	let activeDropdownId: string | null = $state(null);
	let filterDropdownOpen = $state(false);
	let shareDialogOpen = $state(false);
	let shareDialogConversation: Conversation | null = $state(null);

	// Debounced search
	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	let searchActive = $derived(searchQuery.trim().length > 0);

	function handleSearchInput(): void {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => {
			page = 1;
			conversations = [];
			loadConversations();
		}, 300);
	}

	function clearSearch(): void {
		searchQuery = '';
		page = 1;
		conversations = [];
		loadConversations();
	}

	async function loadConversations(): Promise<void> {
		if (page === 1 && conversations.length === 0) loading = true;
		else if (page > 1) loadingMore = true;

		try {
			const response = searchQuery.trim()
				? await searchConversations(searchQuery.trim(), page)
				: await getConversations(page);
			if (page === 1) {
				conversations = response.items;
			} else {
				conversations = [...conversations, ...response.items];
			}
			totalCount = response.count;
			if (page === 1) markSessionFetched('midsphere-library');
		} catch {
			toasts.error('Failed to load conversations');
		} finally {
			loading = false;
			loadingMore = false;
		}
	}

	function loadMore(): void {
		if (loadingMore || !hasMore) return;
		page += 1;
		loadConversations();
	}

	function getStatusBadge(conv: Conversation): {
		label: string;
		variant: 'green' | 'coral' | 'muted' | 'warning';
	} {
		if (conv.status === 'running' || conv.on_going) return { label: 'Running', variant: 'coral' };
		if (conv.status === 'failed' || conv.has_error) return { label: 'Failed', variant: 'warning' };
		if (conv.status === 'cancelled') return { label: 'Cancelled', variant: 'muted' };
		return { label: 'Completed', variant: 'green' };
	}

	function handleConversationClick(conv: Conversation): void {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto(`/chat/${conv.id}`);
	}

	// Dropdown actions
	function toggleDropdown(convId: string, e: MouseEvent): void {
		e.stopPropagation();
		activeDropdownId = activeDropdownId === convId ? null : convId;
	}

	function closeDropdowns(): void {
		activeDropdownId = null;
	}

	function handleRename(conv: Conversation): void {
		activeDropdownId = null;
		renamingId = conv.id;
		renameValue = conv.title || '';
		requestAnimationFrame(() => {
			renameInputEl?.focus();
			renameInputEl?.select();
		});
	}

	async function submitRename(): Promise<void> {
		if (!renamingId) return;
		const id = renamingId;
		const newTitle = renameValue.trim();
		renamingId = null;

		if (!newTitle) return;

		// Optimistic update
		conversations = conversations.map((c) => (c.id === id ? { ...c, title: newTitle } : c));
		renameConversationLocal(id, newTitle);

		try {
			await renameConversation(id, newTitle);
			toasts.success('Conversation renamed');
		} catch {
			toasts.error('Failed to rename');
		}
	}

	function handleRenameKeydown(e: KeyboardEvent): void {
		if (e.key === 'Enter') {
			e.preventDefault();
			submitRename();
		} else if (e.key === 'Escape') {
			renamingId = null;
		}
	}

	function handleFavourite(conv: Conversation, e?: MouseEvent): void {
		e?.stopPropagation();
		activeDropdownId = null;
		const wasFav = isFavourite(conv.id, favs);
		toggleFavourite(conv.id);
		toasts.success(wasFav ? 'Removed from favourites' : 'Added to favourites');
	}

	function handleShare(conv: Conversation): void {
		activeDropdownId = null;
		shareDialogConversation = conv;
		shareDialogOpen = true;
	}

	function handleSharedAccessChange(shared: boolean): void {
		const activeConversation = shareDialogConversation;
		if (!activeConversation) return;

		conversations = conversations.map((c) => {
			if (c.id !== activeConversation.id) return c;
			return {
				...c,
				metadata: {
					...(c.metadata ?? {}),
					shared
				}
			};
		});
		setConversationSharedLocal(activeConversation.id, shared);
		shareDialogConversation = {
			...activeConversation,
			metadata: {
				...(activeConversation.metadata ?? {}),
				shared
			}
		};
	}

	function handleDeletePrompt(conv: Conversation): void {
		activeDropdownId = null;
		deleteConfirmId = conv.id;
		deleteConfirmTitle = conv.title || 'Untitled';
	}

	async function confirmDelete(): Promise<void> {
		if (!deleteConfirmId) return;
		const id = deleteConfirmId;
		deleteConfirmId = null;

		// Optimistic removal
		conversations = conversations.filter((c) => c.id !== id);
		totalCount = Math.max(0, totalCount - 1);
		removeConversationLocal(id);

		try {
			await deleteConversation(id);
			toasts.success('Conversation deleted');
		} catch {
			toasts.error('Failed to delete conversation');
			// Reload to restore state
			page = 1;
			loadConversations();
		}
	}

	function handleExport(conv: Conversation): void {
		activeDropdownId = null;
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto(`/chat/${conv.id}`);
		toasts.info('Use the export button in the chat header');
	}

	// Intersection observer for infinite scroll (conversations)
	function setupIntersectionObserver(): void {
		if (observer) observer.disconnect();
		observer = new IntersectionObserver(
			(entries) => {
				if (entries[0]?.isIntersecting && hasMore && !loadingMore && !loading) {
					loadMore();
				}
			},
			{ rootMargin: '200px' }
		);
		if (scrollSentinelEl) {
			observer.observe(scrollSentinelEl);
		}
	}

	$effect(() => {
		if (scrollSentinelEl) {
			setupIntersectionObserver();
		}
		return () => {
			if (observer) observer.disconnect();
		};
	});

	// =====================
	// Files tab state
	// =====================

	let files: StoredFile[] = $state([]);
	let filesLoading = $state(false);
	let filesLoadingMore = $state(false);
	let filesPage = $state(1);
	let filesTotalCount = $state(0);
	let filesScrollSentinelEl: HTMLDivElement | undefined = $state();
	let filesObserver: IntersectionObserver | null = null;
	let filesHasMore = $derived(files.length < filesTotalCount);
	let filesLoaded = false;

	// File preview state
	let previewOpen = $state(false);
	let previewFilename = $state('');
	let previewFileUrl = $state('');

	// File type detection
	type FileCategory =
		'image' | 'pdf' | 'video' | 'audio' | 'code' | 'document' | 'archive' | 'unknown';

	const fileExtensionMap: Record<string, FileCategory> = {
		jpg: 'image',
		jpeg: 'image',
		png: 'image',
		gif: 'image',
		webp: 'image',
		svg: 'image',
		bmp: 'image',
		ico: 'image',
		pdf: 'pdf',
		mp4: 'video',
		webm: 'video',
		mov: 'video',
		avi: 'video',
		mkv: 'video',
		mp3: 'audio',
		wav: 'audio',
		ogg: 'audio',
		flac: 'audio',
		aac: 'audio',
		js: 'code',
		ts: 'code',
		jsx: 'code',
		tsx: 'code',
		py: 'code',
		rb: 'code',
		go: 'code',
		rs: 'code',
		java: 'code',
		cpp: 'code',
		c: 'code',
		h: 'code',
		css: 'code',
		scss: 'code',
		html: 'code',
		json: 'code',
		yaml: 'code',
		yml: 'code',
		xml: 'code',
		sql: 'code',
		sh: 'code',
		md: 'document',
		txt: 'document',
		log: 'document',
		csv: 'document',
		rtf: 'document',
		doc: 'document',
		docx: 'document',
		xls: 'document',
		xlsx: 'document',
		ppt: 'document',
		pptx: 'document',
		zip: 'archive',
		tar: 'archive',
		gz: 'archive',
		rar: 'archive',
		'7z': 'archive'
	};

	function getFileCategory(filename: string): FileCategory {
		const ext = filename.split('.').pop()?.toLowerCase() || '';
		return fileExtensionMap[ext] || 'unknown';
	}

	function getFileExtension(filename: string): string {
		return filename.split('.').pop()?.toUpperCase() || '';
	}

	function isImageFile(filename: string): boolean {
		return getFileCategory(filename) === 'image';
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function formatFileDate(dateStr: string): string {
		try {
			return new Intl.DateTimeFormat('en', {
				hour: '2-digit',
				minute: '2-digit'
			}).format(new Date(dateStr));
		} catch {
			return '';
		}
	}

	// Group files by day
	type FileGroup = { label: string; files: StoredFile[] };

	function groupFilesByDay(items: StoredFile[]): FileGroup[] {
		const result: FileGroup[] = [];
		const now = new Date();
		const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
		const yesterday = new Date(today.getTime() - 86400000);

		for (const file of items) {
			const date = new Date(file.uploaded_at);
			const dateOnly = new Date(date.getFullYear(), date.getMonth(), date.getDate());
			let label: string;

			if (dateOnly.getTime() === today.getTime()) {
				label = 'Today';
			} else if (dateOnly.getTime() === yesterday.getTime()) {
				label = 'Yesterday';
			} else if (dateOnly.getFullYear() === now.getFullYear()) {
				label = new Intl.DateTimeFormat('en', {
					weekday: 'long',
					month: 'long',
					day: 'numeric'
				}).format(date);
			} else {
				label = new Intl.DateTimeFormat('en', {
					month: 'long',
					day: 'numeric',
					year: 'numeric'
				}).format(date);
			}

			const existing = result.find((g) => g.label === label);
			if (existing) {
				existing.files.push(file);
			} else {
				result.push({ label, files: [file] });
			}
		}

		return result;
	}

	let fileGroups = $derived(groupFilesByDay(files));

	async function loadFiles(): Promise<void> {
		if (filesPage === 1) filesLoading = true;
		else filesLoadingMore = true;

		try {
			const response = await getUserFiles(filesPage);
			if (filesPage === 1) {
				files = response.items;
			} else {
				files = [...files, ...response.items];
			}
			filesTotalCount = response.count;
		} catch {
			toasts.error('Failed to load files');
		} finally {
			filesLoading = false;
			filesLoadingMore = false;
		}
	}

	function loadMoreFiles(): void {
		if (filesLoadingMore || !filesHasMore) return;
		filesPage += 1;
		loadFiles();
	}

	async function handleFileClick(file: StoredFile): Promise<void> {
		try {
			const result = await getFileDownloadUrl(file.id);
			previewFilename = file.name;
			previewFileUrl = result.url;
			previewOpen = true;
		} catch {
			toasts.error('Failed to load file preview');
		}
	}

	async function handleFileDownload(file: StoredFile): Promise<void> {
		try {
			const result = await getFileDownloadUrl(file.id);
			const a = document.createElement('a');
			a.href = result.url;
			a.download = file.name;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);
		} catch {
			toasts.error('Failed to download file');
		}
	}

	// Intersection observer for infinite scroll (files)
	function setupFilesIntersectionObserver(): void {
		if (filesObserver) filesObserver.disconnect();
		filesObserver = new IntersectionObserver(
			(entries) => {
				if (entries[0]?.isIntersecting && filesHasMore && !filesLoadingMore && !filesLoading) {
					loadMoreFiles();
				}
			},
			{ rootMargin: '200px' }
		);
		if (filesScrollSentinelEl) {
			filesObserver.observe(filesScrollSentinelEl);
		}
	}

	$effect(() => {
		if (filesScrollSentinelEl) {
			setupFilesIntersectionObserver();
		}
		return () => {
			if (filesObserver) filesObserver.disconnect();
		};
	});

	// Load files when switching to files tab
	$effect(() => {
		if (activeTab === 'files' && !filesLoaded) {
			filesLoaded = true;
			loadFiles();
		}
	});

	async function handlePullRefresh(): Promise<void> {
		if (activeTab === 'chats') {
			page = 1;
			conversations = [];
			await loadConversations();
		} else {
			filesPage = 1;
			files = [];
			await loadFiles();
		}
	}

	// Filter chip definitions
	const filterChips: { key: ChatFilter; label: string; icon: string }[] = [
		{
			key: 'all',
			label: 'All',
			icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1'
		},
		{
			key: 'favourites',
			label: 'Favourites',
			icon: 'M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 21 12 17.77 5.82 21 7 14.14l-5-4.87 6.91-1.01L12 2'
		},
		{
			key: 'running',
			label: 'Running',
			icon: 'M13 10V3L4 14h7v7l9-11h-7z'
		},
		{
			key: 'shared',
			label: 'Shared',
			icon: 'M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0'
		}
	];

	onMount(() => {
		pageTitle.set('Library');
		showHeaderTitle.set(false);
		if (!isSessionFresh('midsphere-library', 60_000)) loadConversations();
	});
</script>

<!-- Click outside handler for dropdowns -->
<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (!target.closest('[data-library-dropdown]')) {
			closeDropdowns();
			filterDropdownOpen = false;
		}
	}}
/>

<svelte:head>
	<title>Library - Jatayu AI</title>
</svelte:head>

<div
	class="mx-auto flex w-full max-w-6xl flex-col px-4 pt-16 pb-6 sm:px-6 lg:px-8"
	use:pullToRefresh={{ onRefresh: handlePullRefresh }}
>
	<!-- Page title -->
	<div class="mb-4 flex items-center gap-2.5">
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="22"
			height="22"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
			class="text-foreground"
		>
			<path
				d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"
			/>
		</svg>
		<h1 class="text-2xl font-normal tracking-tight text-foreground">Library</h1>
	</div>

	<!-- Toolbar -->
	<div class="mb-4 flex items-center gap-3">
		<!-- Left: Search + Filter -->
		<div class="flex flex-1 items-center gap-3">
			<div class="w-56">
				<SearchInput
					bind:value={searchQuery}
					oninput={handleSearchInput}
					placeholder="Search"
					showCancel={searchActive}
					onclear={clearSearch}
				/>
			</div>

			{#if activeTab === 'chats'}
				<!-- Filter dropdown -->
				<div class="relative" data-library-dropdown>
					<button
						onclick={(e) => {
							e.stopPropagation();
							filterDropdownOpen = !filterDropdownOpen;
						}}
						class="inline-flex h-9 items-center gap-2 rounded-xl border border-border px-3.5 text-sm transition-colors hover:border-border-strong {activeFilter !==
						'all'
							? 'font-medium text-foreground'
							: 'text-subtle'}"
					>
						{filterChips.find((c) => c.key === activeFilter)?.label ?? 'All'}
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
							class="absolute left-0 z-50 mt-1.5 w-44 animate-[fadeInUp_100ms_ease-out] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-sm"
							role="menu"
							tabindex="-1"
						>
							{#each filterChips as chip (chip.key)}
								<button
									onclick={() => {
										activeFilter = chip.key;
										filterDropdownOpen = false;
									}}
									class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors {activeFilter ===
									chip.key
										? 'bg-surface-2 font-medium text-foreground'
										: 'text-subtle hover:bg-surface-2 hover:text-foreground'}"
									role="menuitem"
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
										class="shrink-0"
									>
										<path d={chip.icon} />
									</svg>
									{chip.label}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Right: Tabs + View toggle -->
		<div class="flex items-center gap-2">
			<div class="flex h-9 items-center gap-0.5 rounded-xl border border-border p-1">
				<button
					onclick={() => (activeTab = 'chats')}
					class="flex h-full items-center rounded-lg px-3.5 text-sm font-medium transition-colors {activeTab ===
					'chats'
						? 'bg-surface-2 text-foreground'
						: 'text-muted hover:text-foreground'}"
				>
					Chats
				</button>
				<button
					onclick={() => (activeTab = 'files')}
					class="flex h-full items-center rounded-lg px-3.5 text-sm font-medium transition-colors {activeTab ===
					'files'
						? 'bg-surface-2 text-foreground'
						: 'text-muted hover:text-foreground'}"
				>
					Files
				</button>
			</div>

			{#if activeTab === 'chats'}
				<div class="flex h-9 items-center gap-0.5 rounded-xl border border-border p-1">
					<button
						onclick={() => (viewMode = 'grid')}
						class="flex h-full w-7 items-center justify-center rounded-lg transition-all {viewMode ===
						'grid'
							? 'bg-surface-2 text-foreground'
							: 'text-muted hover:text-subtle'}"
						use:tooltip={'Grid view'}
						aria-label="Grid view"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="15"
							height="15"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<rect width="7" height="7" x="3" y="3" rx="1" />
							<rect width="7" height="7" x="14" y="3" rx="1" />
							<rect width="7" height="7" x="3" y="14" rx="1" />
							<rect width="7" height="7" x="14" y="14" rx="1" />
						</svg>
					</button>
					<button
						onclick={() => (viewMode = 'list')}
						class="flex h-full w-7 items-center justify-center rounded-lg transition-all {viewMode ===
						'list'
							? 'bg-surface-2 text-foreground'
							: 'text-muted hover:text-subtle'}"
						use:tooltip={'List view'}
						aria-label="List view"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="15"
							height="15"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<line x1="8" x2="21" y1="6" y2="6" />
							<line x1="8" x2="21" y1="12" y2="12" />
							<line x1="8" x2="21" y1="18" y2="18" />
							<line x1="3" x2="3.01" y1="6" y2="6" />
							<line x1="3" x2="3.01" y1="12" y2="12" />
							<line x1="3" x2="3.01" y1="18" y2="18" />
						</svg>
					</button>
				</div>
			{/if}
		</div>
	</div>

	{#if activeTab === 'chats'}
		<!-- Loading skeleton -->
		{#if loading}
			{#if viewMode === 'list'}
				<div class="flex flex-col" out:fade={{ duration: 80 }}>
					{#each [0, 1, 2, 3, 4, 5] as i (i)}
						<div class="rounded-lg px-3 py-2.5">
							<Skeleton
								class="rounded"
								width={i % 2 === 0 ? '50%' : '65%'}
								height="14px"
								stagger={i}
							/>
							<div class="mt-1">
								<Skeleton class="rounded" width="80%" height="12px" stagger={i + 1} />
							</div>
							<div class="mt-1.5 flex items-center gap-1.5">
								<Skeleton class="rounded" width="64px" height="11px" stagger={i + 2} />
								<Skeleton class="rounded" width="6px" height="6px" stagger={i + 2} />
								<Skeleton class="rounded" width="52px" height="11px" stagger={i + 3} />
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
					{#each [0, 1, 2, 3, 4, 5] as i (i)}
						<div class="overflow-hidden rounded-xl border border-border">
							<Skeleton class="!rounded-none" width="100%" height="112px" stagger={i} />
							<div class="p-3">
								<Skeleton class="rounded" width="70%" height="14px" stagger={i + 1} />
								<div class="mt-2">
									<Skeleton class="rounded" width="40%" height="12px" stagger={i + 2} />
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		{:else if filteredConversations.length === 0}
			<!-- Empty state -->
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
								><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /><path
									d="M8 11h6"
								/></svg
							>
						</div>
					{/snippet}
				</EmptyState>
			{:else if activeFilter !== 'all'}
				<EmptyState
					title="No {activeFilter} conversations"
					description={activeFilter === 'favourites'
						? 'Star your important conversations to find them quickly here.'
						: activeFilter === 'running'
							? 'No conversations are currently running.'
							: 'Share a conversation to see it here.'}
					ctaLabel="Show all"
					onctaclick={() => (activeFilter = 'all')}
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
								<path
									d={filterChips.find((c) => c.key === activeFilter)?.icon ??
										'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'}
								/>
							</svg>
						</div>
					{/snippet}
				</EmptyState>
			{:else}
				<EmptyState
					title="No conversations yet"
					description="Start a new chat to begin exploring what your AI agent can do."
					ctaLabel="Start a new chat"
					ctaHref="/"
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
								<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
							</svg>
						</div>
					{/snippet}
				</EmptyState>
			{/if}
		{:else}
			<!-- Conversation list view -->
			{#if viewMode === 'list'}
				<div class="flex flex-col" in:fade={{ duration: 150, delay: 50 }}>
					{#each filteredConversations as conv, i (conv.id)}
						{@const status = getStatusBadge(conv)}
						{@const isFav = isFavourite(conv.id, favs)}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class="card-hover group relative -mx-2 cursor-pointer rounded-lg px-3 py-2.5"
							in:fly={{ y: 6, duration: 120, delay: Math.min(i * 20, 200), easing: cubicOut }}
							onclick={() => handleConversationClick(conv)}
							onkeydown={(e) => e.key === 'Enter' && handleConversationClick(conv)}
							role="button"
							tabindex="0"
						>
							<!-- Title -->
							{#if renamingId === conv.id}
								<!-- svelte-ignore a11y_no_static_element_interactions -->
								<div onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
									<input
										bind:this={renameInputEl}
										bind:value={renameValue}
										onblur={submitRename}
										onkeydown={handleRenameKeydown}
										class="w-full max-w-sm rounded-lg border border-border-strong bg-background px-2.5 py-1 text-sm font-medium text-foreground outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
										aria-label="Rename conversation"
									/>
								</div>
							{:else}
								<h3 class="truncate text-sm font-medium text-foreground">
									{conv.title || 'Untitled'}
								</h3>
							{/if}

							<!-- Summary -->
							{#if conv.summary}
								<p class="mt-0.5 line-clamp-1 text-xs leading-normal text-subtle">
									{conv.summary}
								</p>
							{/if}

							<!-- Meta row -->
							<div class="mt-1 flex items-center gap-1.5">
								<span class="text-xs text-muted">
									{formatRelativeTime(conv.date_created)}
								</span>
								<span class="text-muted">·</span>
								<span class="text-xs text-muted">{status.label}</span>
								{#if isFav}
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="11"
										height="11"
										viewBox="0 0 24 24"
										fill="currentColor"
										stroke="currentColor"
										stroke-width="2"
										stroke-linecap="round"
										stroke-linejoin="round"
										class="shrink-0 text-yellow-500"
									>
										<polygon
											points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
										/>
									</svg>
								{/if}
								{#if (conv.metadata as Record<string, unknown>)?.shared}
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="11"
										height="11"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										stroke-linecap="round"
										stroke-linejoin="round"
										class="text-muted"
									>
										<circle cx="18" cy="5" r="3" />
										<circle cx="6" cy="12" r="3" />
										<circle cx="18" cy="19" r="3" />
										<line x1="8.59" x2="15.42" y1="13.51" y2="17.49" />
										<line x1="15.41" x2="8.59" y1="6.51" y2="10.49" />
									</svg>
								{/if}
							</div>

							<!-- Actions dropdown -->
							<div class="absolute top-2.5 right-1" data-library-dropdown>
								<button
									onclick={(e) => toggleDropdown(conv.id, e)}
									class="rounded-lg p-1.5 text-muted opacity-0 transition-all duration-200 hover:bg-surface-2 hover:text-foreground group-hover:opacity-100 {activeDropdownId ===
									conv.id
										? 'opacity-100 bg-surface text-subtle'
										: ''}"
									use:tooltip={'More options'}
									aria-label="More options"
									aria-expanded={activeDropdownId === conv.id}
									aria-haspopup="true"
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="16"
										height="16"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										stroke-linecap="round"
										stroke-linejoin="round"
									>
										<circle cx="12" cy="5" r="1" />
										<circle cx="12" cy="12" r="1" />
										<circle cx="12" cy="19" r="1" />
									</svg>
								</button>

								{#if activeDropdownId === conv.id}
									<div
										class="absolute top-full right-0 z-50 mt-1 w-48 animate-[fadeInUp_150ms_ease-out] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-sm"
										role="menu"
										tabindex="-1"
										onclick={(e) => e.stopPropagation()}
										onkeydown={(e) => e.stopPropagation()}
									>
										<button
											onclick={() => handleRename(conv)}
											class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
											role="menuitem"
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
												<path d="M17 3a2.85 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5Z" />
												<path d="m15 5 4 4" />
											</svg>
											Rename
										</button>
										<button
											onclick={() => handleFavourite(conv)}
											class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
											role="menuitem"
										>
											{#if isFav}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="14"
													height="14"
													viewBox="0 0 24 24"
													fill="currentColor"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="text-yellow-500"
												>
													<polygon
														points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
													/>
												</svg>
												Unfavourite
											{:else}
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
													<polygon
														points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
													/>
												</svg>
												Favourite
											{/if}
										</button>
										<button
											onclick={() => handleShare(conv)}
											class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
											role="menuitem"
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
												<circle cx="18" cy="5" r="3" />
												<circle cx="6" cy="12" r="3" />
												<circle cx="18" cy="19" r="3" />
												<line x1="8.59" x2="15.42" y1="13.51" y2="17.49" />
												<line x1="15.41" x2="8.59" y1="6.51" y2="10.49" />
											</svg>
											Shared Link
										</button>
										<button
											onclick={() => handleExport(conv)}
											class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
											role="menuitem"
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
												<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
												<polyline points="7 10 12 15 17 10" />
												<line x1="12" x2="12" y1="15" y2="3" />
											</svg>
											Export
										</button>
										<div class="my-1 border-t border-border-subtle"></div>
										<button
											onclick={() => handleDeletePrompt(conv)}
											class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-red-500 transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
											role="menuitem"
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
												<path d="M3 6h18" />
												<path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
												<path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
												<line x1="10" x2="10" y1="11" y2="17" />
												<line x1="14" x2="14" y1="11" y2="17" />
											</svg>
											Delete
										</button>
									</div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<!-- Grid view -->
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
					{#each filteredConversations as conv (conv.id)}
						{@const status = getStatusBadge(conv)}
						{@const isFav = isFavourite(conv.id, favs)}
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class="group relative flex cursor-pointer flex-col overflow-hidden rounded-xl border border-border bg-background transition-all duration-200 hover:border-border-strong hover:shadow-sm"
							onclick={() => handleConversationClick(conv)}
							onkeydown={(e) => e.key === 'Enter' && handleConversationClick(conv)}
							role="button"
							tabindex="0"
						>
							<!-- Preview area -->
							<div class="flex h-28 items-center justify-center bg-surface-2/60">
								<div class="flex flex-col items-center gap-2 text-muted">
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="36"
										height="36"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="1.5"
										stroke-linecap="round"
										stroke-linejoin="round"
									>
										<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
									</svg>
								</div>
							</div>

							<!-- Info area -->
							<div class="flex items-start justify-between gap-2 p-3">
								<div class="min-w-0 flex-1">
									{#if renamingId === conv.id}
										<!-- svelte-ignore a11y_no_static_element_interactions -->
										<div
											onclick={(e) => e.stopPropagation()}
											onkeydown={(e) => e.stopPropagation()}
										>
											<input
												bind:this={renameInputEl}
												bind:value={renameValue}
												onblur={submitRename}
												onkeydown={handleRenameKeydown}
												class="w-full rounded-lg border border-border-strong bg-background px-2 py-1 text-sm text-foreground outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
												aria-label="Rename conversation"
											/>
										</div>
									{:else}
										<h3 class="truncate text-[13px] font-medium text-foreground">
											{conv.title || 'Untitled'}
										</h3>
									{/if}
									<p class="mt-0.5 text-xs text-muted">
										{formatRelativeTime(conv.date_created)}
									</p>
									<div class="mt-1 flex items-center gap-1.5">
										<Badge variant={status.variant}>{status.label}</Badge>
										{#if isFav}
											<svg
												xmlns="http://www.w3.org/2000/svg"
												width="11"
												height="11"
												viewBox="0 0 24 24"
												fill="currentColor"
												stroke="currentColor"
												stroke-width="2"
												class="text-yellow-500"
											>
												<polygon
													points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
												/>
											</svg>
										{/if}
										{#if (conv.metadata as Record<string, unknown>)?.shared}
											<span class="inline-flex items-center gap-1 text-[11px] text-muted">
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="10"
													height="10"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
												>
													<circle cx="18" cy="5" r="3" />
													<circle cx="6" cy="12" r="3" />
													<circle cx="18" cy="19" r="3" />
													<line x1="8.59" x2="15.42" y1="13.51" y2="17.49" />
													<line x1="15.41" x2="8.59" y1="6.51" y2="10.49" />
												</svg>
												Shared
											</span>
										{/if}
									</div>
								</div>

								<!-- Dropdown trigger -->
								<div data-library-dropdown>
									<button
										onclick={(e) => toggleDropdown(conv.id, e)}
										class="flex h-7 w-7 items-center justify-center rounded-lg text-muted opacity-0 transition-all hover:bg-surface-2 hover:text-foreground group-hover:opacity-100 {activeDropdownId ===
										conv.id
											? 'opacity-100 text-subtle'
											: ''}"
										use:tooltip={'More options'}
										aria-label="More options"
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="16"
											height="16"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
										>
											<circle cx="12" cy="5" r="1" />
											<circle cx="12" cy="12" r="1" />
											<circle cx="12" cy="19" r="1" />
										</svg>
									</button>

									{#if activeDropdownId === conv.id}
										<div
											class="absolute right-4 bottom-0 z-50 w-44 translate-y-full animate-[fadeInUp_150ms_ease-out] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-sm"
											role="menu"
											tabindex="-1"
											onclick={(e) => e.stopPropagation()}
											onkeydown={(e) => e.stopPropagation()}
										>
											<button
												onclick={() => handleRename(conv)}
												class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
												role="menuitem"
											>
												Rename
											</button>
											<button
												onclick={() => handleFavourite(conv)}
												class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
												role="menuitem"
											>
												{isFav ? 'Unfavourite' : 'Favourite'}
											</button>
											<button
												onclick={() => handleShare(conv)}
												class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
												role="menuitem"
											>
												Shared Link
											</button>
											<button
												onclick={() => handleExport(conv)}
												class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
												role="menuitem"
											>
												Export
											</button>
											<div class="my-1 border-t border-border-subtle"></div>
											<button
												onclick={() => handleDeletePrompt(conv)}
												class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-red-500 transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
												role="menuitem"
											>
												Delete
											</button>
										</div>
									{/if}
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Infinite scroll sentinel -->
			{#if hasMore}
				<div bind:this={scrollSentinelEl} class="flex justify-center py-4">
					{#if loadingMore}
						<div class="flex items-center gap-2 text-sm text-muted">
							<LoadingSpinner />
							Loading more...
						</div>
					{/if}
				</div>
			{/if}

			<!-- Result count -->
			{#if filteredConversations.length > 0}
				<div class="mt-2 pb-2 text-center text-[11px] text-muted">
					{#if activeFilter !== 'all'}
						Showing {filteredConversations.length} {activeFilter} conversations
					{:else}
						Showing {conversations.length} of {totalCount} conversations
					{/if}
				</div>
			{/if}
		{/if}
	{:else}
		<!-- Files tab -->
		{#if filesLoading}
			<!-- Loading skeleton -->
			<div class="space-y-6">
				<div>
					<Skeleton class="mb-3 rounded" width="120px" height="14px" />
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
						{#each [0, 1, 2, 3, 4, 5] as i (i)}
							<div class="rounded-xl border border-border-subtle bg-background p-3">
								<Skeleton class="mb-2 rounded-lg" width="100%" height="64px" stagger={i} />
								<Skeleton class="mb-1.5 rounded" width="80%" height="12px" stagger={i + 1} />
								<Skeleton class="rounded" width="50%" height="10px" stagger={i + 2} />
							</div>
						{/each}
					</div>
				</div>
			</div>
		{:else if files.length === 0}
			<!-- Empty state -->
			<EmptyState
				title="No files yet"
				description="Files uploaded to or generated by your AI agent will appear here."
				ctaLabel="Start a new chat"
				ctaHref="/"
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
							<path d="M15 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7z" />
							<path d="M14 2v4a2 2 0 002 2h4" />
							<line x1="16" x2="8" y1="13" y2="13" />
							<line x1="16" x2="8" y1="17" y2="17" />
							<line x1="10" x2="8" y1="9" y2="9" />
						</svg>
					</div>
				{/snippet}
			</EmptyState>
		{:else}
			<!-- File timeline grouped by day -->
			<div class="space-y-5">
				{#each fileGroups as group (group.label)}
					<div>
						<!-- Day header -->
						<div class="mb-3 flex items-center gap-3">
							<h3 class="text-sm font-medium tracking-wide text-muted uppercase">
								{group.label}
							</h3>
							<div class="h-px flex-1 bg-surface"></div>
							<span class="text-xs text-muted">{group.files.length} files</span>
						</div>

						<!-- File cards grid -->
						<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
							{#each group.files as file (file.id)}
								<div
									class="group relative flex flex-col overflow-hidden rounded-xl border border-border-subtle bg-background transition-all duration-300 hover:-translate-y-0.5 hover:border-border-strong hover:shadow-lg"
								>
									<!-- Thumbnail / Icon area -->
									<button
										onclick={() => handleFileClick(file)}
										class="flex h-20 w-full items-center justify-center bg-surface transition-colors group-hover:bg-surface-2 sm:h-24"
										use:tooltip={`Preview ${file.name}`}
									>
										{#if isImageFile(file.name)}
											<img
												src={file.file}
												alt={file.name}
												class="h-full w-full object-cover"
												loading="lazy"
											/>
										{:else}
											{@const category = getFileCategory(file.name)}
											<div class="flex flex-col items-center gap-1.5">
												{#if category === 'pdf'}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="28"
														height="28"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="1.5"
														stroke-linecap="round"
														stroke-linejoin="round"
														class="text-red-400"
													>
														<path
															d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"
														/>
														<polyline points="14 2 14 8 20 8" />
														<line x1="16" x2="8" y1="13" y2="13" />
														<line x1="16" x2="8" y1="17" y2="17" />
													</svg>
												{:else if category === 'video'}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="28"
														height="28"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="1.5"
														stroke-linecap="round"
														stroke-linejoin="round"
														class="text-purple-400"
													>
														<polygon points="23 7 16 12 23 17 23 7" />
														<rect width="15" height="14" x="1" y="5" rx="2" ry="2" />
													</svg>
												{:else if category === 'audio'}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="28"
														height="28"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="1.5"
														stroke-linecap="round"
														stroke-linejoin="round"
														class="text-green-400"
													>
														<path d="M9 18V5l12-2v13" />
														<circle cx="6" cy="18" r="3" />
														<circle cx="18" cy="16" r="3" />
													</svg>
												{:else if category === 'code'}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="28"
														height="28"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="1.5"
														stroke-linecap="round"
														stroke-linejoin="round"
														class="text-accent"
													>
														<polyline points="16 18 22 12 16 6" />
														<polyline points="8 6 2 12 8 18" />
													</svg>
												{:else if category === 'archive'}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="28"
														height="28"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="1.5"
														stroke-linecap="round"
														stroke-linejoin="round"
														class="text-yellow-500"
													>
														<path d="M21 8V5a2 2 0 00-2-2H5a2 2 0 00-2 2v3" />
														<path d="M21 16v3a2 2 0 01-2 2H5a2 2 0 01-2-2v-3" />
														<path d="M4 12h16" />
													</svg>
												{:else if category === 'document'}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="28"
														height="28"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="1.5"
														stroke-linecap="round"
														stroke-linejoin="round"
														class="text-muted"
													>
														<path d="M15 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7z" />
														<path d="M14 2v4a2 2 0 002 2h4" />
														<line x1="16" x2="8" y1="13" y2="13" />
														<line x1="16" x2="8" y1="17" y2="17" />
													</svg>
												{:else}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														width="28"
														height="28"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="1.5"
														stroke-linecap="round"
														stroke-linejoin="round"
														class="text-muted"
													>
														<path d="M15 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7z" />
														<path d="M14 2v4a2 2 0 002 2h4" />
													</svg>
												{/if}
												<span class="text-xs font-medium text-muted"
													>{getFileExtension(file.name)}</span
												>
											</div>
										{/if}
									</button>

									<!-- File info -->
									<div class="flex items-start justify-between gap-2 p-2.5">
										<button
											onclick={() => handleFileClick(file)}
											class="min-w-0 flex-1 text-left"
											title={file.name}
										>
											<p class="truncate text-sm font-medium text-foreground">{file.name}</p>
											<div class="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
												<span>{formatFileSize(file.size)}</span>
												<span class="text-muted">·</span>
												<span>{formatFileDate(file.uploaded_at)}</span>
											</div>
										</button>

										<!-- Download button -->
										<button
											onclick={() => handleFileDownload(file)}
											class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted opacity-0 transition-all group-hover:opacity-100 hover:bg-surface-2 hover:text-foreground"
											use:tooltip={`Download ${file.name}`}
											aria-label="Download {file.name}"
										>
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
											>
												<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
												<polyline points="7 10 12 15 17 10" />
												<line x1="12" x2="12" y1="15" y2="3" />
											</svg>
										</button>
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/each}
			</div>

			<!-- Infinite scroll sentinel -->
			{#if filesHasMore}
				<div bind:this={filesScrollSentinelEl} class="flex justify-center py-4">
					{#if filesLoadingMore}
						<div class="flex items-center gap-2 text-sm text-muted">
							<LoadingSpinner />
							Loading more...
						</div>
					{/if}
				</div>
			{/if}

			<!-- Result count -->
			{#if files.length > 0}
				<div class="mt-2 pb-2 text-center text-[11px] text-muted">
					Showing {files.length} of {filesTotalCount} files
				</div>
			{/if}
		{/if}
	{/if}
</div>

<!-- File preview dialog -->
<FilePreviewDialog bind:open={previewOpen} filename={previewFilename} fileUrl={previewFileUrl} />

<!-- Delete confirmation dialog -->
<ConfirmationDialog
	open={deleteConfirmId !== null}
	title="Delete conversation?"
	message={`\u201C${deleteConfirmTitle}\u201D will be permanently deleted. This action cannot be undone.`}
	confirmLabel="Delete"
	destructive
	onconfirm={confirmDelete}
	oncancel={() => (deleteConfirmId = null)}
/>

<ShareAccessDialog
	bind:open={shareDialogOpen}
	conversationId={shareDialogConversation?.id ?? ''}
	isShared={!!(shareDialogConversation?.metadata as Record<string, unknown>)?.shared}
	onsharedchange={handleSharedAccessChange}
/>
