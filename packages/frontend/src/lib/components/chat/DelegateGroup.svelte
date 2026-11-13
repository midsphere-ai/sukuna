<script lang="ts">
	import type { Message, ToolCallMessage, TextMessage } from '$services/sse';
	import { getActionLabel } from '$lib/utils/toolLabels';
	import ToolCallMessageRow from './ToolCallMessage.svelte';
	import AgentMessage from './AgentMessage.svelte';

	type Props = {
		delegateCall: ToolCallMessage;
		items: Message[];
		onToolCallClick?: (callId: string) => void;
		isMultiParticipant?: boolean;
		showConnectorAbove?: boolean;
		showConnectorBelow?: boolean;
		forceRunningIndicator?: boolean;
	};

	let {
		delegateCall,
		items,
		onToolCallClick,
		isMultiParticipant = false,
		showConnectorAbove = false,
		showConnectorBelow = false,
		forceRunningIndicator = false
	}: Props = $props();
	let expanded = $state(true);

	function toggle(): void {
		expanded = !expanded;
	}

	function firstNonEmptyString(...values: unknown[]): string | null {
		for (const value of values) {
			if (typeof value !== 'string') continue;
			const trimmed = value.trim();
			if (trimmed) return trimmed;
		}
		return null;
	}

	function hasVisibleMessageBody(msg: ToolCallMessage): boolean {
		if (msg.toolName !== 'message') return false;
		const result =
			typeof msg.result === 'object' && msg.result !== null
				? (msg.result as Record<string, unknown>)
				: null;
		const resultText = typeof msg.result === 'string' ? msg.result : null;
		return Boolean(
			firstNonEmptyString(
				msg.args?.text,
				msg.args?.content,
				result?.message,
				result?.text,
				result?.content,
				result?.output,
				result?.answer,
				result?.final_answer,
				result?.summary,
				resultText
			)
		);
	}

	let delegateLabel = $derived.by(() => {
		const fallback = getActionLabel(delegateCall.toolName, delegateCall.args);
		return (
			firstNonEmptyString(
				delegateCall.args?._exo_tool_brief,
				delegateCall.args?.brief,
				delegateCall.args?.task,
				delegateCall.args?.message,
				fallback
			) || fallback
		);
	});

	let status = $derived(delegateCall.status);
	let indicatorStatus = $derived.by(() => {
		if (status === 'running') return 'running';

		const hasRunningChild = items.some(
			(item) =>
				(item.type === 'tool_call' && item.status === 'running') ||
				(item.type === 'assistant' && item.isStreaming)
		);

		if (hasRunningChild) return 'running';
		if (forceRunningIndicator) return 'running';
		return status;
	});
	const indicatorShellClass =
		'inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors';
	const mutedIndicatorClass = `${indicatorShellClass} border-border-strong bg-surface/50 text-foreground/90`;
	const runningIndicatorClass = `${indicatorShellClass} border-accent/35 bg-accent/15 text-accent`;
</script>

<div
	class="my-0.5"
	data-testid="delegate-group"
	data-delegate-call-id={delegateCall.callId}
	data-delegate-status={delegateCall.status}
>
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="group flex items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-surface -mx-1.5 cursor-pointer"
		onclick={toggle}
		data-testid="delegate-group-toggle"
	>
		<div class="relative flex h-5 w-5 shrink-0 items-center justify-center">
			{#if showConnectorAbove}
				<span
					class="delegate-connector pointer-events-none absolute -top-5 left-1/2 h-5 -translate-x-1/2 text-foreground/60"
					data-testid="delegate-group-connector-above"
				></span>
			{/if}

			{#if indicatorStatus === 'success'}
				<span class={mutedIndicatorClass}>
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
						data-testid="delegate-group-complete"
					>
						<path d="m5 12 4 4 10-10" />
					</svg>
				</span>
			{:else if indicatorStatus === 'error'}
				<span class={mutedIndicatorClass}>
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
						data-testid="delegate-group-error"
					>
						<path d="m5 12 4 4 10-10" />
					</svg>
				</span>
			{:else}
				<span class={runningIndicatorClass}>
					<span
						class="h-2.5 w-2.5 animate-spin rounded-full border-2 border-current border-t-transparent"
						data-testid="delegate-group-running"
					></span>
				</span>
			{/if}

			{#if showConnectorBelow}
				<span
					class="delegate-connector pointer-events-none absolute -bottom-5 left-1/2 h-5 -translate-x-1/2 text-foreground/60"
					data-testid="delegate-group-connector-below"
				></span>
			{/if}
		</div>

		<span class="flex-1 truncate text-[14px] leading-tight text-foreground/90">{delegateLabel}</span
		>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="12"
			height="12"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
			class="shrink-0 text-muted transition-transform duration-150 {expanded ? 'rotate-180' : ''}"
		>
			<path d="m6 9 6 6 6-6" />
		</svg>
	</div>

	{#if expanded}
		<div class="ml-6 pl-1 pt-0.5" data-testid="delegate-group-content">
			{#each items as item, idx (`delegate-item-${idx}`)}
				{#if item.type === 'tool_call' && item.status !== 'error'}
					<ToolCallMessageRow
						message={item}
						onClick={onToolCallClick ? () => onToolCallClick(item.callId) : undefined}
						muted={true}
						hideMessageHeader={item.toolName === 'message' && hasVisibleMessageBody(item)}
					/>
				{:else if item.type === 'assistant'}
					<AgentMessage
						message={item as TextMessage}
						startedByName={isMultiParticipant ? item.started_by_name : undefined}
						muted={true}
					/>
				{:else if item.type === 'reasoning'}
					<p class="my-1 px-1 text-[14px] text-foreground/70">{item.text}</p>
				{/if}
			{/each}
		</div>
	{/if}
</div>

<style>
	.delegate-connector {
		width: 1px;
		background-image: repeating-linear-gradient(to bottom, currentColor 0 1px, transparent 1px 2px);
	}
</style>
