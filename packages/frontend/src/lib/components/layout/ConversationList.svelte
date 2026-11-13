<script lang="ts">
	import { Skeleton, ConfirmationDialog } from '$components/ui';
	import ContextMenu from '$components/ui/ContextMenu.svelte';
	import { get } from 'svelte/store';
	import {
		groupedConversations,
		conversationsLoading,
		conversationsError,
		conversationsHasMore,
		activeConversationId,
		conversationFilter,
		favouriteIds,
		fetchConversations,
		loadMoreConversations,
		toggleFavourite,
		isFavourite,
		renameConversationLocal,
		removeConversationLocal,
		setConversationSharedLocal
	} from '$stores/conversations';
	import type { ConversationGroup } from '$stores/conversations';
	import type { Conversation } from '$api/types';
	import { deleteConversation, renameConversation } from '$api/conversations';
	import { toasts } from '$stores/toast';
	import { branchMap, branchParents, removeBranchesForConversation } from '$stores/branches';
	import { pullToRefresh, haptic } from '$lib/actions/gestures';
	import ShareAccessDialog from '$components/chat/ShareAccessDialog.svelte';
	import { flagEnabled } from '$stores/featureFlags';

	interface Props {
		compact?: boolean;
	}

	let { compact = false }: Props = $props();

	const compactFlag = flagEnabled('compact-sidebar');
	let ultraCompact = $state(false);
	const unsubCompact = compactFlag.subscribe((v) => {
		ultraCompact = v;
	});

	const textSize = $derived(ultraCompact ? 'text-[12px]' : compact ? 'text-[13px]' : 'text-[15px]');
	const itemPadding = $derived(
		ultraCompact ? 'pl-2.5 pr-2.5 py-[3px]' : compact ? 'pl-2.5 pr-2.5 py-[6px]' : 'px-2.5 py-1.5'
	);
	const inactiveColor = $derived(
		compact
			? 'text-foreground hover:bg-surface-2 hover:text-accent'
			: 'text-foreground hover:bg-surface hover:text-accent'
	);

	let groups: ConversationGroup[] = $state([]);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let hasMore = $state(true);
	let activeId = $state<string | null>(null);
	let filter = $state('all');
	let favs = $state<Set<string>>(new Set());
	let branchParentMap = $state<
		Record<string, { parentConversationId: string; fromMessageIndex: number }>
	>({});
	let branchChildMap = $state<
		Record<string, { branchConversationId: string; fromMessageIndex: number; createdAt: string }[]>
	>({});

	groupedConversations.subscribe((v) => (groups = v));
	conversationsLoading.subscribe((v) => (loading = v));
	conversationsError.subscribe((v) => (error = v));
	conversationsHasMore.subscribe((v) => (hasMore = v));
	activeConversationId.subscribe((v) => (activeId = v));
	conversationFilter.subscribe((v) => (filter = v));
	favouriteIds.subscribe((v) => (favs = v));
	branchParents.subscribe((v) => (branchParentMap = v));
	branchMap.subscribe((v) => (branchChildMap = v));

	let listContainer: HTMLDivElement | undefined = $state();
	// Show initial skeleton only when store is completely empty (no cache)
	let initialLoad = $state(get(groupedConversations).length === 0);

	// Rename state
	let renamingId = $state<string | null>(null);
	let renameValue = $state('');

	// Swipe-to-delete state
	let swipingId = $state<string | null>(null);
	let swipeOffset = $state(0);
	let swipeTouchStartX = $state(0);
	let swipeTouchStartY = $state(0);
	let swipeConfirmId = $state<string | null>(null);
	let shareDialogOpen = $state(false);
	let shareDialogConversationId = $state('');
	let shareDialogShared = $state(false);

	const SWIPE_THRESHOLD = 80;

	// Clear initialLoad when groups arrive (from cache or fetch)
	$effect(() => {
		if (groups.length > 0) {
			initialLoad = false;
		}
	});

	function handleScroll(): void {
		if (!listContainer || loading || !hasMore) return;
		const { scrollTop, scrollHeight, clientHeight } = listContainer;
		if (scrollHeight - scrollTop - clientHeight < 100) {
			loadMoreConversations();
		}
	}

	function truncateTitle(title: string, maxLength = 30): string {
		if (title.length <= maxLength) return title;
		return title.slice(0, maxLength) + '...';
	}

	// Context menu actions
	function startRename(convId: string, currentTitle: string): void {
		renamingId = convId;
		renameValue = currentTitle || '';
	}

	async function submitRename(): Promise<void> {
		if (!renamingId || !renameValue.trim()) {
			renamingId = null;
			return;
		}
		const id = renamingId;
		const title = renameValue.trim();
		renamingId = null;

		renameConversationLocal(id, title);
		try {
			await renameConversation(id, title);
		} catch {
			toasts.error('Failed to rename conversation');
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

	async function handleDelete(convId: string): Promise<void> {
		removeConversationLocal(convId);
		removeBranchesForConversation(convId);
		try {
			await deleteConversation(convId);
			toasts.success('Conversation deleted');
		} catch {
			toasts.error('Failed to delete conversation');
			fetchConversations();
		}
	}

	function handleShare(conv: Conversation): void {
		shareDialogConversationId = conv.id;
		shareDialogShared = !!(conv.metadata as Record<string, unknown>)?.shared;
		shareDialogOpen = true;
	}

	function handleSharedAccessChange(shared: boolean): void {
		if (!shareDialogConversationId) return;
		shareDialogShared = shared;
		setConversationSharedLocal(shareDialogConversationId, shared);
	}

	function getMenuItems(conv: Conversation) {
		return [
			{
				label: 'Rename',
				icon: '✏️',
				action: () => startRename(conv.id, conv.title)
			},
			{
				label: isFavourite(conv.id, favs) ? 'Unfavourite' : 'Favourite',
				icon: isFavourite(conv.id, favs) ? '💛' : '⭐',
				action: () => toggleFavourite(conv.id)
			},
			{
				label: 'Share',
				icon: '🔗',
				action: () => handleShare(conv)
			},
			{
				label: 'Delete',
				icon: '🗑️',
				danger: true,
				action: () => {
					swipeConfirmId = conv.id;
				}
			}
		];
	}

	// Swipe gesture handlers for mobile
	function handleSwipeTouchStart(e: TouchEvent, convId: string): void {
		swipeTouchStartX = e.touches[0].clientX;
		swipeTouchStartY = e.touches[0].clientY;
		swipingId = convId;
		swipeOffset = 0;
	}

	function handleSwipeTouchMove(e: TouchEvent): void {
		if (!swipingId) return;
		const dx = e.touches[0].clientX - swipeTouchStartX;
		const dy = e.touches[0].clientY - swipeTouchStartY;

		// Only activate swipe if horizontal movement is dominant
		if (Math.abs(dy) > Math.abs(dx)) {
			swipingId = null;
			swipeOffset = 0;
			return;
		}

		// Only allow left swipe (negative)
		swipeOffset = Math.min(0, dx);
	}

	function handleSwipeTouchEnd(): void {
		if (!swipingId) return;
		if (Math.abs(swipeOffset) >= SWIPE_THRESHOLD) {
			haptic(15);
			swipeConfirmId = swipingId;
		}
		swipingId = null;
		swipeOffset = 0;
	}

	function confirmDelete(): void {
		if (swipeConfirmId) {
			handleDelete(swipeConfirmId);
			swipeConfirmId = null;
		}
	}

	function cancelDelete(): void {
		swipeConfirmId = null;
	}
</script>

<div
	class="flex flex-1 flex-col overflow-y-auto scrollbar-thin"
	bind:this={listContainer}
	onscroll={handleScroll}
	aria-label="Conversations"
	use:pullToRefresh={{ onRefresh: () => fetchConversations() }}
>
	{#if initialLoad && loading}
		<!-- Loading skeleton -->
		<div class="space-y-1 px-1 pt-1">
			{#each [0, 1, 2, 3, 4] as i (i)}
				<div class="rounded-lg px-2.5 py-1.5">
					<Skeleton variant="text" width={i % 2 === 0 ? '75%' : '60%'} height="15px" />
				</div>
			{/each}
		</div>
	{:else if error && groups.length === 0}
		<div class="px-3 py-6 text-center">
			<p class="text-[15px] text-muted">Failed to load conversations</p>
			<button
				onclick={() => fetchConversations()}
				class="mt-2 text-xs font-medium text-accent transition-colors hover:text-accent/80"
			>
				Try again
			</button>
		</div>
	{:else if groups.length === 0}
		<div class="flex flex-col items-center gap-2 px-3 py-8 text-center">
			<div class="flex h-9 w-9 items-center justify-center rounded-lg bg-surface text-muted">
				{#if filter === 'favourites'}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						><polygon
							points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
						/></svg
					>
				{:else if filter === 'scheduled'}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg
					>
				{:else if filter === 'shared'}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle
							cx="18"
							cy="19"
							r="3"
						/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49" /><line
							x1="15.41"
							y1="6.51"
							x2="8.59"
							y2="10.49"
						/></svg
					>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg
					>
				{/if}
			</div>
			<p class="{textSize} text-muted">
				{#if filter === 'favourites'}
					No favourite conversations
				{:else if filter === 'scheduled'}
					No scheduled conversations
				{:else if filter === 'shared'}
					No shared conversations
				{:else}
					No conversations yet
				{/if}
			</p>
			{#if filter === 'all'}
				<p class="text-[11px] text-muted">Start a new task to begin</p>
			{/if}
		</div>
	{:else}
		<!-- eslint-disable svelte/no-navigation-without-resolve -- conversation links are dynamic internal navigation -->
		{#each groups as group (group.label)}
			<div
				class={ultraCompact ? 'mb-0' : 'mb-0.5'}
				role="group"
				aria-label="{group.label} conversations"
			>
				{#if !compact && !ultraCompact}
					<p class="px-2.5 py-1.5 text-[11px] font-medium uppercase tracking-wider text-muted">
						{group.label}
					</p>
				{/if}
				{#each group.conversations as conv (conv.id)}
					{@const isActive = activeId === conv.id}
					{@const isSwiping = swipingId === conv.id}
					<ContextMenu items={getMenuItems(conv)}>
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class="relative overflow-hidden"
							ontouchstart={(e) => handleSwipeTouchStart(e, conv.id)}
							ontouchmove={handleSwipeTouchMove}
							ontouchend={handleSwipeTouchEnd}
						>
							<!-- Delete action revealed on swipe -->
							{#if isSwiping && swipeOffset < -20}
								<div
									class="absolute inset-y-0 right-0 flex items-center bg-error px-4 {textSize} font-medium text-white"
								>
									Delete
								</div>
							{/if}

							{#if renamingId === conv.id}
								<div class={itemPadding}>
									<input
										type="text"
										bind:value={renameValue}
										onblur={submitRename}
										onkeydown={handleRenameKeydown}
										class="w-full rounded-md border border-accent/40 bg-surface px-2 py-1 {textSize} text-foreground outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
										aria-label="Rename conversation"
									/>
								</div>
							{:else}
								<a
									href="/chat/{conv.id}"
									class="group relative flex items-center gap-2 rounded-lg {itemPadding} {textSize} transition-colors duration-100
										{isActive ? 'bg-surface-2 text-foreground font-medium' : inactiveColor}"
									style={isSwiping ? `transform: translateX(${swipeOffset}px)` : ''}
									aria-current={isActive ? 'page' : undefined}
								>
									{#if conv.status === 'running' || conv.status === 'queued' || conv.status === 'provisioning'}
										<span
											class="absolute left-0.5 top-1/2 -translate-y-1/2 h-[5px] w-[5px] rounded-full bg-accent animate-pulse"
											aria-label="Task {conv.status}"
										></span>
									{/if}
									<span
										class="flex min-w-0 flex-1 items-center gap-1 overflow-hidden whitespace-nowrap leading-tight text-fade"
									>
										{conv.title || 'Untitled'}
										{#if isFavourite(conv.id, favs)}
											<span class="text-[10px]" aria-label="Favourite">⭐</span>
										{/if}
										{#if branchParentMap[conv.id]}
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
												class="shrink-0 text-accent/40"
												aria-label="Branch"
												><circle cx="12" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><circle
													cx="18"
													cy="6"
													r="3"
												/><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9" /><path
													d="M12 12v3"
												/></svg
											>
										{:else if branchChildMap[conv.id]?.length}
											<span
												class="text-[9px] font-medium text-accent/40"
												aria-label="{branchChildMap[conv.id].length} branches"
												>{branchChildMap[conv.id].length}b</span
											>
										{/if}
									</span>
								</a>
							{/if}
						</div>
					</ContextMenu>
				{/each}
			</div>
		{/each}
		<!-- eslint-enable svelte/no-navigation-without-resolve -->

		{#if loading && !initialLoad}
			<div class="space-y-1 px-1 pt-1">
				{#each [0, 1, 2] as i (i)}
					<div class="rounded-lg px-2.5 py-1.5">
						<Skeleton variant="text" width={i % 2 === 0 ? '70%' : '55%'} height="15px" />
					</div>
				{/each}
			</div>
		{/if}

		{#if !hasMore && groups.length > 0}
			<p class="py-3 text-center text-[10px] text-muted">No more conversations</p>
		{/if}
	{/if}
</div>

<!-- Delete confirmation dialog -->
<ConfirmationDialog
	open={swipeConfirmId !== null}
	title="Delete conversation?"
	message="This action cannot be undone. The conversation and all its messages will be permanently deleted."
	confirmLabel="Delete"
	destructive
	onconfirm={confirmDelete}
	oncancel={cancelDelete}
/>

<ShareAccessDialog
	bind:open={shareDialogOpen}
	conversationId={shareDialogConversationId}
	isShared={shareDialogShared}
	onsharedchange={handleSharedAccessChange}
/>

<style>
	.text-fade {
		mask-image: linear-gradient(to right, black calc(100% - 24px), transparent);
		-webkit-mask-image: linear-gradient(to right, black calc(100% - 24px), transparent);
	}
</style>
