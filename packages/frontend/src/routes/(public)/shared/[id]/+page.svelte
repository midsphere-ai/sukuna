<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/state';
	import ChatMessageList from '$components/chat/ChatMessageList.svelte';
	import FilePreviewDialog from '$components/chat/FilePreviewDialog.svelte';
	import {
		resetStores,
		replayEventsPage,
		prependOlderEvents,
		eventsHasMore,
		getOldestLoadedCursor,
		messages as messagesStore,
		runStatus as runStatusStore,
		connectToSharedRun,
		disconnect
	} from '$services/sse';
	import {
		getSharedConversationStatus,
		getSharedConversation,
		getSharedRunEvents
	} from '$api/chat';
	import type { Message, RunStatus } from '$services/sse';
	import type { SharedConversationInfo } from '$api/chat';
	import { Skeleton } from '$components/ui';

	let conversationId = $derived(page.params.id ?? '');

	let currentMessages: Message[] = $state([]);
	let currentStatus: RunStatus = $state('idle');
	let loading = $state(true);
	let error = $state('');
	let conversationInfo = $state<SharedConversationInfo | null>(null);

	// File preview state
	let previewOpen = $state(false);
	let previewFilename = $state('');
	let previewFileUrl = $state('');

	function handleFileClick(filename: string): void {
		previewFilename = filename;
		previewFileUrl = '';
		previewOpen = true;
	}

	// Subscribe to SSE stores
	const unsubMessages = messagesStore.subscribe((msgs) => {
		currentMessages = msgs;
	});
	const unsubStatus = runStatusStore.subscribe((s) => {
		currentStatus = s;
	});

	// Pagination state
	let hasMoreMessages = $state(false);
	const unsubHasMore = eventsHasMore.subscribe((v) => {
		hasMoreMessages = v;
	});

	async function handleLoadMore(): Promise<void> {
		if (!conversationId) return;
		const cursor = getOldestLoadedCursor();
		const result = await getSharedRunEvents(conversationId, {
			cursor,
			limit: 50000
		});
		prependOlderEvents(result.events, result.has_more, result.next_cursor);
	}

	async function loadSharedConversation(convId: string): Promise<void> {
		loading = true;
		error = '';
		resetStores();

		try {
			// Fetch conversation info and status in parallel
			const [info, status] = await Promise.allSettled([
				getSharedConversation(convId),
				getSharedConversationStatus(convId)
			]);

			if (info.status === 'fulfilled') {
				conversationInfo = info.value;
			}

			if (status.status === 'rejected') {
				error = 'This conversation is not available or has not been shared.';
				return;
			}

			const statusData = status.value;

			if (statusData.status === 'running' && statusData.run_id) {
				// Live conversation — connect SSE (read-only, no auth)
				connectToSharedRun(convId);
			} else if (statusData.status !== 'idle') {
				// Completed/failed/cancelled — load persisted events with pagination
				// Note: run_id may be empty string for cleaned-up runs, but events
				// are fetched by conversationId so they're still available.
				try {
					const result = await getSharedRunEvents(convId, { limit: 50000 });
					replayEventsPage(result.events, result.has_more, result.next_cursor);
				} catch {
					error = 'Could not load conversation history. The sandbox may no longer be available.';
				}
			} else {
				error = 'This conversation has no messages yet.';
			}
		} catch {
			error = 'This conversation is not available or has not been shared.';
		} finally {
			loading = false;
		}
	}

	// React to conversation ID changes
	$effect(() => {
		if (conversationId) {
			loadSharedConversation(conversationId);
		}
	});

	onDestroy(() => {
		disconnect();
		unsubMessages();
		unsubStatus();
		unsubHasMore();
	});

	let pageTitle = $derived(conversationInfo?.title || 'Shared Conversation');
	let ogDescription = $derived.by(() => {
		const base = 'View a shared AI agent conversation on Jatayu AI';
		if (conversationInfo?.title) {
			return `${conversationInfo.title} — ${base}.`;
		}
		return `${base} — the AI agent orchestration platform.`;
	});
	let formattedDate = $derived(
		conversationInfo?.date_created
			? new Date(conversationInfo.date_created).toLocaleDateString('en-US', {
					year: 'numeric',
					month: 'long',
					day: 'numeric'
				})
			: ''
	);
</script>

<svelte:head>
	<title>{pageTitle} — Jatayu AI</title>
	<meta name="description" content={ogDescription} />

	<!-- Open Graph -->
	<meta property="og:title" content="{pageTitle} — Jatayu AI" />
	<meta property="og:description" content={ogDescription} />
	<meta property="og:type" content="article" />
	<meta property="og:url" content="https://midsphere.com/shared/{conversationId}" />
	<meta property="og:site_name" content="Jatayu AI" />
	<meta property="og:image" content="https://midsphere.com/og-share.png" />
	<meta property="og:image:width" content="1200" />
	<meta property="og:image:height" content="630" />
	<meta property="og:image:alt" content="Jatayu AI — AI Agent Orchestration Platform" />
	{#if formattedDate}
		<meta property="article:published_time" content={conversationInfo?.date_created ?? ''} />
	{/if}

	<!-- Twitter Card -->
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content="{pageTitle} — Jatayu AI" />
	<meta name="twitter:description" content={ogDescription} />
	<meta name="twitter:image" content="https://midsphere.com/og-share.png" />
	<meta name="twitter:image:alt" content="Jatayu AI — AI Agent Orchestration Platform" />
</svelte:head>

<div class="flex min-h-screen flex-col bg-background">
	{#if error}
		<!-- Error state -->
		<div class="flex flex-1 flex-col items-center justify-center px-4 py-16 sm:px-6">
			<div class="w-full max-w-md text-center">
				<!-- Illustration -->
				<div class="mb-10 flex justify-center">
					<div
						class="flex h-24 w-24 items-center justify-center rounded-3xl bg-accent/[0.08] text-accent/60"
					>
						<svg
							width="44"
							height="44"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path
								d="m18.84 12.25 1.72-1.71h-.02a5.004 5.004 0 0 0-.12-7.07 5.006 5.006 0 0 0-6.95 0l-1.72 1.71"
							/>
							<path
								d="m5.17 11.75-1.71 1.71a5.004 5.004 0 0 0 .12 7.07 5.006 5.006 0 0 0 6.95 0l1.71-1.71"
							/>
							<line x1="8" x2="8.01" y1="2" y2="2" />
							<line x1="2" x2="2.01" y1="8" y2="8" />
							<line x1="22" x2="22.01" y1="16" y2="16" />
							<line x1="16" x2="16.01" y1="22" y2="22" />
						</svg>
					</div>
				</div>

				<h1 class="font-junicode text-xl tracking-tight text-foreground sm:text-2xl">
					Conversation unavailable
				</h1>
				<p class="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-subtle">
					{error}
				</p>

				<!-- eslint-disable svelte/no-navigation-without-resolve -->
				<div class="mt-8 flex flex-wrap items-center justify-center gap-3">
					<a
						href="/signup"
						class="inline-flex items-center gap-2 rounded-xl bg-foreground px-6 py-2.5 text-sm font-medium text-background transition-all duration-200"
					>
						<svg
							class="h-4 w-4"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
							<circle cx="9" cy="7" r="4" />
							<line x1="19" x2="19" y1="8" y2="14" />
							<line x1="22" x2="16" y1="11" y2="11" />
						</svg>
						Sign up for Jatayu AI
					</a>
					<button
						onclick={() => history.back()}
						class="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-border-strong bg-surface px-6 py-2.5 text-sm font-medium text-foreground transition-all duration-200 hover:border-border-strong hover:text-foreground"
					>
						<svg
							class="h-4 w-4"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<line x1="19" y1="12" x2="5" y2="12" />
							<polyline points="12 19 5 12 12 5" />
						</svg>
						Go back
					</button>
				</div>
				<!-- eslint-enable svelte/no-navigation-without-resolve -->
			</div>
		</div>
	{:else}
		<!-- Shared banner -->
		<div class="border-b border-border-subtle bg-accent/[0.03] px-4 py-2.5 sm:px-6">
			<div class="mx-auto flex max-w-3xl items-center gap-2.5">
				<div class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/[0.1]">
					<svg
						width="12"
						height="12"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="text-accent"
					>
						<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
						<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
					</svg>
				</div>
				<p class="text-[14px] text-subtle">
					Shared conversation
					<span class="mx-1 text-muted">·</span>
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a href="/signup" class="font-medium text-accent/80 transition-colors hover:text-accent">
						Sign up
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
					to create your own
				</p>
			</div>
		</div>

		<!-- Conversation header -->
		<div class="px-4 py-8 sm:px-6 sm:py-10">
			<div class="mx-auto max-w-3xl">
				{#if loading && !conversationInfo}
					<Skeleton class="rounded-lg" width="60%" height="32px" />
					<div class="mt-3">
						<Skeleton class="rounded" width="25%" height="14px" stagger={1} />
					</div>
				{:else}
					<h1 class="font-junicode text-2xl tracking-tight text-foreground sm:text-3xl">
						{pageTitle}
					</h1>
					{#if formattedDate || currentStatus !== 'idle'}
						<div class="mt-3 flex items-center gap-3">
							{#if formattedDate}
								<p class="text-sm text-muted">{formattedDate}</p>
							{/if}
							{#if currentStatus === 'running'}
								<span
									class="inline-flex items-center gap-1.5 rounded-full bg-success/[0.08] px-2.5 py-0.5 text-xs font-medium text-success"
								>
									<span class="h-1.5 w-1.5 animate-pulse rounded-full bg-success"></span>
									Live
								</span>
							{:else if currentStatus === 'completed'}
								<span
									class="inline-flex items-center gap-1.5 rounded-full bg-accent-positive/[0.08] px-2.5 py-0.5 text-xs font-medium text-accent-positive"
								>
									Completed
								</span>
							{:else if currentStatus === 'failed'}
								<span
									class="inline-flex items-center gap-1.5 rounded-full bg-accent/[0.08] px-2.5 py-0.5 text-xs font-medium text-accent"
								>
									Failed
								</span>
							{:else if currentStatus === 'cancelled'}
								<span
									class="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-muted"
								>
									Cancelled
								</span>
							{/if}
						</div>
					{/if}
				{/if}
			</div>
		</div>

		<!-- Message list -->
		<div class="mx-auto w-full max-w-3xl flex-1 px-4 sm:px-6">
			<ChatMessageList
				messages={currentMessages}
				{loading}
				hasMore={hasMoreMessages}
				runStatus={currentStatus}
				onLoadMore={handleLoadMore}
				onFileClick={handleFileClick}
			/>
		</div>

		<!-- Empty state when no messages and not loading -->
		{#if !loading && currentMessages.length === 0 && !error}
			<div class="flex flex-1 flex-col items-center justify-center px-4 py-16">
				<div class="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface">
					<svg
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
						<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
					</svg>
				</div>
				<p class="mt-4 text-sm text-muted">No messages yet</p>
			</div>
		{/if}

		<!-- Sign up CTA -->
		{#if currentMessages.length > 0 && !loading}
			<div class="border-t border-border-subtle px-4 py-10 sm:px-6 sm:py-12">
				<div class="mx-auto flex max-w-3xl flex-col items-center gap-5 text-center">
					<div class="flex h-10 w-10 items-center justify-center rounded-xl bg-surface">
						<svg
							width="20"
							height="20"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-muted"
						>
							<path d="M12 2L2 7l10 5 10-5-10-5z" />
							<path d="M2 17l10 5 10-5" />
							<path d="M2 12l10 5 10-5" />
						</svg>
					</div>
					<div>
						<p class="text-sm font-medium text-subtle">Enjoyed this conversation?</p>
						<p class="mt-1 text-sm text-muted">Build your own AI agents with Jatayu AI.</p>
					</div>
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a
						href="/signup"
						class="inline-flex items-center gap-2 rounded-xl bg-foreground px-6 py-2.5 text-sm font-medium text-background transition-all duration-200"
					>
						Get Started Free
						<svg
							class="h-4 w-4"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<line x1="5" y1="12" x2="19" y2="12" />
							<polyline points="12 5 19 12 12 19" />
						</svg>
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				</div>
			</div>
		{/if}
	{/if}
</div>

<!-- File preview dialog -->
<FilePreviewDialog bind:open={previewOpen} filename={previewFilename} fileUrl={previewFileUrl} />
