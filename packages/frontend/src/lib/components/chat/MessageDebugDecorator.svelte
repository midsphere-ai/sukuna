<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { Message } from '$services/sse';
	import { tokenUsage } from '$services/sse';
	import { toasts } from '$stores/toast';
	import JsonViewer from '$components/debug/JsonViewer.svelte';

	type Props = {
		message: Message;
		index: number;
	};

	let { message, index }: Props = $props();
	let open = $state(false);

	let tokens = $state({ inputTokens: 0, outputTokens: 0, totalTokens: 0, model: '' });
	const unsubTokens = tokenUsage.subscribe((v) => (tokens = v));
	onDestroy(unsubTokens);

	let typeLabel = $derived(message.type);
	let typeClass = $derived.by(() => {
		switch (message.type) {
			case 'user':
				return 'bg-accent/15 text-accent';
			case 'assistant':
				return 'bg-success/15 text-success';
			case 'tool_call':
				return 'bg-accent/15 text-accent';
			case 'reasoning':
				return 'bg-amber-500/15 text-amber-700';
			case 'step':
				return 'bg-subtle/20 text-subtle';
			case 'error':
				return 'bg-accent/25 text-accent';
			case 'hitl':
				return 'bg-accent/25 text-accent';
			case 'mcp_progress':
				return 'bg-amber-500/10 text-amber-700';
			default:
				return 'bg-surface-2 text-subtle';
		}
	});

	let summaryText = $derived.by(() => {
		switch (message.type) {
			case 'user':
				return truncate(message.text, 60);
			case 'assistant':
				return `${truncate(message.text, 60)}${message.isStreaming ? ' · streaming' : ''}`;
			case 'tool_call':
				return `${message.toolName} · ${message.status}${
					typeof message.durationMs === 'number' ? ` · ${message.durationMs}ms` : ''
				}`;
			case 'reasoning':
				return truncate(message.text, 60);
			case 'step':
				return `step ${message.stepNumber}${message.maxSteps ? `/${message.maxSteps}` : ''} · ${
					message.status
				}${typeof message.durationMs === 'number' ? ` · ${message.durationMs}ms` : ''}`;
			case 'error':
				return truncate(message.message, 60);
			case 'hitl':
				return `${message.requestId} · ${truncate(message.prompt, 40)}`;
			case 'mcp_progress':
				return `${message.toolName} · ${message.progress}/${message.total}`;
			default:
				return '';
		}
	});

	let sourceAgent = $derived.by(() => {
		if (
			message.type === 'assistant' ||
			message.type === 'tool_call' ||
			message.type === 'reasoning'
		) {
			return message.source_agent;
		}
		return undefined;
	});

	function truncate(s: string | undefined, n: number): string {
		if (!s) return '';
		return s.length > n ? s.slice(0, n) + '…' : s;
	}

	async function copyJson(): Promise<void> {
		try {
			await navigator.clipboard.writeText(JSON.stringify(message, null, 2));
			toasts.success('Message copied as JSON');
		} catch {
			toasts.error('Failed to copy');
		}
	}
</script>

<div
	class="mx-auto my-0.5 w-full max-w-3xl rounded-md border border-border-subtle bg-surface-2/40 px-2 py-1 font-mono text-[10.5px] text-subtle"
	data-debug-index={index}
>
	<button
		type="button"
		onclick={() => (open = !open)}
		class="flex w-full items-center gap-2 text-left"
	>
		<span class="text-[9px]">{open ? '▾' : '▸'}</span>
		<span class="rounded px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide {typeClass}"
			>{typeLabel}</span
		>
		{#if sourceAgent}
			<span class="rounded bg-surface-2 px-1.5 py-0.5 text-[9.5px] text-muted">{sourceAgent}</span>
		{/if}
		<span class="truncate text-foreground/80">{summaryText}</span>
		<span class="ml-auto text-[9.5px] text-muted">#{index}</span>
	</button>

	{#if open}
		<div class="mt-1.5 space-y-1.5 border-t border-border-subtle pt-1.5">
			{#if message.type === 'assistant'}
				<div class="flex flex-wrap gap-x-3 gap-y-0.5">
					<span><span class="text-muted">model:</span> {tokens.model || '—'}</span>
					<span><span class="text-muted">streaming:</span> {message.isStreaming}</span>
					{#if message.started_by_name}
						<span><span class="text-muted">started_by:</span> {message.started_by_name}</span>
					{/if}
				</div>
				<div>
					<div class="mb-0.5 text-muted">raw text ({message.text.length} chars):</div>
					<pre
						class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-1.5 text-[11px] text-foreground">{message.text}</pre>
				</div>
				{#if message.metadata}
					<div>
						<div class="mb-0.5 text-muted">metadata:</div>
						<JsonViewer value={message.metadata} collapseDepth={2} />
					</div>
				{/if}
			{:else if message.type === 'user'}
				<div class="flex flex-wrap gap-x-3 gap-y-0.5">
					<span><span class="text-muted">optimistic:</span> {String(!!message.optimistic)}</span>
					{#if message.clientId}
						<span><span class="text-muted">clientId:</span> {message.clientId}</span>
					{/if}
					{#if message.sender_id}
						<span
							><span class="text-muted">sender:</span>
							{message.sender_name ?? message.sender_id}</span
						>
					{/if}
					{#if message.created_at}
						<span><span class="text-muted">created:</span> {message.created_at}</span>
					{/if}
				</div>
				<div>
					<div class="mb-0.5 text-muted">text ({message.text.length} chars):</div>
					<pre
						class="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-1.5 text-[11px] text-foreground">{message.text}</pre>
				</div>
				{#if message.files?.length}
					<div>
						<div class="mb-0.5 text-muted">files:</div>
						<JsonViewer value={message.files} />
					</div>
				{/if}
			{:else if message.type === 'tool_call'}
				<div class="flex flex-wrap gap-x-3 gap-y-0.5">
					<span><span class="text-muted">tool:</span> {message.toolName}</span>
					<span><span class="text-muted">status:</span> {message.status}</span>
					<span><span class="text-muted">callId:</span> {truncate(message.callId, 24)}</span>
					{#if typeof message.durationMs === 'number'}
						<span><span class="text-muted">duration:</span> {message.durationMs}ms</span>
					{/if}
					{#if message.phaseId}
						<span><span class="text-muted">phase:</span> {message.phaseId}</span>
					{/if}
				</div>
				<div>
					<div class="mb-0.5 text-muted">args:</div>
					<JsonViewer value={message.args} collapseDepth={2} />
				</div>
				{#if typeof message.result !== 'undefined'}
					<div>
						<div class="mb-0.5 text-muted">result:</div>
						<JsonViewer value={message.result} collapseDepth={1} />
					</div>
				{/if}
				{#if message.error}
					<div>
						<div class="mb-0.5 text-muted">error:</div>
						<pre
							class="whitespace-pre-wrap break-words rounded bg-accent/10 p-1.5 text-[11px] text-accent">{message.error}</pre>
					</div>
				{/if}
			{:else if message.type === 'reasoning'}
				<div>
					<div class="mb-0.5 text-muted">reasoning ({message.text.length} chars):</div>
					<pre
						class="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-background p-1.5 text-[11px] text-foreground">{message.text}</pre>
				</div>
			{:else if message.type === 'step'}
				<div class="flex flex-wrap gap-x-3 gap-y-0.5">
					<span><span class="text-muted">step:</span> {message.stepNumber}</span>
					<span><span class="text-muted">status:</span> {message.status}</span>
					{#if message.maxSteps}
						<span><span class="text-muted">max:</span> {message.maxSteps}</span>
					{/if}
					{#if typeof message.durationMs === 'number'}
						<span><span class="text-muted">duration:</span> {message.durationMs}ms</span>
					{/if}
				</div>
			{:else if message.type === 'hitl'}
				<div>
					<span class="text-muted">requestId:</span>
					{message.requestId}
				</div>
				<div>
					<div class="mb-0.5 text-muted">prompt:</div>
					<pre
						class="whitespace-pre-wrap break-words rounded bg-background p-1.5 text-[11px] text-foreground">{message.prompt}</pre>
				</div>
				{#if message.choices?.length}
					<div>
						<div class="mb-0.5 text-muted">choices:</div>
						<JsonViewer value={message.choices} />
					</div>
				{/if}
				{#if message.response}
					<div>
						<span class="text-muted">response:</span>
						<span class="text-foreground">{message.response}</span>
					</div>
				{/if}
			{:else if message.type === 'error'}
				<div>
					<div class="mb-0.5 text-muted">message:</div>
					<pre
						class="whitespace-pre-wrap break-words rounded bg-accent/10 p-1.5 text-[11px] text-accent">{message.message}</pre>
				</div>
			{:else if message.type === 'mcp_progress'}
				<div class="flex flex-wrap gap-x-3 gap-y-0.5">
					<span><span class="text-muted">tool:</span> {message.toolName}</span>
					<span><span class="text-muted">progress:</span> {message.progress}/{message.total}</span>
					{#if message.message}
						<span><span class="text-muted">message:</span> {message.message}</span>
					{/if}
				</div>
			{/if}

			<div class="flex items-center gap-2 pt-1">
				<button
					type="button"
					onclick={copyJson}
					class="rounded border border-border-subtle bg-background px-2 py-0.5 text-[10px] text-foreground hover:bg-surface-2"
				>
					Copy as JSON
				</button>
			</div>
		</div>
	{/if}
</div>
