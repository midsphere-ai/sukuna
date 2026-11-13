<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { get } from 'svelte/store';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import ChatMessageList from '$components/chat/ChatMessageList.svelte';
	import { chatFilesDialogOpen } from '$stores/computerPanel';
	import BranchSwitcher from '$components/chat/BranchSwitcher.svelte';
	import FilePreviewDialog from '$components/chat/FilePreviewDialog.svelte';
	import ChatFilesDialog from '$components/chat/ChatFilesDialog.svelte';
	import ActiveChatInput from '$components/chat/ActiveChatInput.svelte';
	import HitlInputBar from '$components/chat/HitlInputBar.svelte';
	import {
		connectToRun,
		disconnect,
		resetStores,
		replayEventsPage,
		restorePaginationState,
		prependOlderEvents,
		eventsHasMore,
		getOldestLoadedCursor,
		addUserMessage,
		consumePendingPrompt,
		messages as messagesStore,
		runStatus as runStatusStore,
		isThinking as isThinkingStore,
		injectionQueuePosition as injectionQueuePositionStore,
		hitlRequest as hitlRequestStore,
		getCurrentRunId
	} from '$services/sse';
	import { getCachedChat, setCachedChat, invalidateCachedChat } from '$services/chatCache';
	import { getConversationStatus, getRunEvents } from '$api/chat';
	import {
		submitHitlResponse as submitHitlResponseRun,
		branchRun,
		cancelRun as cancelRunSandbox
	} from '$api/run';
	import { acquireSession } from '$stores/sandboxSession';
	import { getFileDownloadUrl } from '$api/files';

	import { conversations } from '$stores/conversations';
	import { updateHitlResponse } from '$services/sse';
	import type { Message, RunStatus, HitlRequest } from '$services/sse';
	import {
		addBranch,
		getBranchesForConversation,
		getParentInfo,
		branchMap
	} from '$stores/branches';
	import { onStopAgent, onExportChat } from '$stores/shortcuts';
	import { computerPanelVncActive, computerPanelOpen } from '$stores/computerPanel';
	import {
		isGalleryConversation,
		loadGalleryConversation,
		GALLERY_TITLE
	} from '$lib/data/galleryConversation';
	import {
		projectSandboxBusy,
		startSandboxStatusPolling,
		stopSandboxStatusPolling
	} from '$stores/sandboxStatus';
	import { startPresence, stopPresence, presentUsers } from '$stores/presence';
	import { currentUser } from '$stores/auth';
	import InjectionQueueBanner from '$components/chat/InjectionQueueBanner.svelte';
	import type { PresenceUser } from '$stores/presence';
	import DebugPanel from '$components/debug/DebugPanel.svelte';
	import { flagEnabled } from '$stores/featureFlags';
	import { debugPanelOpen } from '$stores/debugPanel';

	// In-memory status cache — avoids re-fetching getConversationStatus on re-navigation
	// eslint-disable-next-line svelte/prefer-svelte-reactivity -- intentionally non-reactive cache
	const statusCache = new Map<
		string,
		{ status: string; run_id: string | null; rating?: number | null; my_role?: string | null }
	>();

	// Guard against concurrent loadConversation calls (e.g. $effect firing twice)
	let loadGeneration = 0;

	let conversationId = $derived(page.params.id ?? '');

	let currentMessages: Message[] = $state([]);
	let currentStatus: RunStatus = $state('idle');
	let currentThinking = $state(false);
	let currentHitlRequest: HitlRequest | null = $state(null);
	let loading = $state(true);
	let error = $state('');
	let branching = $state(false);
	let readOnly = $state(false);
	let myRole = $state<'creator' | 'collaborator' | 'viewer' | null>(null);
	let isViewOnly = $derived(myRole === 'viewer');
	let existingRating: number | null = $state(null);
	let sandboxBusy: { conversationId: string | null; conversationTitle: string | null } | null =
		$state(null);

	const unsubSandboxBusy = projectSandboxBusy.subscribe((v) => {
		sandboxBusy = v;
	});

	// Presence
	let authUser = $state<{ id: string } | null>(null);
	let presenceUserList = $state<PresenceUser[]>([]);
	const unsubAuthUser = currentUser.subscribe((v) => (authUser = v));
	const unsubPresenceList = presentUsers.subscribe((v) => (presenceUserList = v));

	// Injection queue
	let queuePosition = $state<number | null>(null);
	const unsubQueue = injectionQueuePositionStore.subscribe((v) => (queuePosition = v));

	// Debug panel visibility (gated on debug-mode flag)
	let debugFlag = $state(false);
	let debugOpen = $state(false);
	const debugFlagStore = flagEnabled('debug-mode');
	const unsubDebugFlag = debugFlagStore.subscribe((v) => (debugFlag = v));
	const unsubDebugOpen = debugPanelOpen.subscribe((v) => (debugOpen = v));
	let showDebugPanel = $derived(debugFlag && debugOpen);

	// Multi-participant: true when more than 1 presence user or messages have different sender_ids
	let isMultiParticipant = $derived.by(() => {
		if (presenceUserList.length > 1) return true;
		const senderIds = new Set<string>();
		for (const m of currentMessages) {
			if (m.type === 'user' && m.sender_id) senderIds.add(m.sender_id);
			if (senderIds.size > 1) return true;
		}
		return false;
	});

	// Branch state
	let branches = $state<ReturnType<typeof getBranchesForConversation>>([]);
	let parentInfo = $state<ReturnType<typeof getParentInfo>>(null);

	function refreshBranchInfo(): void {
		branches = getBranchesForConversation(conversationId);
		parentInfo = getParentInfo(conversationId);
	}

	// Re-derive branch info when branchMap changes
	const unsubBranches = branchMap.subscribe(() => {
		refreshBranchInfo();
	});

	$effect(() => {
		// Update branch info when conversation changes
		// Touch conversationId to trigger reactivity
		void conversationId;
		refreshBranchInfo();
	});

	// Start presence tracking when conversation changes
	$effect(() => {
		const id = conversationId;
		if (id) {
			startPresence(id);
		}
		return () => {
			stopPresence();
		};
	});

	// File preview state
	let previewOpen = $state(false);
	let previewFilename = $state('');
	let previewFileUrl = $state('');

	// Files dialog state (triggered from layout-level ChatHeader)
	let filesDialogOpen = $state(false);
	const unsubFilesDialog = chatFilesDialogOpen.subscribe((v) => {
		if (v) {
			filesDialogOpen = true;
			chatFilesDialogOpen.set(false);
		}
	});

	type FileEntry = {
		filename: string;
		url: string;
		size?: number;
		timestamp?: string;
	};

	const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

	// Cache resolved attachment URLs so repeated clicks don't re-fetch signed links.
	const attachmentPreviewCache = new Map<string, FileEntry>();

	/** Extract all files referenced in conversation messages */
	let sessionFiles = $derived.by(() => {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local Set inside $derived, not reactive state
		const seen = new Set<string>();
		const entries: FileEntry[] = [];

		for (const msg of currentMessages) {
			// User-uploaded files
			if (msg.type === 'user' && msg.files) {
				for (const f of msg.files) {
					const filename = f.split('/').pop() || f;
					if (seen.has(filename)) continue;
					seen.add(filename);
					entries.push({ filename, url: '' });
				}
			}
			// Tool call results that include file attachments (e.g., message type=result)
			if (msg.type === 'tool_call' && msg.result && typeof msg.result === 'object') {
				const meta = (msg.result as Record<string, unknown>).metadata as
					Record<string, unknown> | undefined;
				const files = meta?.uploaded_files as Array<Record<string, string>> | undefined;
				if (files) {
					for (const f of files) {
						const filename = f.filename || f.file_id || 'attachment';
						if (seen.has(filename)) continue;
						seen.add(filename);
						entries.push({ filename, url: f.url || '' });
					}
				}
			}
		}
		return entries;
	});

	async function handleFileClick(fileRef: string): Promise<void> {
		const cached = attachmentPreviewCache.get(fileRef);
		if (cached) {
			previewFilename = cached.filename;
			previewFileUrl = cached.url;
			previewOpen = true;
			return;
		}

		const fromSession = sessionFiles.find((f) => f.filename === fileRef || f.url === fileRef);
		if (fromSession?.url) {
			attachmentPreviewCache.set(fileRef, fromSession);
			previewFilename = fromSession.filename;
			previewFileUrl = fromSession.url;
			previewOpen = true;
			return;
		}

		if (fileRef.startsWith('http://') || fileRef.startsWith('https://')) {
			const filename = fileRef.split('/').pop() || 'attachment';
			const direct = { filename, url: fileRef };
			attachmentPreviewCache.set(fileRef, direct);
			previewFilename = direct.filename;
			previewFileUrl = direct.url;
			previewOpen = true;
			return;
		}

		if (!UUID_RE.test(fileRef)) {
			toasts.error('Preview unavailable for this attachment.');
			return;
		}

		try {
			const result = await getFileDownloadUrl(fileRef);
			const resolved = {
				filename: result.filename || fileRef,
				url: result.url
			};
			attachmentPreviewCache.set(fileRef, resolved);
			previewFilename = resolved.filename;
			previewFileUrl = resolved.url;
			previewOpen = true;
		} catch {
			toasts.error('Failed to load file preview.');
		}
	}

	async function handleBranch(messageIndex: number): Promise<void> {
		if (!conversationId) {
			toasts.error('Cannot branch: no active conversation.');
			return;
		}
		const runId = getCurrentRunId();
		if (!runId) {
			toasts.error('Cannot branch: no active run to branch from.');
			return;
		}
		branching = true;
		try {
			const result = await branchRun(conversationId, runId, String(messageIndex));
			addBranch(conversationId, result.branch_conversation_id, messageIndex);
			statusCache.delete(conversationId);
			invalidateCachedChat(conversationId);
			toasts.success('Conversation branched');
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic branch navigation
			goto(`/chat/${result.branch_conversation_id}`);
		} catch {
			toasts.error('Failed to branch conversation. Please try again.');
		} finally {
			branching = false;
		}
	}

	async function handleHitlSubmit(requestId: string, response: string): Promise<void> {
		if (!conversationId) {
			toasts.error('Cannot submit response: no active connection.');
			return;
		}
		const runId = getCurrentRunId();
		if (!runId) {
			toasts.error('Cannot submit response: no active run.');
			return;
		}
		try {
			await submitHitlResponseRun(conversationId, runId, requestId, response);
			updateHitlResponse(requestId, response);
		} catch {
			toasts.error('Failed to submit response. Please try again.');
		}
	}

	// Subscribe to SSE stores
	const unsubMessages = messagesStore.subscribe((msgs) => {
		currentMessages = msgs;
	});
	const unsubStatus = runStatusStore.subscribe((s) => {
		currentStatus = s;
	});
	const unsubThinking = isThinkingStore.subscribe((v) => {
		currentThinking = v;
	});
	const unsubHitl = hitlRequestStore.subscribe((v) => {
		currentHitlRequest = v;
	});

	// Pagination state
	let hasMoreMessages = $state(false);
	const unsubHasMore = eventsHasMore.subscribe((v) => {
		hasMoreMessages = v;
	});

	async function handleLoadMore(): Promise<void> {
		if (!conversationId) return;
		const cursor = getOldestLoadedCursor();
		const result = await getRunEvents(conversationId, {
			cursor,
			limit: 50000
		});
		prependOlderEvents(result.events, result.has_more, result.next_cursor);
	}

	async function loadConversation(convId: string): Promise<void> {
		// Increment generation so any in-flight previous call becomes stale
		const thisGen = ++loadGeneration;
		const isStale = () => thisGen !== loadGeneration;

		error = '';
		computerPanelVncActive.set(false);

		// Gallery / demo conversation — load mock data, skip API calls
		if (isGalleryConversation(convId)) {
			resetStores();
			loadGalleryConversation();
			pageTitle.set(GALLERY_TITLE);
			showHeaderTitle.set(true);
			readOnly = true;
			computerPanelOpen.set(true);
			loading = false;
			return;
		}

		// Check if we already know about this conversation from the sidebar store
		const known = get(conversations).find((c) => c.id === convId);
		const cached = statusCache.get(convId);

		// Try to restore from in-memory chat cache (instant navigation)
		const chatCached = getCachedChat(convId);
		const cachedStatus = cached?.status;
		if (chatCached && cachedStatus && cachedStatus !== 'running') {
			resetStores();
			messagesStore.set(chatCached.messages);
			restorePaginationState(chatCached.hasMore, chatCached.cursor);
			if (known?.title) pageTitle.set(known.title);
			showHeaderTitle.set(true);
			loading = false;

			// Silent background status revalidation
			getConversationStatus(convId)
				.then(async (freshStatus) => {
					statusCache.set(convId, {
						status: freshStatus.status,
						run_id: freshStatus.run_id,
						rating: freshStatus.rating,
						my_role: freshStatus.my_role
					});
					if (freshStatus.status === 'running' && freshStatus.run_id) {
						// Status changed to running — acquire session + reconnect SSE
						try {
							await acquireSession({ conversationId: convId });
							connectToRun(convId, freshStatus.run_id, true);
						} catch (sessErr) {
							console.warn('[loadConversation] failed to acquire sandbox session:', sessErr);
						}
					}
				})
				.catch((err) => {
					console.warn('[loadConversation] background revalidation failed:', err);
				});
			return;
		}

		resetStores();

		// Restore pending user message from home-page submission (survives resetStores)
		const pendingText = consumePendingPrompt();

		// If we have cached knowledge, show the chat shell instantly
		if (known || cached) {
			loading = false;
			showHeaderTitle.set(true);
			if (known?.title) pageTitle.set(known.title);
		} else {
			loading = true;
		}

		// Show pending user message immediately while we fetch status
		if (pendingText) {
			addUserMessage(pendingText, undefined, undefined, undefined, `pending-${Date.now()}`);
		}

		try {
			// Use cached status if available, otherwise fetch
			const status = cached ?? (await getConversationStatus(convId));
			if (isStale()) {
				return;
			}

			// Cache the status for future re-navigation
			statusCache.set(convId, {
				status: status.status,
				run_id: status.run_id,
				rating: status.rating,
				my_role: status.my_role
			});
			existingRating = status.rating ?? null;
			myRole = (status.my_role as typeof myRole) ?? null;

			showHeaderTitle.set(true);

			// Always load persisted events — the events API uses conversationId,
			// not run_id, so even conversations where run_id is empty/missing
			// (e.g. failed or completed runs) will have their history loaded.
			// Only skip for truly idle conversations that never had a run.
			const shouldLoadEvents = status.status !== 'idle';
			if (shouldLoadEvents) {
				try {
					const result = await getRunEvents(convId, { limit: 50000 });
					if (isStale()) {
						return;
					}
					replayEventsPage(result.events, result.has_more, result.next_cursor);

					// replayEventsPage does a full messages.set(), which wipes the
					// optimistic user message added above.  Re-add it if the replayed
					// events did not include it (common when the run is so new
					// that no events have been persisted yet).
					if (pendingText) {
						const msgs = get(messagesStore);
						const hasUserMsg = msgs.some((m) => m.type === 'user' && m.text === pendingText);
						if (!hasUserMsg) {
							addUserMessage(pendingText, undefined, undefined, undefined, `pending-${Date.now()}`);
						}
					}
					setCachedChat(convId, {
						messages: get(messagesStore),
						hasMore: result.has_more,
						cursor: result.next_cursor
					});
				} catch (evtErr) {
					console.error('[loadConversation] Failed to load events:', evtErr);
					// Events may not be available yet for queued runs — that's OK
				}
			}

			const hasMessages = get(messagesStore).length > 0;

			if (status.status === 'running' && status.run_id) {
				loading = false;
				// Ensure sandbox session exists for SSE auth, then connect direct.
				try {
					await acquireSession({ conversationId: convId });
					connectToRun(convId, status.run_id, hasMessages);
				} catch (sessErr) {
					console.error('[loadConversation] failed to acquire sandbox session:', sessErr);
					toasts.error('Failed to connect to sandbox.');
				}
			} else if (
				status.status === 'queued' ||
				status.status === 'provisioning' ||
				status.status === 'pending'
			) {
				// Run is still starting. Acquire the session (which waits for sandbox
				// health) and poll status once more — if it has a run_id, connect.
				loading = false;
				try {
					await acquireSession({ conversationId: convId });
					const fresh = await getConversationStatus(convId);
					if (fresh.status === 'running' && fresh.run_id) {
						statusCache.set(convId, {
							status: fresh.status,
							run_id: fresh.run_id,
							rating: fresh.rating,
							my_role: fresh.my_role
						});
						connectToRun(convId, fresh.run_id, hasMessages);
					} else if (
						fresh.status === 'completed' ||
						fresh.status === 'failed' ||
						fresh.status === 'cancelled'
					) {
						statusCache.set(convId, {
							status: fresh.status,
							run_id: fresh.run_id,
							rating: fresh.rating,
							my_role: fresh.my_role
						});
					}
				} catch (sessErr) {
					console.warn('[loadConversation] failed to acquire session during warmup:', sessErr);
				}
			} else {
				// Completed, failed, cancelled, or idle — events already loaded above
				loading = false;
			}
		} catch (err: unknown) {
			console.error('[loadConversation] Fatal error:', err);
			const status = (err as { status?: number })?.status;
			if (status === 403) {
				toasts.error('Access to this project has been revoked');
				goto('/projects');
				return;
			}
			error = 'Failed to load conversation. Please try again.';
			toasts.error('Failed to load conversation.');
			loading = false;
		}
	}

	// React to conversation ID changes
	$effect(() => {
		if (conversationId) {
			loadConversation(conversationId);
		}
	});

	// Reactively update page title and sandbox polling when conversation data arrives
	// (handles race where fetchConversations completes after loadConversation)
	$effect(() => {
		const convId = conversationId;
		if (!convId || isGalleryConversation(convId)) return;
		const unsub = conversations.subscribe((convs) => {
			const match = convs.find((c) => c.id === convId);
			if (match?.title) {
				pageTitle.set(match.title);
			}
			if (match?.project_id) {
				startSandboxStatusPolling(match.project_id, convId);
			}
		});
		return unsub;
	});

	// Register keyboard shortcut callbacks
	onStopAgent.set(async () => {
		if (conversationId && currentStatus === 'running') {
			const runId = getCurrentRunId();
			if (!runId) return;
			try {
				await cancelRunSandbox(conversationId, runId);
				statusCache.delete(conversationId);
				toasts.info('Agent stopped.');
			} catch {
				toasts.error('Failed to stop agent.');
			}
		}
	});

	onExportChat.set(() => {
		if (currentMessages.length === 0) return;
		const text = currentMessages
			.map((m) => {
				if (m.type === 'user') return `[user]: ${m.text}`;
				if (m.type === 'assistant') return `[assistant]: ${m.text}`;
				if (m.type === 'tool_call') return `[tool]: ${m.toolName}`;
				if (m.type === 'error') return `[error]: ${m.message}`;
				return `[${m.type}]`;
			})
			.join('\n\n');
		const blob = new Blob([text], { type: 'text/plain' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `chat-${conversationId}.txt`;
		a.click();
		URL.revokeObjectURL(url);
	});

	onDestroy(() => {
		disconnect();
		unsubMessages();
		unsubStatus();
		unsubThinking();
		unsubHitl();
		unsubHasMore();
		unsubBranches();
		unsubFilesDialog();
		unsubSandboxBusy();
		unsubAuthUser();
		unsubPresenceList();
		unsubQueue();
		unsubDebugFlag();
		unsubDebugOpen();
		stopPresence();
		stopSandboxStatusPolling();
		computerPanelVncActive.set(false);
		onStopAgent.set(null);
		onExportChat.set(null);
	});
</script>

<svelte:head>
	<title>Chat - Jatayu AI</title>
</svelte:head>

<div class="flex h-full w-full flex-row overflow-hidden">
	<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
		{#if error}
			<div class="flex flex-1 flex-col items-center justify-center gap-4 px-4">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="48"
					height="48"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="text-muted"
				>
					<circle cx="12" cy="12" r="10" />
					<line x1="12" x2="12" y1="8" y2="12" />
					<line x1="12" x2="12.01" y1="16" y2="16" />
				</svg>
				<p class="text-sm text-subtle">{error}</p>
				<button
					onclick={() => loadConversation(conversationId)}
					class="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-all"
				>
					Try again
				</button>
			</div>
		{:else}
			<!-- Branch switcher bar -->
			{#if branches.length > 0 || parentInfo}
				<div class="flex items-center gap-2 border-b border-border-subtle px-4 py-2 sm:px-6">
					<BranchSwitcher
						{conversationId}
						parentConversationId={parentInfo?.parentConversationId ?? null}
						{branches}
					/>
					{#if branching}
						<span class="text-xs text-muted">Creating branch...</span>
					{/if}
				</div>
			{/if}

			<!-- Message list -->
			<ChatMessageList
				messages={currentMessages}
				{loading}
				hasMore={hasMoreMessages}
				runStatus={currentStatus}
				isThinking={currentThinking}
				conversationId={readOnly ? undefined : conversationId}
				{existingRating}
				onLoadMore={handleLoadMore}
				onFileClick={handleFileClick}
				onBranch={handleBranch}
				onFeedbackSubmitted={(rating) => {
					existingRating = rating;
				}}
				branchPointIndex={parentInfo?.fromMessageIndex ?? null}
				{isMultiParticipant}
				currentUserId={authUser?.id ?? ''}
			/>

			<!-- Injection queue banner -->
			<InjectionQueueBanner position={queuePosition} />

			<!-- Chat input / HITL input bar -->
			{#if currentStatus === 'waiting_for_input' && currentHitlRequest}
				<HitlInputBar hitlRequest={currentHitlRequest} onSubmit={handleHitlSubmit} />
			{:else}
				<ActiveChatInput
					{conversationId}
					runStatus={currentStatus}
					readOnly={readOnly || isViewOnly}
					sandboxBusyConversation={sandboxBusy}
					viewOnlyMessage={isViewOnly ? 'View only' : undefined}
				/>
			{/if}
		{/if}
	</div>
	{#if showDebugPanel}
		<DebugPanel />
	{/if}
</div>

<!-- File preview dialog -->
<FilePreviewDialog bind:open={previewOpen} filename={previewFilename} fileUrl={previewFileUrl} />

<!-- Session files dialog -->
<ChatFilesDialog bind:open={filesDialogOpen} files={sessionFiles} />
