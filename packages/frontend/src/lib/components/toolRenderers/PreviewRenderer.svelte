<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);
	let port = $derived(
		typeof resultObj.port === 'number'
			? (resultObj.port as number)
			: typeof toolCall.args?.port === 'number'
				? (toolCall.args.port as number)
				: undefined
	);
	let url = $derived(typeof resultObj.url === 'string' ? (resultObj.url as string) : '');
	let label = $derived(
		typeof resultObj.label === 'string'
			? (resultObj.label as string)
			: typeof toolCall.args?.label === 'string'
				? (toolCall.args.label as string)
				: ''
	);
</script>

<div
	class="flex items-center gap-2 rounded-lg border border-border-subtle bg-surface-2 px-2.5 py-1.5"
	data-testid="preview-renderer"
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
		class="shrink-0 text-muted"
	>
		<path d="M2 3h20v14H2z" />
		<path d="M8 21h8" />
		<path d="M12 17v4" />
	</svg>
	<span class="font-mono text-[10px] uppercase tracking-wide text-muted">preview</span>
	{#if port !== undefined}
		<span
			class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
			data-testid="preview-renderer-port"
		>
			:{port}
		</span>
	{/if}
	{#if label}
		<span
			class="min-w-0 truncate font-mono text-[11px] text-foreground"
			title={label}
			data-testid="preview-renderer-label"
		>
			{label}
		</span>
	{/if}
	<div class="ml-auto flex items-center gap-2">
		{#if isRunning}
			<span
				class="flex items-center gap-1 rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted"
			>
				<span class="inline-block size-1.5 animate-pulse rounded-full bg-accent"></span>
				exposing
			</span>
		{:else if isError}
			<span class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] text-accent">error</span
			>
		{:else if url}
			<a
				href={url}
				target="_blank"
				rel="noopener noreferrer"
				class="max-w-[200px] truncate rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-accent underline decoration-border-subtle hover:text-accent"
				title={url}
				data-testid="preview-renderer-url"
			>
				{url}
			</a>
		{/if}
	</div>
</div>
