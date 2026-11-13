<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, formatBytes } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);
	let isError = $derived(envelope.success === false);
	let isSuccess = $derived(!isRunning && !isError);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let action = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : ''
	);
	let filePath = $derived(
		(typeof toolCall.args?.path === 'string'
			? (toolCall.args.path as string)
			: typeof resultObj.file_path === 'string'
				? (resultObj.file_path as string)
				: '') ?? ''
	);
	let fileName = $derived(filePath.split('/').pop() ?? filePath);
	let size = $derived(
		typeof resultObj.size === 'number'
			? (resultObj.size as number)
			: typeof resultObj.bytes_written === 'number'
				? (resultObj.bytes_written as number)
				: undefined
	);

	const ACTION_PAST: Record<string, string> = {
		write: 'Wrote',
		append: 'Appended to',
		download: 'Downloaded',
		delete: 'Deleted',
		move: 'Moved',
		edit: 'Edited'
	};
	const ACTION_PROGRESSIVE: Record<string, string> = {
		write: 'Writing',
		append: 'Appending to',
		download: 'Downloading',
		delete: 'Deleting',
		move: 'Moving',
		edit: 'Editing'
	};
	let label = $derived.by(() => {
		if (isRunning) return (ACTION_PROGRESSIVE[action] ?? 'Running') + '…';
		if (isError) return action ? `Failed to ${action}` : 'Failed';
		return ACTION_PAST[action] ?? 'Completed';
	});
</script>

<div data-testid="file-status-renderer">
	<div
		class="flex items-start gap-2.5 rounded-lg border border-border-subtle bg-surface px-3 py-2.5"
		data-testid="file-status-card"
	>
		{#if isRunning}
			<span
				class="mt-0.5 inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
				aria-hidden="true"
			></span>
		{:else if isSuccess}
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
				class="mt-0.5 shrink-0 text-success"
			>
				<polyline points="20 6 9 17 4 12" />
			</svg>
		{:else}
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
				class="mt-0.5 shrink-0 text-accent"
			>
				<circle cx="12" cy="12" r="10" />
				<line x1="15" x2="9" y1="9" y2="15" />
				<line x1="9" x2="15" y1="9" y2="15" />
			</svg>
		{/if}

		<div class="min-w-0 flex-1">
			<div class="text-xs" data-testid="file-status-action">
				<span class="text-subtle">{label}</span>
				{#if fileName}
					<span class="ml-1 font-mono text-foreground" data-testid="file-status-name"
						>{fileName}</span
					>
				{/if}
				{#if size !== undefined}
					<span class="ml-1.5 font-mono text-[10px] text-subtle">{formatBytes(size)}</span>
				{/if}
			</div>

			{#if envelope.message && !isError}
				<p class="mt-0.5 text-[11px] text-muted" data-testid="file-status-message">
					{envelope.message}
				</p>
			{/if}

			{#if isError}
				<div class="mt-1.5 rounded border border-accent/30 bg-accent/5 px-2 py-1.5">
					<div class="font-mono text-[10px] font-medium uppercase text-accent">
						{envelope.error ?? 'error'}
					</div>
					{#if envelope.message}
						<div class="mt-0.5 text-[11px] text-foreground">{envelope.message}</div>
					{/if}
					{#if envelope.hint}
						<div class="mt-0.5 text-[10px] italic text-muted">hint: {envelope.hint}</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
