<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';

	import Sidebar from '$components/layout/Sidebar.svelte';
	import TauriWindowControls from '$components/layout/TauriWindowControls.svelte';
	import { isTauri } from '$utils/platform';
	import { initTauriWindow, destroyTauriWindow } from '$stores/tauri';
	import MobileNavDrawer from '$components/layout/MobileNavDrawer.svelte';
	import ComputerPanelMobile from '$components/chat/ComputerPanelMobile.svelte';
	import ChatHeader from '$components/chat/ChatHeader.svelte';
	import WorkspaceLayout from '$components/chat/WorkspaceLayout.svelte';
	import CodeEditorPanel from '$components/chat/CodeEditorPanel.svelte';
	import ShortcutsCheatsheet from '$components/layout/ShortcutsCheatsheet.svelte';
	import SearchDialog from '$components/layout/SearchDialog.svelte';
	import SettingsDialog from '$components/settings/SettingsDialog.svelte';
	import MFAChallenge from '$components/auth/MFAChallenge.svelte';
	import { openMobileNav } from '$stores/sidebar';
	import { toolCalls as toolCallsStore, messages as messagesStore } from '$services/sse';
	import type { ToolCallMessage, Message } from '$services/sse';
	import { handleGlobalKeydown } from '$stores/shortcuts';
	import { searchOpen } from '$stores/search';
	import { authToken, currentUser } from '$stores/auth';
	import {
		pageTitle,
		showHeaderTitle,
		headerSearchConfig,
		headerSearchValue,
		headerFilterConfig,
		headerHidden
	} from '$stores/page';
	import { Search, SlidersHorizontal } from '@lucide/svelte';
	import { initAuth } from '$api/auth';
	import { getHomeBanner } from '$api/cms';
	import { loadInfoTutorials } from '$stores/infoTutorials';
	import { startNotificationPolling, stopNotificationPolling } from '$services/notificationStream';
	import { browser } from '$app/environment';
	import { fetchConversations } from '$stores/conversations';
	import {
		connect as connectConversationStream,
		disconnect as disconnectConversationStream
	} from '$services/conversationStream';
	import { get } from 'svelte/store';
	import type { User } from '$api/types';

	let isOnChatPage = $derived(page.url.pathname.startsWith('/chat/'));
	let isOnClawChatPage = $derived(/^\/claw\/[^/]+/.test(page.url.pathname));

	// Chat page state — subscribe lazily only when on chat page to avoid
	// re-rendering the entire layout on every SSE text chunk.
	let chatConversationId = $derived(page.params.id ?? '');
	let toolCallsMap: Map<string, ToolCallMessage> = $state(new Map());
	let currentToolCalls: ToolCallMessage[] = $derived(Array.from(toolCallsMap.values()));
	let currentMessages: Message[] = $state([]);

	$effect(() => {
		if (!isOnChatPage) return;
		const unsub1 = toolCallsStore.subscribe((map) => {
			toolCallsMap = map;
		});
		const unsub2 = messagesStore.subscribe((msgs) => {
			currentMessages = msgs;
		});
		return () => {
			unsub1();
			unsub2();
			toolCallsMap = new Map();
			currentMessages = [];
		};
	});

	let { children } = $props();
	let ready = $state(false);

	const SEEN_ANNOUNCEMENT_KEY = 'midsphere-last-seen-announcement';

	function hasCompletedOnboarding(user: User | null): boolean {
		if (!user) return false;
		if (typeof user.onboarding_completed === 'boolean') {
			return user.onboarding_completed;
		}
		return Boolean(user.name) && user.last_login !== null;
	}

	async function checkForAnnouncements(): Promise<void> {
		try {
			const banner = await getHomeBanner();
			if (banner?.announcement && browser) {
				const lastSeen = localStorage.getItem(SEEN_ANNOUNCEMENT_KEY);
				if (lastSeen !== banner.announcement.id) {
					localStorage.setItem(SEEN_ANNOUNCEMENT_KEY, banner.announcement.id);
				}
			}
		} catch {
			// CMS unavailable — silently skip
		}
	}

	onMount(() => {
		initTauriWindow();

		const token = get(authToken);

		if (!token) {
			// Preserve current URL (including query params like ?prompt=) so login can redirect back
			const returnTo = page.url.pathname + page.url.search;
			const loginUrl =
				returnTo && returnTo !== '/' ? `/login?next=${encodeURIComponent(returnTo)}` : '/login';
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto(loginUrl);
			return;
		}

		void (async () => {
			try {
				await initAuth();
			} catch {
				// Token is invalid - redirect to login, preserving return URL
				ready = false;
				const returnTo = page.url.pathname + page.url.search;
				const loginUrl =
					returnTo && returnTo !== '/' ? `/login?next=${encodeURIComponent(returnTo)}` : '/login';
				// eslint-disable-next-line svelte/no-navigation-without-resolve
				goto(loginUrl);
				return;
			}

			if (!hasCompletedOnboarding(get(currentUser))) {
				ready = false;
				// eslint-disable-next-line svelte/no-navigation-without-resolve
				goto('/onboarding');
				return;
			}

			ready = true;
			fetchConversations();
			connectConversationStream();
			startNotificationPolling();
			checkForAnnouncements();
			loadInfoTutorials();
		})();
	});

	onDestroy(() => {
		disconnectConversationStream();
		stopNotificationPolling();
		destroyTauriWindow();
	});
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

{#if ready && $currentUser?.mfa_pending}
	<MFAChallenge />
{:else if ready}
	<a href="#main-content" class="skip-to-content">Skip to content</a>
	<div class="flex h-dvh overflow-hidden bg-background">
		<Sidebar />

		<!-- Main content area -->
		<div class="flex min-w-0 flex-1 flex-col">
			<!-- Tauri titlebar: drag region + window controls (desktop only) -->
			{#if isTauri()}
				<div
					data-tauri-drag-region
					class="hidden h-[var(--header-height)] shrink-0 items-center justify-end border-b border-border-subtle lg:flex"
				>
					<TauriWindowControls />
				</div>
			{/if}

			{#if isOnChatPage}
				<!-- Chat pages: split layout with per-pane headers -->
				<div class="min-h-0 flex-1 overflow-hidden">
					<WorkspaceLayout>
						{#snippet editor()}
							<CodeEditorPanel toolCalls={currentToolCalls} conversationId={chatConversationId} />
						{/snippet}
						{#snippet chat()}
							<ChatHeader conversationId={chatConversationId} messages={currentMessages} />
							<main
								id="main-content"
								class="chat-main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
							>
								{@render children()}
							</main>
						{/snippet}
					</WorkspaceLayout>
				</div>
			{:else}
				<!-- Non-chat pages: mobile header + desktop quick-actions row.
				     Desktop: terminal / notifications / avatar in the top-right.
				     Header hides when a page sets `headerHidden`, but <main>
				     stays mounted so page state survives. -->
				{#if !$headerHidden}
					<header
						class="flex h-[var(--header-height)] shrink-0 items-center justify-between px-2 lg:px-5"
					>
						<!-- Mobile hamburger (hidden on desktop) -->
						<button
							onclick={openMobileNav}
							class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-foreground lg:hidden"
							aria-label="Open menu"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="20"
								height="20"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
								aria-hidden="true"
							>
								<path d="M3 12h18" /><path d="M3 6h18" /><path d="M3 18h18" />
							</svg>
						</button>

						<!-- Page title (desktop). Set by each page via `pageTitle` store. -->
						{#if $showHeaderTitle}
							<h1
								class="hidden text-[18px] font-medium tracking-[-0.01em] text-foreground lg:block lg:pl-2"
							>
								{$pageTitle}
							</h1>
						{/if}

						<!-- Spacer so desktop quick-actions float to the right -->
						<div class="hidden flex-1 lg:block"></div>

						<!-- Page-scoped search + filter. Rendered when the current page
					     sets `headerSearchConfig` / `headerFilterConfig`. -->
						<div class="hidden items-center gap-2 lg:flex">
							{#if $headerSearchConfig}
								<div class="relative">
									<Search
										class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-subtle"
										strokeWidth={1.5}
									/>
									<input
										id={$headerSearchConfig.inputId ?? 'global-header-search'}
										type="text"
										bind:value={$headerSearchValue}
										placeholder={$headerSearchConfig.placeholder}
										class="h-8 w-[240px] rounded-[6px] border border-border bg-surface pl-10 {$headerSearchConfig.shortcut
											? 'pr-12'
											: 'pr-3'} text-[13px] text-foreground placeholder:text-subtle focus:border-accent focus:outline-none"
									/>
									{#if $headerSearchConfig.shortcut}
										<kbd
											class="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-subtle"
										>
											{$headerSearchConfig.shortcut}
										</kbd>
									{/if}
								</div>
							{/if}
							{#if $headerFilterConfig}
								<button
									type="button"
									onclick={$headerFilterConfig.onClick}
									class="flex h-8 items-center gap-1.5 rounded-[6px] border border-border bg-surface px-3 text-[13px] text-foreground transition-colors hover:bg-surface-2"
								>
									<span>{$headerFilterConfig.label ?? 'Filter'}</span>
									<SlidersHorizontal class="h-3.5 w-3.5 text-subtle" strokeWidth={1.5} />
								</button>
							{/if}
						</div>

						<div class="flex items-center gap-1">
							<!-- Terminal / command palette trigger -->
							<button
								onclick={() => ($searchOpen = true)}
								class="flex h-8 w-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface hover:text-foreground"
								aria-label="Open command palette"
								title="Command palette (⌘K)"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="18"
									height="18"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									stroke-linecap="round"
									stroke-linejoin="round"
									aria-hidden="true"
								>
									<polyline points="4 17 10 11 4 5" />
									<line x1="12" x2="20" y1="19" y2="19" />
								</svg>
							</button>

							<!-- Notifications -->
							<button
								class="flex h-8 w-8 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface hover:text-foreground"
								aria-label="Notifications"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="18"
									height="18"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									stroke-linecap="round"
									stroke-linejoin="round"
									aria-hidden="true"
								>
									<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
									<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
								</svg>
							</button>

							<!-- Avatar (mobile: "new task" pencil for legacy affordance) -->
							<div class="hidden lg:block">
								{#if $currentUser}
									<div
										class="flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border border-border bg-surface"
									>
										{#if $currentUser.avatar}
											<img
												src={$currentUser.avatar}
												alt={$currentUser.name ?? 'Account'}
												class="h-full w-full object-cover"
											/>
										{:else}
											<span class="text-[12px] font-medium text-foreground">
												{($currentUser.name ?? 'A').slice(0, 1).toUpperCase()}
											</span>
										{/if}
									</div>
								{/if}
							</div>
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a
								href="/"
								class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-foreground lg:hidden"
								aria-label="New task"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="20"
									height="20"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									stroke-linecap="round"
									stroke-linejoin="round"
									aria-hidden="true"
								>
									<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
									<path
										d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"
									/>
								</svg>
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						</div>
					</header>
				{/if}

				<main
					id="main-content"
					class="page-enter flex-1 {isOnClawChatPage
						? 'overflow-hidden flex flex-col'
						: 'overflow-y-auto'}"
				>
					{@render children()}
				</main>
			{/if}
		</div>

		<!-- Right-edge drawer slot. Pages that want a true right-sidebar
		     (e.g. /tasks task-detail drawer) portal their markup into this
		     node. `display: contents` flattens it so the portaled element
		     becomes a direct flex child of the outer row — sibling to the
		     <Sidebar> on the left and the middle column. -->
		<div id="app-right-slot" style="display: contents;"></div>
	</div>

	<!-- Mobile navigation drawer (available on all pages) -->
	<MobileNavDrawer />

	<!-- Mobile canvas drawer (bottom sheet for tool call results) -->
	{#if isOnChatPage}
		<div class="lg:hidden">
			<ComputerPanelMobile toolCalls={currentToolCalls} />
		</div>
	{/if}

	<ShortcutsCheatsheet />
	<SearchDialog bind:open={$searchOpen} />
	<SettingsDialog />
{:else}
	<!-- Loading state while validating auth -->
	<div class="flex h-dvh items-center justify-center bg-background">
		<div class="flex flex-col items-center gap-3">
			<svg
				class="h-6 w-6 animate-spin text-muted"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				aria-hidden="true"
			>
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
				></circle>
				<path
					class="opacity-75"
					fill="currentColor"
					d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
				></path>
			</svg>
		</div>
	</div>
{/if}
