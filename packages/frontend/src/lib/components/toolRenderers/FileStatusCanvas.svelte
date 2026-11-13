<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, formatBytes } from './_shared';

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
	let url = $derived(typeof toolCall.args?.url === 'string' ? (toolCall.args.url as string) : '');
	let fileName = $derived(filePath.split('/').pop() ?? filePath);

	let size = $derived(
		typeof resultObj.size === 'number'
			? (resultObj.size as number)
			: typeof resultObj.bytes_written === 'number'
				? (resultObj.bytes_written as number)
				: undefined
	);

	const ACTION_PAST_TENSE: Record<string, string> = {
		write: 'Wrote',
		append: 'Appended to',
		download: 'Downloaded',
		delete: 'Deleted',
		move: 'Moved'
	};
	const ACTION_PROGRESSIVE: Record<string, string> = {
		write: 'Writing',
		append: 'Appending to',
		download: 'Downloading',
		delete: 'Deleting',
		move: 'Moving'
	};
	let headline = $derived.by(() => {
		if (isRunning) return (ACTION_PROGRESSIVE[action] ?? 'Running') + '…';
		if (isError) return action ? `Failed to ${action}` : 'Failed';
		return ACTION_PAST_TENSE[action] ?? 'Completed';
	});
</script>

<div class="h-full p-2" data-testid="file-status-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="file-status-canvas"
	>
		<!-- Title bar -->
		<div
			class="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface px-3 py-2"
		>
			<div class="flex min-w-0 flex-1 items-center gap-2 text-muted">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="13"
					height="13"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="shrink-0"
				>
					<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
					<path d="M14 2v4a2 2 0 0 0 2 2h4" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					file{action ? ` · ${action}` : ''}
				</span>
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						running
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{:else}
					<span
						class="rounded bg-success/15 px-2 py-0.5 font-mono text-[11px] font-medium text-success"
					>
						ok
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background p-4">
			<div class="flex items-start gap-3">
				{#if isRunning}
					<span
						class="mt-0.5 inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
				{:else if isError}
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
						class="mt-0.5 shrink-0 text-accent"
					>
						<circle cx="12" cy="12" r="10" />
						<line x1="15" x2="9" y1="9" y2="15" />
						<line x1="9" x2="15" y1="9" y2="15" />
					</svg>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="mt-0.5 shrink-0 text-success"
					>
						<polyline points="20 6 9 17 4 12" />
					</svg>
				{/if}

				<div class="min-w-0 flex-1">
					<div class="text-[13px] text-foreground">
						<span class="font-medium">{headline}</span>
						{#if fileName}
							<span class="ml-1 font-mono text-muted">{fileName}</span>
						{/if}
					</div>

					{#if filePath && fileName !== filePath}
						<div class="mt-0.5 font-mono text-[11px] text-subtle break-all" title={filePath}>
							{filePath}
						</div>
					{/if}

					{#if url}
						<div class="mt-1 flex items-center gap-1.5 font-mono text-[11px] text-subtle">
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
								class="shrink-0"
							>
								<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
								<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
							</svg>
							<span class="truncate">{url}</span>
						</div>
					{/if}

					{#if size !== undefined}
						<div class="mt-1 font-mono text-[11px] text-subtle">
							{formatBytes(size)}
						</div>
					{/if}

					{#if envelope.message && !isError}
						<p class="mt-2 text-[12px] text-muted">{envelope.message}</p>
					{/if}

					{#if isError}
						<div class="mt-3 rounded border border-accent/30 bg-accent/5 px-3 py-2">
							<div class="font-mono text-[10px] font-medium uppercase text-accent">
								{envelope.error ?? 'error'}
							</div>
							{#if envelope.message}
								<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
							{/if}
							{#if envelope.hint}
								<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
</div>
