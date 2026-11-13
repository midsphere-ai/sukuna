<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, truncatePath } from './_shared';

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
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'analyze'
	);
	let source = $derived(
		typeof toolCall.args?.source === 'string' ? (toolCall.args.source as string) : ''
	);
	let sources = $derived(
		Array.isArray(toolCall.args?.sources) ? (toolCall.args.sources as string[]) : []
	);
	let question = $derived(
		typeof toolCall.args?.question === 'string' ? (toolCall.args.question as string) : ''
	);

	// perception result fields (see sandbox/tools/perception/*.py)
	let analysisText = $derived(
		typeof resultObj.result === 'string'
			? (resultObj.result as string)
			: typeof resultObj.answer === 'string'
				? (resultObj.answer as string)
				: typeof resultObj.analysis === 'string'
					? (resultObj.analysis as string)
					: typeof resultObj.content === 'string'
						? (resultObj.content as string)
						: ''
	);
	let framesProcessed = $derived(
		typeof resultObj.frames_processed === 'number'
			? (resultObj.frames_processed as number)
			: undefined
	);
	let saveTo = $derived(
		typeof resultObj.saved_to === 'string' ? (resultObj.saved_to as string) : ''
	);

	const IMAGE_EXT = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg']);
	const VIDEO_EXT = new Set(['mp4', 'mov', 'webm', 'mkv', 'avi']);

	function kindOf(p: string): 'image' | 'video' | 'url' | 'file' {
		if (!p) return 'file';
		if (/^https?:\/\/(www\.)?(youtube\.com|youtu\.be)/i.test(p)) return 'url';
		const ext = p.split('.').pop()?.toLowerCase() ?? '';
		if (IMAGE_EXT.has(ext)) return 'image';
		if (VIDEO_EXT.has(ext)) return 'video';
		return 'file';
	}

	let displaySources = $derived(action === 'compare' && sources.length > 0 ? sources : [source]);

	let copied = $state(false);
	function copyAnalysis(): void {
		if (!analysisText) return;
		navigator.clipboard.writeText(analysisText).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}
</script>

<div class="h-full p-2" data-testid="vision-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="vision-canvas"
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
					<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
					<circle cx="12" cy="12" r="3" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					perception · {action}
				</span>
				{#if source}
					<span class="truncate font-mono text-[11px] text-foreground" title={source}>
						{truncatePath(source, 2)}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if framesProcessed !== undefined}
					<span
						class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
						data-testid="vision-canvas-frames"
					>
						{framesProcessed} frames
					</span>
				{/if}
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="vision-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						analyzing
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{/if}

				<button
					onclick={copyAnalysis}
					disabled={!analysisText}
					class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
					title="Copy analysis"
					aria-label="Copy analysis"
				>
					{#if copied}
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
							class="text-success"
						>
							<polyline points="20 6 9 17 4 12" />
						</svg>
					{:else}
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
						>
							<rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
							<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
						</svg>
					{/if}
				</button>
			</div>
		</div>

		<!-- Body: two-column on wide, stacked on narrow -->
		<div class="flex-1 overflow-auto bg-background" data-testid="vision-canvas-body">
			{#if isRunning && !analysisText}
				<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Analyzing media…
				</div>
			{:else if isError}
				<div class="p-3" data-testid="vision-canvas-error">
					<div class="rounded border border-accent/30 bg-accent/5 px-3 py-2">
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
				</div>
			{:else}
				<div class="flex flex-col gap-3 p-3 lg:flex-row">
					<!-- Source column -->
					<div class="flex w-full flex-col gap-2 lg:w-2/5">
						{#each displaySources as s, i (s || i)}
							{#if s}
								{@const k = kindOf(s)}
								<div
									class="overflow-hidden rounded-lg border border-border-subtle bg-surface"
									data-testid="vision-canvas-source"
								>
									{#if k === 'image'}
										<img src={s} alt="source {i + 1}" class="max-h-64 w-full object-contain" />
									{:else if k === 'video'}
										<!-- svelte-ignore a11y_media_has_caption -->
										<video src={s} controls class="max-h-64 w-full"></video>
									{:else}
										<div class="flex items-center gap-2 px-3 py-2 text-[11px] text-muted">
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
												<circle cx="12" cy="12" r="10" />
												<path d="M2 12h20" />
											</svg>
											<span class="truncate font-mono">{s}</span>
										</div>
									{/if}
									<div
										class="truncate border-t border-border-subtle px-2 py-1 font-mono text-[10px] text-subtle"
									>
										{truncatePath(s, 3)}
									</div>
								</div>
							{/if}
						{/each}
					</div>

					<!-- Analysis column -->
					<div class="flex min-w-0 flex-1 flex-col gap-2">
						{#if question}
							<div
								class="rounded border border-border-subtle bg-surface px-3 py-2 text-[12px] text-muted"
								data-testid="vision-canvas-question"
							>
								<span class="font-mono text-[10px] uppercase tracking-wide text-subtle">Q:</span>
								<span class="ml-1 text-foreground">{question}</span>
							</div>
						{/if}
						{#if analysisText}
							<div
								class="whitespace-pre-wrap rounded border border-border-subtle bg-surface-2 px-3 py-2 text-[12.5px] leading-relaxed text-foreground"
								data-testid="vision-canvas-analysis"
							>
								{analysisText}
							</div>
						{:else}
							<div class="text-[12px] italic text-subtle">
								{envelope.message ?? 'No analysis returned'}
							</div>
						{/if}
						{#if saveTo}
							<div
								class="rounded border border-border-subtle bg-surface px-2.5 py-1.5 text-[10px] text-subtle"
							>
								full output saved to
								<span class="font-mono text-muted">{saveTo}</span>
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>
