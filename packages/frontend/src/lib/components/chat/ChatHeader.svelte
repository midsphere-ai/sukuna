<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		conversations,
		toggleFavourite,
		favouriteIds,
		isFavourite,
		renameConversationLocal,
		removeConversationLocal,
		setConversationSharedLocal
	} from '$stores/conversations';
	import { renameConversation, deleteConversation } from '$api/conversations';
	import { toasts } from '$stores/toast';
	import { removeBranchesForConversation } from '$stores/branches';
	import type { Conversation } from '$api/types';
	import { Skeleton, ConfirmationDialog } from '$components/ui';
	import ShareAccessDialog from '$components/chat/ShareAccessDialog.svelte';
	import ExportDialog from '$components/chat/ExportDialog.svelte';
	import type { Message } from '$services/sse';
	import { openMobileNav, sidebarHidden, toggleSidebar } from '$stores/sidebar';
	import { isTauri } from '$utils/platform';
	import { workspaceLayout, expandPane } from '$stores/workspaceLayout';
	import { isGalleryConversation, GALLERY_TITLE } from '$lib/data/galleryConversation';
	import {
		toolCalls as toolCallsStore,
		creditBurn as creditBurnStore,
		runStatus as runStatusStore
	} from '$services/sse';
	import { onDestroy } from 'svelte';
	import { tooltip } from '$lib/actions/tooltip';
	import { flagEnabled } from '$stores/featureFlags';
	import { debugPanelOpen, toggleDebugPanel } from '$stores/debugPanel';

	let isSidebarHidden = $state(false);
	const unsubSidebar = sidebarHidden.subscribe((v) => (isSidebarHidden = v));

	let editorCollapsed = $state(false);
	let hasToolCalls = $state(false);
	let currentCreditBurn = $state(0);
	let currentRunStatus = $state('idle');
	let debugFlag = $state(false);
	let debugOpen = $state(false);
	const debugFlagStore = flagEnabled('debug-mode');
	const unsubLayout = workspaceLayout.subscribe((v) => (editorCollapsed = v.editorCollapsed));
	const unsubToolCalls = toolCallsStore.subscribe((tc) => (hasToolCalls = tc.size > 0));
	const unsubCreditBurn = creditBurnStore.subscribe((v) => (currentCreditBurn = v));
	const unsubRunStatus = runStatusStore.subscribe((v) => (currentRunStatus = v));
	const unsubDebugFlag = debugFlagStore.subscribe((v) => (debugFlag = v));
	const unsubDebugOpen = debugPanelOpen.subscribe((v) => (debugOpen = v));
	let editorHidden = $derived(editorCollapsed || !hasToolCalls);

	type Props = {
		conversationId: string;
		messages: Message[];
	};

	let { conversationId, messages }: Props = $props();

	// Find conversation from store
	let allConversations: Conversation[] = $state([]);
	let favs = $state<Set<string>>(new Set());
	const unsubConversations = conversations.subscribe((v) => (allConversations = v));
	const unsubFavourites = favouriteIds.subscribe((v) => (favs = v));

	let isGallery = $derived(isGalleryConversation(conversationId));
	let conversation = $derived(allConversations.find((c) => c.id === conversationId));
	let title = $derived(isGallery ? GALLERY_TITLE : conversation?.title || 'Untitled');
	let isFav = $derived(isFavourite(conversationId, favs));

	// Editable title state
	let editing = $state(false);
	let editValue = $state('');
	let titleInputEl: HTMLInputElement | undefined = $state();

	function startEditing(): void {
		editValue = title;
		editing = true;
		requestAnimationFrame(() => {
			titleInputEl?.focus();
			titleInputEl?.select();
		});
	}

	async function submitRename(): Promise<void> {
		editing = false;
		const newTitle = editValue.trim();
		if (!newTitle || newTitle === title) return;

		renameConversationLocal(conversationId, newTitle);
		try {
			await renameConversation(conversationId, newTitle);
			toasts.success('Conversation renamed');
		} catch {
			toasts.error('Failed to rename conversation');
		}
	}

	function handleTitleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Enter') {
			e.preventDefault();
			submitRename();
		} else if (e.key === 'Escape') {
			editing = false;
		}
	}

	// Dropdown state
	let menuOpen = $state(false);
	let taskDetailsOpen = $state(false);
	let deleteConfirmOpen = $state(false);
	let shareDialogOpen = $state(false);
	let exportDialogOpen = $state(false);

	function closeAllDropdowns(): void {
		menuOpen = false;
	}

	function handleShareClick(): void {
		shareDialogOpen = true;
	}

	function handleSharedAccessChange(shared: boolean): void {
		setConversationSharedLocal(conversationId, shared);
	}

	function handleMenuRename(): void {
		menuOpen = false;
		startEditing();
	}

	function handleMenuFavourite(): void {
		const wasFav = isFav;
		toggleFavourite(conversationId);
		menuOpen = false;
		toasts.success(wasFav ? 'Removed from favourites' : 'Added to favourites');
	}

	function handleMenuTaskDetails(): void {
		menuOpen = false;
		taskDetailsOpen = true;
	}

	function handleMenuDelete(): void {
		menuOpen = false;
		deleteConfirmOpen = true;
	}

	async function confirmDelete(): Promise<void> {
		deleteConfirmOpen = false;
		removeConversationLocal(conversationId);
		removeBranchesForConversation(conversationId);
		try {
			await deleteConversation(conversationId);
			toasts.success('Conversation deleted');
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- navigating after delete
			goto('/');
		} catch {
			toasts.error('Failed to delete conversation');
		}
	}

	// Task details from conversation metadata
	let metadata = $derived((conversation?.metadata ?? {}) as Record<string, unknown>);
	let isShared = $derived(!!(conversation?.metadata as Record<string, unknown>)?.shared);
	let taskTokens = $derived((metadata.tokens as number) ?? 0);
	let taskAddons = $derived((metadata.addons as string[]) ?? []);
	let taskMcps = $derived((metadata.mcp as string[]) ?? []);
	let taskSandboxTime = $derived((metadata.sandbox_time as number) ?? 0);

	onDestroy(() => {
		unsubConversations();
		unsubFavourites();
		unsubSidebar();
		unsubLayout();
		unsubToolCalls();
		unsubCreditBurn();
		unsubRunStatus();
		unsubDebugFlag();
		unsubDebugOpen();
	});
</script>

<!-- Click outside handler -->
<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (!target.closest('[data-chat-header-dropdown]')) {
			closeAllDropdowns();
		}
	}}
/>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="flex h-[var(--header-height)] shrink-0 items-center justify-between border-b border-border-subtle px-2 sm:px-4"
	data-tauri-drag-region={isTauri() ? '' : undefined}
>
	<!-- Left: hamburger/sidebar toggle + title -->
	<div class="flex min-w-0 flex-1 items-center">
		<!-- Mobile hamburger -->
		<button
			onclick={openMobileNav}
			class="mr-0.5 flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground lg:hidden"
			aria-label="Open navigation"
			use:tooltip={'Open navigation'}
		>
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
			>
				<path d="M3 12h18" /><path d="M3 6h18" /><path d="M3 18h18" />
			</svg>
		</button>

		<!-- Editable title -->
		{#if !conversation && !isGallery && !editing}
			<div class="px-1.5 py-1">
				<Skeleton class="rounded" width="140px" height="16px" />
			</div>
		{:else if editing}
			<input
				bind:this={titleInputEl}
				bind:value={editValue}
				onblur={submitRename}
				onkeydown={handleTitleKeydown}
				class="w-full max-w-[260px] rounded-md border border-border-strong bg-background px-2 py-1 text-[14px] font-medium text-foreground outline-none transition-colors focus:border-accent"
				aria-label="Rename conversation"
			/>
		{:else}
			<button
				onclick={startEditing}
				class="min-w-0 max-w-[260px] truncate rounded-md px-1.5 py-1 text-[14px] font-medium text-foreground transition-colors hover:bg-surface-2"
				use:tooltip={{ text: 'Rename', position: 'bottom' }}
			>
				{title}
			</button>
		{/if}
	</div>

	<!-- Right: Presence + Export, Share, Menu + Window Controls -->
	<div class="flex shrink-0 items-center gap-0.5" data-chat-header-dropdown>
		<!-- Live credit burn -->
		{#if currentRunStatus === 'running' && currentCreditBurn > 0}
			<div
				class="mr-1 flex items-center gap-1 rounded-md bg-surface px-2 py-1 text-[14px] text-subtle"
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
					<circle cx="12" cy="12" r="8" />
					<path d="M14.5 9a3.5 3.5 0 00-5 0" />
					<path d="M12 12v4" />
					<path d="M12 8v.01" />
				</svg>
				<span class="tabular-nums">~{currentCreditBurn.toLocaleString()} credits</span>
			</div>
		{/if}

		<!-- Open canvas (when collapsed) -->
		{#if editorCollapsed && hasToolCalls}
			<button
				onclick={() => expandPane('editor')}
				class="hidden items-center justify-center rounded-md p-1 text-foreground transition-colors hover:bg-surface-2 hover:text-accent lg:flex"
				use:tooltip={{ text: 'Open canvas', position: 'bottom' }}
				aria-label="Open canvas"
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
					<rect width="18" height="18" x="3" y="3" rx="2" />
					<path d="M9 3v18" />
				</svg>
			</button>
		{/if}
		<!-- Debug panel toggle (gated on debug-mode feature flag) -->
		{#if debugFlag}
			<button
				onclick={toggleDebugPanel}
				class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg transition-colors lg:min-h-0 lg:min-w-0 lg:p-1.5 {debugOpen
					? 'bg-surface-2 text-accent'
					: 'text-muted hover:bg-surface-2 hover:text-foreground'}"
				use:tooltip={{
					text: debugOpen ? 'Close debug panel' : 'Open debug panel',
					position: 'bottom'
				}}
				aria-label={debugOpen ? 'Close debug panel' : 'Open debug panel'}
				aria-pressed={debugOpen}
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
					<path d="M8 2v4" />
					<path d="M16 2v4" />
					<path d="M12 20v-8" />
					<path d="M8 20v-4" />
					<path d="M16 20v-4" />
					<rect width="20" height="14" x="2" y="6" rx="2" />
				</svg>
			</button>
		{/if}

		<!-- Export (download) -->
		<button
			onclick={() => {
				exportDialogOpen = true;
			}}
			class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground lg:min-h-0 lg:min-w-0 lg:p-1.5"
			use:tooltip={{ text: 'Export', position: 'bottom' }}
			aria-label="Export conversation"
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
				<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
				<polyline points="7 10 12 15 17 10" />
				<line x1="12" x2="12" y1="15" y2="3" />
			</svg>
		</button>

		<!-- Share -->
		<button
			onclick={handleShareClick}
			class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg transition-colors lg:min-h-0 lg:min-w-0 lg:p-1.5 {isShared
				? 'text-accent'
				: 'text-muted hover:bg-surface-2 hover:text-foreground'}"
			use:tooltip={{ text: isShared ? 'Shared' : 'Share', position: 'bottom' }}
			aria-label={isShared ? 'Unshare conversation' : 'Share conversation'}
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
				<circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle
					cx="18"
					cy="19"
					r="3"
				/>
				<line x1="8.59" x2="15.42" y1="13.51" y2="17.49" /><line
					x1="15.41"
					x2="8.59"
					y1="6.51"
					y2="10.49"
				/>
			</svg>
		</button>

		<!-- More menu -->
		<div class="relative">
			<button
				onclick={() => {
					menuOpen = !menuOpen;
				}}
				class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg transition-colors lg:min-h-0 lg:min-w-0 lg:p-1.5 {menuOpen
					? 'bg-surface-2 text-foreground'
					: 'text-muted hover:bg-surface-2 hover:text-foreground'}"
				use:tooltip={{ text: 'More options', position: 'bottom' }}
				aria-label="More options"
				aria-expanded={menuOpen}
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
					<circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /><circle
						cx="5"
						cy="12"
						r="1"
					/>
				</svg>
			</button>

			{#if menuOpen}
				<div
					class="absolute top-full right-0 z-50 mt-1 w-48 animate-[dropdownIn_0.15s_ease-out] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-xl"
					role="menu"
				>
					<button
						onclick={handleMenuRename}
						class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[14px] text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
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
							><path d="M17 3a2.85 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5Z" /><path
								d="m15 5 4 4"
							/></svg
						>
						Rename
					</button>
					<button
						onclick={handleMenuFavourite}
						class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[14px] text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
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
								><polygon
									points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
								/></svg
							>
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
								><polygon
									points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
								/></svg
							>
							Favourite
						{/if}
					</button>
					<button
						onclick={handleMenuTaskDetails}
						class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[14px] text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
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
							><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg
						>
						Task details
					</button>
					<div class="my-0.5 border-t border-border-subtle"></div>
					<button
						onclick={handleMenuDelete}
						class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[14px] text-red-500 transition-colors hover:bg-red-50 hover:text-red-600"
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
							><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path
								d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"
							/><line x1="10" x2="10" y1="11" y2="17" /><line
								x1="14"
								x2="14"
								y1="11"
								y2="17"
							/></svg
						>
						Delete
					</button>
				</div>
			{/if}
		</div>
	</div>
</div>

<!-- Task details dialog -->
{#if taskDetailsOpen}
	<div
		class="fixed inset-0 z-[10000] flex items-center justify-center bg-foreground/40"
		onclick={() => (taskDetailsOpen = false)}
		onkeydown={(e) => e.key === 'Escape' && (taskDetailsOpen = false)}
		role="presentation"
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="mx-4 w-full max-w-sm rounded-xl border border-border-subtle bg-surface p-5 shadow-xl"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<h3 class="text-[15px] font-medium text-foreground">Task Details</h3>
			<div class="mt-3.5 space-y-2.5">
				<div class="flex items-center justify-between">
					<span class="text-[14px] text-subtle">Tokens used</span>
					<span class="text-[14px] font-medium text-foreground">{taskTokens.toLocaleString()}</span>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-[14px] text-subtle">Addons</span>
					<span class="text-[14px] font-medium text-foreground"
						>{taskAddons.length > 0 ? taskAddons.join(', ') : 'None'}</span
					>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-[14px] text-subtle">MCP servers</span>
					<span class="text-[14px] font-medium text-foreground"
						>{taskMcps.length > 0 ? taskMcps.join(', ') : 'None'}</span
					>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-[14px] text-subtle">Sandbox time</span>
					<span class="text-[14px] font-medium text-foreground">
						{#if taskSandboxTime > 0}
							{Math.round(taskSandboxTime / 60)}m {taskSandboxTime % 60}s
						{:else}
							N/A
						{/if}
					</span>
				</div>
				<div class="flex items-center justify-between">
					<span class="text-[14px] text-subtle">Credits consumed</span>
					<span class="text-[14px] font-medium text-foreground">
						{#if currentCreditBurn > 0}
							~{currentCreditBurn.toLocaleString()}
						{:else}
							--
						{/if}
					</span>
				</div>
			</div>
			<div class="mt-4 flex justify-end">
				<button
					onclick={() => (taskDetailsOpen = false)}
					class="rounded-lg border border-border px-3.5 py-1.5 text-[14px] font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
				>
					Close
				</button>
			</div>
		</div>
	</div>
{/if}

<ConfirmationDialog
	open={deleteConfirmOpen}
	title="Delete conversation?"
	message="This action cannot be undone. The conversation and all its messages will be permanently deleted."
	confirmLabel="Delete"
	destructive
	onconfirm={confirmDelete}
	oncancel={() => (deleteConfirmOpen = false)}
/>

<ShareAccessDialog
	bind:open={shareDialogOpen}
	{conversationId}
	{isShared}
	onsharedchange={handleSharedAccessChange}
/>

<ExportDialog
	bind:open={exportDialogOpen}
	{title}
	{messages}
	dateCreated={conversation?.date_created}
/>
