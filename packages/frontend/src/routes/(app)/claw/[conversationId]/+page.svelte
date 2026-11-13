<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { fade } from 'svelte/transition';
	import { get } from 'svelte/store';
	import { toasts } from '$stores/toast';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { sendClawMessage } from '$api/claw';
	import { getRunEvents, getConversationStatus } from '$api/chat';
	import {
		connectToRun,
		disconnect,
		resetStores,
		replayEventsPage,
		messages as messagesStore,
		runStatus as runStatusStore,
		isThinking as isThinkingStore
	} from '$services/sse';
	import { acquireSession } from '$stores/sandboxSession';
	import type { Message, RunStatus } from '$services/sse';
	import ClawChatInput from '$components/claw/ClawChatInput.svelte';

	let conversationId = $derived(page.params.conversationId ?? '');
	let currentMessages: Message[] = $state([]);
	let currentStatus: RunStatus = $state('idle');
	let currentThinking = $state(false);
	let loading = $state(true);
	let error = $state('');
	let sending = $state(false);
	let scrollContainer: HTMLDivElement | undefined = $state();

	const unsubMessages = messagesStore.subscribe((msgs) => {
		currentMessages = msgs;
		// Auto-scroll to bottom on new messages
		requestAnimationFrame(() => {
			if (scrollContainer) {
				scrollContainer.scrollTop = scrollContainer.scrollHeight;
			}
		});
	});
	const unsubStatus = runStatusStore.subscribe((s) => {
		currentStatus = s;
	});
	const unsubThinking = isThinkingStore.subscribe((v) => {
		currentThinking = v;
	});

	async function loadConversation(convId: string): Promise<void> {
		error = '';
		loading = true;
		resetStores();

		try {
			// Fetch conversation status
			const status = await getConversationStatus(convId);

			pageTitle.set('Claw Chat');
			showHeaderTitle.set(true);

			// Load persisted events
			if (status.status !== 'idle') {
				try {
					const result = await getRunEvents(convId, { limit: 50000 });
					if (result.events.length > 0) {
						replayEventsPage(result.events, result.has_more, result.next_cursor);
					}
				} catch {
					// Events may not be available yet
				}
			}

			const hasMessages = get(messagesStore).length > 0;

			if (status.status === 'running' && status.run_id) {
				try {
					await acquireSession({ conversationId: convId });
					connectToRun(convId, status.run_id, hasMessages);
				} catch (sessErr) {
					console.warn('[claw] failed to acquire sandbox session:', sessErr);
				}
			} else if (
				status.status === 'queued' ||
				status.status === 'provisioning' ||
				status.status === 'pending'
			) {
				try {
					await acquireSession({ conversationId: convId });
					const fresh = await getConversationStatus(convId);
					if (fresh.status === 'running' && fresh.run_id) {
						connectToRun(convId, fresh.run_id, hasMessages);
					}
				} catch (sessErr) {
					console.warn('[claw] failed to acquire session during warmup:', sessErr);
				}
			}

			loading = false;
		} catch {
			error = 'Failed to load conversation.';
			toasts.error('Failed to load conversation.');
			loading = false;
		}
	}

	$effect(() => {
		if (conversationId) {
			loadConversation(conversationId);
		}
	});

	onDestroy(() => {
		disconnect();
		unsubMessages();
		unsubStatus();
		unsubThinking();
	});

	async function handleSend(text: string): Promise<void> {
		sending = true;
		try {
			const result = await sendClawMessage({
				prompt: text,
				conversation_id: conversationId
			});
			if (result.run_id) {
				try {
					await acquireSession({ conversationId });
					connectToRun(conversationId, result.run_id, true);
				} catch (sessErr) {
					console.warn('[claw] failed to reconnect SSE:', sessErr);
				}
			}
		} catch {
			toasts.error('Failed to send message');
		} finally {
			sending = false;
		}
	}

	const _activeStatuses: RunStatus[] = ['running', 'connecting', 'queued', 'provisioning'];
	let isRunning = $derived(_activeStatuses.includes(currentStatus));
</script>

<svelte:head>
	<title>Claw Chat - Jatayu AI</title>
</svelte:head>

<div class="flex h-full flex-col">
	<!-- Header -->
	<div
		class="flex shrink-0 items-center justify-between border-b border-border-subtle px-4 py-3 sm:px-6"
	>
		<div class="flex items-center gap-3">
			<a
				href="/claw"
				class="rounded-lg p-1 text-muted transition-colors hover:bg-surface hover:text-foreground"
				aria-label="Back to Claw dashboard"
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
					<path d="M19 12H5" /><path d="M12 19l-7-7 7-7" />
				</svg>
			</a>
			<h1 class="text-sm font-medium text-foreground">Claw Chat</h1>
			{#if isRunning}
				<span class="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
					Running
				</span>
			{/if}
		</div>
	</div>

	{#if error}
		<div class="flex flex-1 flex-col items-center justify-center gap-4 px-4">
			<p class="text-sm text-muted">{error}</p>
			<button
				onclick={() => loadConversation(conversationId)}
				class="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-all"
			>
				Try again
			</button>
		</div>
	{:else if loading}
		<div class="flex flex-1 items-center justify-center">
			<svg
				class="h-5 w-5 animate-spin text-muted"
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
	{:else}
		<!-- Messages -->
		<div bind:this={scrollContainer} class="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
			{#if currentMessages.length === 0}
				<div class="flex h-full items-center justify-center">
					<p class="text-sm text-muted">No messages yet. Send a message to get started.</p>
				</div>
			{:else}
				<div class="mx-auto max-w-3xl space-y-4">
					{#each currentMessages as message, i (i)}
						{#if message.type === 'user'}
							<div class="flex justify-end" in:fade={{ duration: 100 }}>
								<div
									class="max-w-[80%] rounded-xl bg-foreground px-4 py-2.5 text-sm text-background"
								>
									<p class="whitespace-pre-wrap">{message.text}</p>
								</div>
							</div>
						{:else if message.type === 'assistant'}
							<div class="flex justify-start" in:fade={{ duration: 100 }}>
								<div
									class="max-w-[80%] rounded-xl border border-border bg-surface px-4 py-2.5 text-sm text-foreground"
								>
									<p class="whitespace-pre-wrap">{message.text}</p>
								</div>
							</div>
						{:else if message.type === 'tool_call'}
							<div class="flex justify-start" in:fade={{ duration: 100 }}>
								<div
									class="max-w-[80%] rounded-lg border border-border-subtle bg-surface-2 px-3 py-2 text-xs text-muted"
								>
									<span class="font-medium">{message.toolName}</span>
									{#if message.status === 'running'}
										<svg
											class="ml-1 inline h-3 w-3 animate-spin"
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											aria-hidden="true"
										>
											<circle
												class="opacity-25"
												cx="12"
												cy="12"
												r="10"
												stroke="currentColor"
												stroke-width="4"
											></circle>
											<path
												class="opacity-75"
												fill="currentColor"
												d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
											></path>
										</svg>
									{:else if message.status === 'success'}
										<span class="ml-1 text-green-600">done</span>
									{:else if message.status === 'error'}
										<span class="ml-1 text-red-500">error</span>
									{/if}
								</div>
							</div>
						{:else if message.type === 'error'}
							<div class="flex justify-center" in:fade={{ duration: 100 }}>
								<div class="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
									{message.message}
								</div>
							</div>
						{/if}
					{/each}

					{#if currentThinking}
						<div class="flex justify-start" in:fade={{ duration: 100 }}>
							<div
								class="rounded-xl border border-border bg-surface px-4 py-2.5 text-sm text-muted"
							>
								<span class="thinking-shimmer">Thinking...</span>
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Input -->
		<div class="shrink-0 border-t border-border-subtle px-4 py-3 sm:px-6">
			<div class="mx-auto max-w-3xl">
				<ClawChatInput
					disabled={isRunning}
					{sending}
					placeholder={isRunning ? 'Waiting for response...' : 'Type a message...'}
					onsend={handleSend}
				/>
			</div>
		</div>
	{/if}
</div>

<style>
	.thinking-shimmer {
		--shimmer-low: rgba(46, 46, 46, 0.28);
		--shimmer-high: rgba(46, 46, 46, 0.56);
		background: linear-gradient(
			90deg,
			var(--shimmer-low) 0%,
			var(--shimmer-high) 50%,
			var(--shimmer-low) 100%
		);
		background-size: 200% 100%;
		-webkit-background-clip: text;
		background-clip: text;
		-webkit-text-fill-color: transparent;
		animation: thinkingShimmer 2s ease-in-out infinite;
	}

	:global([data-theme='dark']) .thinking-shimmer {
		--shimmer-low: rgba(209, 207, 192, 0.32);
		--shimmer-high: rgba(209, 207, 192, 0.62);
	}

	@keyframes thinkingShimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.thinking-shimmer {
			animation: none;
			-webkit-text-fill-color: initial;
			background: none;
		}
	}
</style>
