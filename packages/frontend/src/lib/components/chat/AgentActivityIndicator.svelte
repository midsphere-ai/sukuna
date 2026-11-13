<script lang="ts">
	import { onDestroy } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toolCalls as toolCallsStore, type ToolCallMessage } from '$services/sse';
	import { getActionLabel } from '$lib/utils/toolLabels';

	type ActivityState = 'reconnecting' | 'provisioning' | 'connecting' | 'executing' | 'thinking';

	type Props = {
		runStatus: string;
		isThinking: boolean;
		isReconnecting?: boolean;
	};

	let { runStatus, isThinking, isReconnecting = false }: Props = $props();

	// Track active running tool from the toolCalls store
	let activeToolCall: ToolCallMessage | null = $state(null);
	let parallelToolCount = $state(0);

	const unsubToolCalls = toolCallsStore.subscribe((map) => {
		// Show the most-recently started running tool (last in insertion order).
		// If none are running, clear the indicator so stale calls don't linger.
		let latest: ToolCallMessage | null = null;
		let runningCount = 0;
		for (const tc of map.values()) {
			if (tc.status === 'running') {
				latest = tc;
				runningCount++;
			}
		}
		activeToolCall = latest;
		parallelToolCount = runningCount;
	});

	onDestroy(() => {
		unsubToolCalls();
	});

	// Derive the current activity state based on priority
	let activityState = $derived.by((): ActivityState | null => {
		if (isReconnecting) return 'reconnecting';
		if (runStatus === 'queued' || runStatus === 'provisioning') return 'provisioning';
		if (runStatus === 'connecting') return 'connecting';
		if (runStatus === 'running' && activeToolCall) return 'executing';
		if (runStatus === 'running' && (isThinking || !activeToolCall)) return 'thinking';
		return null;
	});

	// Derive label text
	let label = $derived.by(() => {
		switch (activityState) {
			case 'reconnecting':
				return 'Reconnecting to agent...';
			case 'provisioning':
				return 'Creating your sandbox';
			case 'connecting':
				return 'Connecting to agent';
			case 'executing': {
				if (!activeToolCall) return 'Executing tool';
				const base = getActionLabel(activeToolCall.toolName, activeToolCall.args);
				return parallelToolCount > 1 ? `${base} (+${parallelToolCount - 1} more)` : base;
			}
			case 'thinking':
				return 'Thinking...';
			default:
				return '';
		}
	});

	// Subtext for long waits
	const subtexts: Partial<Record<ActivityState, string>> = {
		provisioning: 'Setting up a secure workspace',
		connecting: 'Almost ready',
		reconnecting: 'Connection interrupted, retrying'
	};

	let subtext = $derived(activityState ? (subtexts[activityState] ?? null) : null);

	// Elapsed timer for subtext reveal — only ticks while indicator is visible.
	let elapsed = $state(0);

	$effect(() => {
		// Reset elapsed whenever activityState changes.
		elapsed = 0;
		if (!activityState) return;
		const interval = setInterval(() => {
			elapsed += 1;
		}, 1000);
		return () => clearInterval(interval);
	});
</script>

{#if activityState}
	<div
		transition:fade={{ duration: 200 }}
		class="message-enter flex items-center py-2"
		data-testid="agent-activity-indicator"
		data-activity-state={activityState}
		role="status"
		aria-live="polite"
	>
		<!-- Label with shimmer + crossfade -->
		<div class="flex flex-col gap-0.5">
			{#key activityState + (activityState === 'executing' ? activeToolCall?.callId : '')}
				<span
					class="activity-shimmer text-sm"
					in:fade={{ duration: 200, delay: 60 }}
					out:fade={{ duration: 150 }}
				>
					{label}
				</span>
			{/key}

			{#if subtext && elapsed >= 5}
				<span transition:fade={{ duration: 300 }} class="text-xs text-muted">{subtext}</span>
			{/if}
		</div>
	</div>
{/if}

<style>
	/* ── Shimmer text ── */
	.activity-shimmer {
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
		animation: activityShimmer 2s ease-in-out infinite;
	}

	:global([data-theme='dark']) .activity-shimmer {
		--shimmer-low: rgba(209, 207, 192, 0.32);
		--shimmer-high: rgba(209, 207, 192, 0.62);
	}

	@keyframes activityShimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}

	/* ── Reduced motion ── */
	@media (prefers-reduced-motion: reduce) {
		.activity-shimmer {
			animation: none;
			-webkit-text-fill-color: initial;
			background: none;
		}
	}
</style>
