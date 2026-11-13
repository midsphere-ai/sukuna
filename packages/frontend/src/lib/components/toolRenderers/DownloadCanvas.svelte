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

	let url = $derived(typeof toolCall.args?.url === 'string' ? (toolCall.args.url as string) : '');
	let filePath = $derived(
		(typeof resultObj.file_path === 'string'
			? (resultObj.file_path as string)
			: typeof resultObj.output_path === 'string'
				? (resultObj.output_path as string)
				: typeof toolCall.args?.output_path === 'string'
					? (toolCall.args.output_path as string)
					: typeof toolCall.args?.path === 'string'
						? (toolCall.args.path as string)
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
		if (resultObj.metadata && typeof resultObj.metadata === 'object') {
			const meta = resultObj.metadata as Record<string, unknown>;
			if (typeof meta.size === 'number') return meta.size as number;
			if (typeof meta.content_length === 'number') return meta.content_length as number;
		}
		return undefined;
	});
</script>

<div class="h-full p-2" data-testid="download-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="download-canvas"
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
					<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
					<polyline points="7 10 12 15 17 10" />
					<line x1="12" x2="12" y1="15" y2="3" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					file · download
				</span>
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="download-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						downloading
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
		<div class="flex-1 overflow-auto bg-background p-4" data-testid="download-canvas-body">
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
						<span class="font-medium">
							{#if isRunning}Downloading{:else if isError}Failed to download{:else}Downloaded{/if}
						</span>
						<span class="ml-1 font-mono text-muted" data-testid="download-canvas-name">
							{fileName}
						</span>
					</div>

					{#if filePath && fileName !== filePath}
						<div class="mt-0.5 font-mono text-[11px] break-all text-subtle" title={filePath}>
							{filePath}
						</div>
					{/if}

					{#if url}
						<div
							class="mt-2 flex items-center gap-1.5 font-mono text-[11px] text-subtle"
							data-testid="download-canvas-url"
						>
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
						<div class="mt-1 font-mono text-[11px] text-subtle" data-testid="download-canvas-size">
							{formatBytes(size)}
						</div>
					{/if}

					{#if isRunning}
						<div class="mt-3 h-1 w-full overflow-hidden rounded-full bg-surface">
							<div class="h-full w-1/3 animate-pulse rounded-full bg-accent/60"></div>
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
