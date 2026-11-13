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

	let source = $derived(
		typeof toolCall.args?.source === 'string' ? (toolCall.args.source as string) : ''
	);
	let fileName = $derived(source ? (source.split('/').pop() ?? source) : '');
	let isUrl = $derived(/^https?:\/\//i.test(source));

	let transcription = $derived(
		typeof resultObj.transcription === 'string'
			? (resultObj.transcription as string)
			: typeof resultObj.transcript === 'string'
				? (resultObj.transcript as string)
				: typeof resultObj.result === 'string'
					? (resultObj.result as string)
					: ''
	);
	let language = $derived(
		typeof resultObj.language === 'string' ? (resultObj.language as string) : ''
	);
	let duration = $derived(
		typeof resultObj.duration === 'number'
			? (resultObj.duration as number)
			: typeof resultObj.duration_seconds === 'number'
				? (resultObj.duration_seconds as number)
				: undefined
	);

	function fmtDuration(s?: number): string {
		if (s === undefined || !isFinite(s)) return '';
		const m = Math.floor(s / 60);
		const sec = Math.floor(s % 60);
		return `${m}:${sec.toString().padStart(2, '0')}`;
	}

	let copied = $state(false);
	function copyTranscript(): void {
		if (!transcription) return;
		navigator.clipboard.writeText(transcription).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}
</script>

<div class="h-full p-2" data-testid="audio-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="audio-canvas"
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
					<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
					<path d="M19 10v2a7 7 0 0 1-14 0v-2" />
					<line x1="12" x2="12" y1="19" y2="22" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					perception · transcribe
				</span>
				{#if fileName}
					<span class="truncate font-mono text-[11px] text-foreground" title={source}>
						{fileName}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if language}
					<span
						class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] uppercase text-accent"
						data-testid="audio-canvas-language"
					>
						{language}
					</span>
				{/if}
				{#if duration !== undefined}
					<span
						class="rounded bg-success/15 px-1.5 py-0.5 font-mono text-[10px] text-success"
						data-testid="audio-canvas-duration"
					>
						{fmtDuration(duration)}
					</span>
				{/if}
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="audio-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						transcribing
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{/if}

				<button
					onclick={copyTranscript}
					disabled={!transcription}
					class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
					title="Copy transcript"
					aria-label="Copy transcript"
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

		<!-- Body -->
		<div class="flex flex-1 flex-col overflow-hidden bg-background" data-testid="audio-canvas-body">
			<!-- Waveform placeholder + source -->
			{#if source}
				<div
					class="shrink-0 border-b border-border-subtle bg-surface p-3"
					data-testid="audio-canvas-source"
				>
					<div class="flex items-center gap-3">
						<div
							class="flex h-10 flex-1 items-center gap-[2px] overflow-hidden rounded border border-border-subtle bg-background px-2"
							aria-hidden="true"
						>
							{#each Array(48) as _, i (i)}
								{@const h = 20 + ((i * 37) % 70)}
								<span class="inline-block w-[3px] rounded-full bg-accent/40" style="height: {h}%"
								></span>
							{/each}
						</div>
						<div class="min-w-0 max-w-[40%]">
							<div class="truncate text-[12px] font-medium text-foreground">{fileName}</div>
							<div class="truncate font-mono text-[10px] text-subtle">
								{isUrl ? source : truncatePath(source, 3)}
							</div>
						</div>
					</div>
					{#if !isUrl && source}
						<audio src={source} controls class="mt-2 w-full" data-testid="audio-canvas-player"
						></audio>
					{/if}
				</div>
			{/if}

			<!-- Transcription -->
			<div class="flex-1 overflow-auto p-4" data-testid="audio-canvas-transcription">
				{#if isRunning && !transcription}
					<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
						<span
							class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
							aria-hidden="true"
						></span>
						Transcribing audio…
					</div>
				{:else if isError}
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
				{:else if transcription}
					<div class="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground">
						{transcription}
					</div>
				{:else}
					<div class="text-[12px] italic text-subtle">
						{envelope.message ?? 'No transcription returned'}
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
