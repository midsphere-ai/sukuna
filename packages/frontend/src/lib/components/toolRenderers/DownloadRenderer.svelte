<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, formatBytes } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);
	let isSuccess = $derived(!isRunning && !isError);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let url = $derived(typeof toolCall.args?.url === 'string' ? (toolCall.args.url as string) : '');
	let filePath = $derived(
		(typeof resultObj.file_path === 'string'
			? (resultObj.file_path as string)
			: typeof resultObj.output_path === 'string'
				? (resultObj.output_path as string)
				: typeof toolCall.args?.output_path === 'string'
					? (toolCall.args.output_path as string)
					: '') ?? ''
	);
	let fileName = $derived.by(() => {
		if (filePath) return filePath.split('/').pop() ?? filePath;
		if (url) {
			try {
				const u = new URL(url);
				const parts = u.pathname.split('/').filter(Boolean);
				return parts[parts.length - 1] || u.hostname;
			} catch {
				return url.split('/').pop() ?? url;
			}
		}
		return 'download';
	});

	let size = $derived.by(() => {
		if (typeof resultObj.size === 'number') return resultObj.size as number;
		if (typeof resultObj.bytes_written === 'number') return resultObj.bytes_written as number;
		return undefined;
	});
</script>

<div data-testid="download-renderer">
	<div
		class="flex items-start gap-2.5 rounded-lg border border-border-subtle bg-surface px-3 py-2.5"
		data-testid="download-card"
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
				<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
				<polyline points="7 10 12 15 17 10" />
				<line x1="12" x2="12" y1="15" y2="3" />
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
			<div class="flex items-center gap-1.5 text-xs">
				<span class="text-subtle">
					{#if isRunning}Downloading{:else if isError}Failed{:else}Downloaded{/if}
				</span>
				<span class="truncate font-mono text-foreground" data-testid="download-filename">
					{fileName}
				</span>
				{#if size !== undefined}
					<span class="font-mono text-[10px] text-subtle" data-testid="download-size">
						{formatBytes(size)}
					</span>
				{/if}
			</div>
			{#if url}
				<div
					class="mt-0.5 truncate font-mono text-[10px] text-subtle"
					title={url}
					data-testid="download-url"
				>
					{url}
				</div>
			{/if}
			{#if isError}
				<div class="mt-1 rounded border border-accent/30 bg-accent/5 px-2 py-1">
					<div class="font-mono text-[10px] font-medium uppercase text-accent">
						{envelope.error ?? 'error'}
					</div>
					{#if envelope.message}
						<div class="mt-0.5 text-[11px] text-foreground">{envelope.message}</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
