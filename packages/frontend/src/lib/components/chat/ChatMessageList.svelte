<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { Skeleton } from '$components/ui';
	import UserMessage from './UserMessage.svelte';
	import AgentMessage from './AgentMessage.svelte';
	import HitlMessage from './HitlMessage.svelte';
	import ErrorMessage from './ErrorMessage.svelte';
	import ToolCallMessage from './ToolCallMessage.svelte';
	import DelegateGroup from './DelegateGroup.svelte';
	import MessageDebugDecorator from './MessageDebugDecorator.svelte';
	import BranchPointIndicator from './BranchPointIndicator.svelte';
	import AgentActivityIndicator from './AgentActivityIndicator.svelte';
	import RunFeedbackCard from './RunFeedbackCard.svelte';
	import ContextMenu from '$components/ui/ContextMenu.svelte';
	import { haptic } from '$lib/actions/gestures';
	import { get } from 'svelte/store';
	import {
		toolCalls as toolCallsStore,
		isReconnecting as isReconnectingStore,
		tokenUsage,
		type Message,
		type TextMessage,
		type ToolCallMessage as ToolCallMessageType
	} from '$services/sse';
	import { openComputerPanelAtIndex } from '$stores/computerPanel';
	import { flagEnabled } from '$stores/featureFlags';

	type Props = {
		messages: Message[];
		loading?: boolean;
		hasMore?: boolean;
		runStatus?: string;
		isThinking?: boolean;
		conversationId?: string;
		existingRating?: number | null;
		onLoadMore?: () => Promise<void>;
		onFileClick?: (filename: string) => void;
		onBranch?: (messageIndex: number) => void;
		onFeedbackSubmitted?: (rating: number) => void;
		branchPointIndex?: number | null;
		isMultiParticipant?: boolean;
		currentUserId?: string;
		onDeleteMessage?: (messageIndex: number) => void;
		onRetry?: () => void;
	};

	let {
		messages,
		loading = false,
		hasMore = false,
		runStatus = 'idle',
		isThinking = false,
		conversationId,
		existingRating = null,
		onLoadMore,
		onFileClick,
		onBranch,
		onFeedbackSubmitted,
		branchPointIndex = null,
		isMultiParticipant = false,
		currentUserId = '',
		onDeleteMessage,
		onRetry
	}: Props = $props();

	// Subscribe to reconnecting state for the activity indicator
	let isReconnecting = $state(false);
	const unsubReconnecting = isReconnectingStore.subscribe((val) => {
		isReconnecting = val;
	});

	// Feature flag subscriptions
	const debugFlag = flagEnabled('debug-mode');
	const tokenFlag = flagEnabled('show-token-usage');
	const scrollLockFlag = flagEnabled('auto-scroll-lock');
	let debugEnabled = $state(false);
	let showTokens = $state(false);
	let scrollLockEnabled = $state(false);
	let usage = $state({ inputTokens: 0, outputTokens: 0, totalTokens: 0, model: '' });
	const unsubDebug = debugFlag.subscribe((v) => {
		debugEnabled = v;
	});
	const unsubTokenFlag = tokenFlag.subscribe((v) => {
		showTokens = v;
	});
	const unsubScrollLock = scrollLockFlag.subscribe((v) => {
		scrollLockEnabled = v;
	});
	const unsubUsage = tokenUsage.subscribe((v) => {
		usage = v;
	});

	let containerEl: HTMLDivElement | undefined = $state(undefined);
	let isNearBottom = $state(true);
	let showNewMessageIndicator = $state(false);
	let prevMessageCount = $state(0);
	let isLoadingMore = $state(false);
	let feedbackDismissed = $state(false);
	let scrollLocked = $state(false);

	// Reset dismissed state and scroll lock when conversation changes
	$effect(() => {
		void conversationId;
		feedbackDismissed = false;
		scrollLocked = false;
	});

	let showFeedback = $derived(
		(runStatus === 'completed' || runStatus === 'failed' || runStatus === 'cancelled') &&
			!existingRating &&
			!feedbackDismissed
	);

	const SCROLL_THRESHOLD = 100;
	const SCROLL_LOCK_RELEASE = 50;
	const ACTIVE_RUN_STATUSES = new Set([
		'connecting',
		'queued',
		'provisioning',
		'running',
		'waiting_for_input'
	]);

	// --- Delegate grouping ---

	type GroupedMessage = { type: 'message'; msg: Message; index: number };
	type GroupedToolCall = { type: 'tool_call'; toolCall: ToolCallMessageType; index: number };
	type GroupedDelegate = {
		type: 'delegate_group';
		delegateCall: ToolCallMessageType;
		items: Message[];
		startIndex: number;
	};
	type GroupedItem = GroupedMessage | GroupedToolCall | GroupedDelegate;
	type ActiveDelegateState = {
		group: GroupedDelegate;
		rootSourceAgent?: string;
		sawExecutorEvidence: boolean;
	};

	const DELEGATE_BREAKING_TYPES = new Set(['user', 'hitl', 'error']);

	function isSkippableAssistant(msg: Message): msg is TextMessage {
		return msg.type === 'assistant' && !msg.text?.trim();
	}

	function getMessageSourceAgent(msg: Message): string | undefined {
		if (msg.type === 'assistant' || msg.type === 'tool_call' || msg.type === 'reasoning') {
			return msg.source_agent;
		}
		return undefined;
	}

	function isPlannerLikeAgent(agentName?: string): boolean {
		if (!agentName) return false;
		const normalized = agentName.toLowerCase();
		return (
			normalized === 'planner' ||
			normalized.startsWith('planner') ||
			normalized === 'main' ||
			normalized.startsWith('main') ||
			normalized === 'orchestrator' ||
			normalized.startsWith('orchestrator')
		);
	}

	function isExecutorAgentInDelegate(
		agentName: string | undefined,
		delegateSourceAgent?: string
	): boolean {
		if (!agentName) return false;
		const normalized = agentName.toLowerCase();
		const normalizedDelegate = delegateSourceAgent?.toLowerCase();

		if (normalizedDelegate && normalized === normalizedDelegate) return false;
		if (isPlannerLikeAgent(normalized)) return false;

		// If delegate source is known and this event comes from a different agent,
		// treat it as executor output.
		if (normalizedDelegate && normalized !== normalizedDelegate) return true;

		return (
			/executor|worker|sub[\s_-]?agent|delegate|child/.test(normalized) ||
			/[._-]\d+$/.test(normalized)
		);
	}

	function groupMessages(msgs: Message[]): GroupedItem[] {
		const items: GroupedItem[] = [];
		let currentDelegate: ActiveDelegateState | null = null;

		function flushDelegate(): void {
			if (!currentDelegate) return;
			items.push(currentDelegate.group);
			currentDelegate = null;
		}

		for (let i = 0; i < msgs.length; i++) {
			const msg = msgs[i];
			if (isSkippableAssistant(msg)) continue;

			if (msg.type === 'tool_call' && msg.toolName === 'delegate') {
				flushDelegate();
				currentDelegate = {
					group: {
						type: 'delegate_group',
						delegateCall: msg,
						items: [],
						startIndex: i
					},
					rootSourceAgent: getMessageSourceAgent(msg),
					sawExecutorEvidence: false
				};
				continue;
			}

			if (currentDelegate) {
				if (DELEGATE_BREAKING_TYPES.has(msg.type)) {
					flushDelegate();
				} else if (msg.type === 'step' || msg.type === 'mcp_progress') {
					// Hidden rows should not close an active delegate thread.
					continue;
				} else if (msg.type === 'tool_call') {
					const sourceAgent = getMessageSourceAgent(msg);
					if (
						isExecutorAgentInDelegate(sourceAgent, currentDelegate.rootSourceAgent) ||
						(!sourceAgent && currentDelegate.sawExecutorEvidence)
					) {
						currentDelegate.group.items.push(msg);
						if (sourceAgent) currentDelegate.sawExecutorEvidence = true;
						continue;
					}
					flushDelegate();
				} else {
					const sourceAgent = getMessageSourceAgent(msg);
					if (
						isExecutorAgentInDelegate(sourceAgent, currentDelegate.rootSourceAgent) ||
						(!sourceAgent &&
							currentDelegate.sawExecutorEvidence &&
							(msg.type === 'assistant' || msg.type === 'reasoning'))
					) {
						currentDelegate.group.items.push(msg);
						if (sourceAgent) currentDelegate.sawExecutorEvidence = true;
						continue;
					}
					flushDelegate();
				}
			}

			if (msg.type === 'tool_call') {
				items.push({ type: 'tool_call', toolCall: msg, index: i });
				continue;
			}

			items.push({ type: 'message', msg, index: i });
		}

		flushDelegate();
		return items;
	}

	// Recompute groups on every message update so streaming text and
	// tool-call status/result changes propagate immediately.
	let groupedItems = $derived.by(() => groupMessages(messages));

	function isDelegateGroupItem(item: GroupedItem | undefined): item is GroupedDelegate {
		return Boolean(item && item.type === 'delegate_group');
	}

	function getGroupKey(item: GroupedItem): string {
		if (item.type === 'delegate_group') return `dg-${item.delegateCall.callId || item.startIndex}`;
		if (item.type === 'tool_call') return `tc-${item.toolCall.callId || item.index}`;
		return getMessageKey(item.msg, item.index);
	}

	// --- Scroll management ---

	function checkScrollPosition(): void {
		if (!containerEl) return;
		const { scrollTop, scrollHeight, clientHeight } = containerEl;
		const distFromBottom = scrollHeight - scrollTop - clientHeight;
		isNearBottom = distFromBottom < SCROLL_THRESHOLD;

		if (scrollLockEnabled) {
			if (distFromBottom < SCROLL_LOCK_RELEASE) {
				scrollLocked = false;
			} else if (ACTIVE_RUN_STATUSES.has(runStatus) && !isNearBottom) {
				scrollLocked = true;
			}
		}

		if (isNearBottom && !scrollLocked) {
			showNewMessageIndicator = false;
		}
	}

	function handleScroll(): void {
		checkScrollPosition();
	}

	async function loadMoreMessages(): Promise<void> {
		if (!onLoadMore || isLoadingMore) return;
		isLoadingMore = true;

		// Anchor: remember the first visible message element
		const anchorEl = containerEl?.querySelector('.message-enter') as HTMLElement | null;

		try {
			await onLoadMore();
		} finally {
			// Wait for DOM update, then scroll the anchor back into view
			await tick();
			if (anchorEl && containerEl && anchorEl.scrollIntoView) {
				anchorEl.scrollIntoView({ block: 'start' });
				containerEl.scrollTop = Math.max(0, containerEl.scrollTop - 8);
			}

			isLoadingMore = false;
		}
	}

	function scrollToBottom(smooth = true): void {
		if (!containerEl) return;
		containerEl.scrollTo({
			top: containerEl.scrollHeight,
			behavior: smooth ? 'smooth' : 'instant'
		});
		showNewMessageIndicator = false;
	}

	// Watch for new messages
	$effect(() => {
		const currentCount = messages.length;
		if (currentCount > prevMessageCount && prevMessageCount > 0) {
			if (isNearBottom && !scrollLocked) {
				// Auto-scroll to bottom for new messages — use instant to avoid
				// jitter during high-frequency streaming updates
				tick().then(() => scrollToBottom(false));
			} else {
				// Show indicator when user has scrolled up
				showNewMessageIndicator = true;
			}
		}
		prevMessageCount = currentCount;
	});

	onMount(() => {
		if (containerEl) {
			// Scroll to bottom on initial load
			containerEl.scrollTop = containerEl.scrollHeight;
		}
	});

	onDestroy(() => {
		unsubReconnecting();
		unsubDebug();
		unsubTokenFlag();
		unsubScrollLock();
		unsubUsage();
	});

	function getMessageKey(msg: Message, index: number): string {
		if (msg.type === 'tool_call') return `tc-${msg.callId}`;
		if (msg.type === 'hitl') return `hitl-${msg.requestId}`;
		if (msg.type === 'step') return `step-${index}`;
		return `msg-${index}`;
	}

	// --- Message context menu ---

	function copyMessageText(msg: Message): void {
		let text = '';
		if (msg.type === 'user') text = msg.text;
		else if (msg.type === 'assistant') text = msg.text;
		if (!text) return;
		haptic();
		navigator.clipboard.writeText(text).then(
			() => {
				/* silent success */
			},
			() => {
				/* clipboard API may not be available */
			}
		);
	}

	function getMessageMenuItems(msg: Message, index: number) {
		const items: { label: string; icon: string; action: () => void }[] = [
			{
				label: 'Copy',
				icon: '\u{1F4CB}',
				action: () => copyMessageText(msg)
			}
		];
		if (onBranch) {
			items.push({
				label: 'Branch',
				icon: '\u{1F500}',
				action: () => {
					haptic();
					onBranch!(index);
				}
			});
		}
		return items;
	}

	/** Open the computer panel at the tool call matching this callId */
	function handleToolCallClick(callId: string): void {
		const tcMap = get(toolCallsStore);
		const keys = Array.from(tcMap.keys());
		const idx = keys.indexOf(callId);
		if (idx >= 0) {
			openComputerPanelAtIndex(idx);
		}
	}
</script>

<div
	bind:this={containerEl}
	class="scroll-container relative w-0 min-w-full flex-1 overflow-y-auto"
	onscroll={handleScroll}
	role="log"
	aria-label="Chat messages"
	aria-live="polite"
>
	<!-- Loading skeleton for history -->
	{#if isLoadingMore}
		<div class="flex flex-col gap-2 px-4 py-4 sm:px-5 md:px-6 lg:px-8">
			{#each [0, 1, 2] as i (i)}
				{#if i % 2 === 0}
					<div class="py-2">
						<div class="min-w-0 space-y-2">
							<Skeleton width="80%" />
							<Skeleton width="50%" />
						</div>
					</div>
				{:else}
					<div class="flex justify-end py-2">
						<div class="max-w-[85%]">
							<Skeleton class="rounded-2xl" width="200px" height="36px" />
						</div>
					</div>
				{/if}
			{/each}
		</div>
	{/if}

	{#if hasMore && !isLoadingMore}
		<div class="flex justify-center py-3">
			<button
				onclick={loadMoreMessages}
				class="flex items-center gap-2 rounded-full border border-border bg-background px-4 py-2 text-xs font-medium text-muted transition-all hover:bg-accent/5 hover:text-foreground"
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
					<path d="m17 11-5-5-5 5" />
					<path d="M12 18V6" />
				</svg>
				Load earlier messages
			</button>
		</div>
	{/if}

	<!-- Initial loading state -->
	{#if loading && messages.length === 0}
		<div
			class="flex flex-col gap-2 px-4 py-6 sm:px-5 md:px-6 lg:px-8"
			data-testid="message-skeleton"
		>
			{#each [0, 1, 2, 3] as i (i)}
				{#if i % 2 === 0}
					<!-- Agent message skeleton: left-aligned -->
					<div class="py-2">
						<div class="min-w-0 space-y-2">
							<Skeleton width="90%" stagger={i + 1} />
							<Skeleton width="70%" stagger={i + 2} />
						</div>
					</div>
				{:else}
					<!-- User message skeleton: right-aligned bubble -->
					<div class="flex justify-end py-2">
						<div class="max-w-[85%]">
							<Skeleton class="rounded-2xl" width="240px" height="40px" stagger={i} />
						</div>
					</div>
				{/if}
			{/each}
		</div>
	{:else}
		<!-- Message list with delegate-thread grouping -->
		<div class="flex flex-col gap-2 px-4 py-6 sm:px-5 md:px-6 lg:px-8">
			{#each groupedItems as item, itemIdx (getGroupKey(item))}
				{#if item.type === 'delegate_group'}
					<div
						class="message-item message-enter {isDelegateGroupItem(groupedItems[itemIdx - 1])
							? '-mt-1'
							: ''} {isDelegateGroupItem(groupedItems[itemIdx + 1]) ? '-mb-1' : ''}"
					>
						<DelegateGroup
							delegateCall={item.delegateCall}
							items={item.items}
							onToolCallClick={handleToolCallClick}
							showConnectorAbove={isDelegateGroupItem(groupedItems[itemIdx - 1])}
							showConnectorBelow={isDelegateGroupItem(groupedItems[itemIdx + 1])}
							forceRunningIndicator={ACTIVE_RUN_STATUSES.has(runStatus) &&
								itemIdx === groupedItems.length - 1}
						/>
					</div>
					{#if debugEnabled}
						<!-- Decorate the delegate call itself, then every executor-side sub-item that
						     DelegateGroup collapses into its thread, so debug mode surfaces
						     every underlying event (tool calls, results, reasoning, steps) from
						     the executor agent. -->
						<MessageDebugDecorator message={item.delegateCall} index={item.startIndex} />
						{#each item.items as subMsg, subIdx (subIdx)}
							<MessageDebugDecorator message={subMsg} index={item.startIndex + 1 + subIdx} />
						{/each}
					{/if}
				{:else if item.type === 'tool_call'}
					<div class="message-item message-enter">
						<ToolCallMessage
							message={item.toolCall}
							onClick={() => handleToolCallClick(item.toolCall.callId)}
						/>
					</div>
					{#if debugEnabled}
						<MessageDebugDecorator message={item.toolCall} index={item.index} />
					{/if}
				{:else if item.msg.type === 'user'}
					{#if branchPointIndex !== null && branchPointIndex === item.index}
						<BranchPointIndicator />
					{/if}
					<div class="message-item message-enter">
						<ContextMenu items={getMessageMenuItems(item.msg, item.index)}>
							<UserMessage
								message={item.msg}
								{onFileClick}
								messageIndex={item.index}
								{onBranch}
								{isMultiParticipant}
								{currentUserId}
								onDelete={onDeleteMessage}
							/>
						</ContextMenu>
					</div>
					{#if debugEnabled}
						<MessageDebugDecorator message={item.msg} index={item.index} />
					{/if}
				{:else if item.msg.type === 'assistant'}
					{#if branchPointIndex !== null && branchPointIndex === item.index}
						<BranchPointIndicator />
					{/if}
					<div class="message-item message-enter">
						<AgentMessage
							message={item.msg}
							startedByName={isMultiParticipant ? item.msg.started_by_name : undefined}
						/>
					</div>
					{#if debugEnabled}
						<MessageDebugDecorator message={item.msg} index={item.index} />
					{/if}
				{:else if item.msg.type === 'hitl'}
					<div class="message-item message-enter">
						<HitlMessage message={item.msg} />
					</div>
					{#if debugEnabled}
						<MessageDebugDecorator message={item.msg} index={item.index} />
					{/if}
				{:else if item.msg.type === 'error'}
					<div class="message-item message-enter">
						<ErrorMessage message={item.msg} {onRetry} />
					</div>
					{#if debugEnabled}
						<MessageDebugDecorator message={item.msg} index={item.index} />
					{/if}
				{:else if item.msg.type === 'step'}
					<!-- Step indicators hidden unless debug mode exposes them -->
					{#if debugEnabled}
						<MessageDebugDecorator message={item.msg} index={item.index} />
					{/if}
				{:else if item.msg.type === 'reasoning'}
					<!-- Reasoning -->
					<div class="message-item my-1 rounded-lg bg-accent/5 px-3 py-2">
						<p class="text-xs italic text-subtle">{item.msg.text}</p>
					</div>
					{#if debugEnabled}
						<MessageDebugDecorator message={item.msg} index={item.index} />
					{/if}
				{:else if item.msg.type === 'mcp_progress'}
					<!-- Hidden from chat — consumed by canvas renderers -->
					{#if debugEnabled}
						<MessageDebugDecorator message={item.msg} index={item.index} />
					{/if}
				{/if}
			{/each}

			<!-- Terminal run status as inline message -->
			{#if runStatus === 'completed'}
				<div class="message-enter flex items-center gap-2 py-2">
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
						class="text-success"
					>
						<polyline points="20 6 9 17 4 12" />
					</svg>
					<span class="text-[14px] text-success">Task completed</span>
				</div>
			{:else if runStatus === 'failed'}
				<div class="message-enter flex items-center gap-2 py-2">
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
						class="text-accent"
					>
						<circle cx="12" cy="12" r="10" />
						<line x1="15" x2="9" y1="9" y2="15" />
						<line x1="9" x2="15" y1="9" y2="15" />
					</svg>
					<span class="text-[14px] text-accent">Task failed</span>
				</div>
			{:else if runStatus === 'cancelled'}
				<div class="message-enter flex items-center gap-2 py-2">
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
						class="text-muted"
					>
						<circle cx="12" cy="12" r="10" />
						<line x1="8" x2="16" y1="12" y2="12" />
					</svg>
					<span class="text-[14px] text-muted">Task cancelled</span>
				</div>
			{/if}

			<!-- Debug info (feature flag: debug-mode) -->
			{#if debugEnabled && (runStatus === 'completed' || runStatus === 'failed' || runStatus === 'cancelled')}
				<div
					class="message-enter flex items-center gap-3 rounded-lg bg-accent/5 px-3 py-1.5 font-mono text-[11px] text-muted"
				>
					{#if usage.model}<span>model: {usage.model}</span>{/if}
					<span
						>{usage.inputTokens.toLocaleString()} in / {usage.outputTokens.toLocaleString()} out</span
					>
					<span>({usage.totalTokens.toLocaleString()} total)</span>
				</div>
			{/if}

			<!-- Token usage counter (feature flag: show-token-usage) -->
			{#if showTokens && usage.totalTokens > 0}
				<div class="flex items-center gap-2 py-1 font-mono text-[11px] text-muted">
					<span>{usage.inputTokens.toLocaleString()} in</span>
					<span class="text-border">/</span>
					<span>{usage.outputTokens.toLocaleString()} out</span>
					{#if usage.model}
						<span class="text-border">|</span>
						<span>{usage.model}</span>
					{/if}
				</div>
			{/if}

			<!-- Run feedback inline card -->
			{#if showFeedback && conversationId}
				<RunFeedbackCard
					{conversationId}
					onSubmitted={(rating) => {
						onFeedbackSubmitted?.(rating);
					}}
					onDismiss={() => {
						feedbackDismissed = true;
					}}
				/>
			{/if}

			<!-- Agent activity indicator (inline) -->
			<AgentActivityIndicator {runStatus} {isThinking} {isReconnecting} />
		</div>

		<!-- Waiting state: show response skeletons while agent is actively running -->
		{#if messages.length === 0 && !loading && (runStatus === 'running' || runStatus === 'queued' || runStatus === 'provisioning' || runStatus === 'connecting')}
			<div class="flex flex-col gap-2 px-4 py-6 sm:px-5 md:px-6 lg:px-8">
				<div class="py-2">
					<div class="min-w-0 space-y-2">
						<Skeleton width="85%" />
						<Skeleton width="65%" />
						<Skeleton width="45%" />
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>

<!-- Scroll lock / new messages indicator -->
{#if scrollLocked}
	<div class="absolute bottom-20 left-1/2 z-10 -translate-x-1/2">
		<button
			onclick={() => {
				scrollLocked = false;
				scrollToBottom();
			}}
			class="flex items-center gap-1.5 rounded-full border border-amber-400/50 bg-amber-50 px-4 py-2 text-xs font-medium text-amber-700 shadow-lg transition-all hover:shadow-xl dark:border-amber-500/30 dark:bg-amber-900/30 dark:text-amber-300"
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
				<rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path
					d="M7 11V7a5 5 0 0110 0v4"
				/>
			</svg>
			Auto-scroll paused
		</button>
	</div>
{:else if showNewMessageIndicator}
	<div class="new-msg-indicator absolute bottom-20 left-1/2 z-10">
		<button
			onclick={() => scrollToBottom()}
			class="flex items-center gap-1.5 rounded-full border border-border bg-background px-4 py-2 text-xs font-medium text-foreground shadow-lg transition-all hover:shadow-xl"
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
				<path d="m7 13 5 5 5-5" />
				<path d="M12 18V6" />
			</svg>
			New messages
		</button>
	</div>
{/if}

<style>
	/* E3: Allow the browser to skip rendering for off-screen messages */
	.message-item {
		content-visibility: auto;
		contain-intrinsic-block-size: auto 80px;
	}

	/* E4: Enable native scroll anchoring so content above doesn't shift the viewport */
	.scroll-container {
		overflow-anchor: auto;
	}
</style>
