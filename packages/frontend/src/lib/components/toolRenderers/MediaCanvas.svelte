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
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : ''
	);
	let prompt = $derived(
		typeof toolCall.args?.prompt === 'string' ? (toolCall.args.prompt as string) : ''
	);
	let aspectRatio = $derived(
		typeof toolCall.args?.aspect_ratio === 'string' ? (toolCall.args.aspect_ratio as string) : ''
	);
	let resolution = $derived(
		typeof toolCall.args?.resolution === 'string' ? (toolCall.args.resolution as string) : ''
	);
	let videoDuration = $derived(
		typeof toolCall.args?.video_duration === 'number'
			? (toolCall.args.video_duration as number)
			: undefined
	);

	let filePath = $derived(
		typeof resultObj.file_path === 'string' ? (resultObj.file_path as string) : ''
	);
	let width = $derived(
		typeof resultObj.width === 'number' ? (resultObj.width as number) : undefined
	);
	let height = $derived(
		typeof resultObj.height === 'number' ? (resultObj.height as number) : undefined
	);
	let duration = $derived(
		typeof resultObj.duration === 'number'
			? (resultObj.duration as number)
			: typeof resultObj.duration_seconds === 'number'
				? (resultObj.duration_seconds as number)
				: undefined
	);

	const IMAGE_EXT = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'svg']);
	const VIDEO_EXT = new Set(['mp4', 'mov', 'webm', 'mkv', 'avi']);
	const AUDIO_EXT = new Set(['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac']);

	let ext = $derived(filePath.split('.').pop()?.toLowerCase() ?? '');
	let kind = $derived(
		IMAGE_EXT.has(ext)
			? 'image'
			: VIDEO_EXT.has(ext)
				? 'video'
				: AUDIO_EXT.has(ext)
					? 'audio'
					: filePath.startsWith('gs://')
						? 'gcs'
						: 'file'
	);
	let fileName = $derived(filePath.split('/').pop() ?? filePath);
	let isGcs = $derived(filePath.startsWith('gs://'));
</script>

<div class="h-full p-2" data-testid="media-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="media-canvas"
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
					<rect width="18" height="14" x="3" y="5" rx="2" ry="2" />
					<path d="m10 10 5 3-5 3z" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					generate{action ? ' · ' + action.replace(/_/g, ' ') : ''}
				</span>
				{#if fileName}
					<span class="truncate font-mono text-[11px] text-foreground" title={filePath}>
						{fileName}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if width && height}
					<span class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent">
						{width}×{height}
					</span>
				{:else if aspectRatio}
					<span class="rounded bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted">
						{aspectRatio}
					</span>
				{/if}
				{#if resolution}
					<span class="rounded bg-surface px-1.5 py-0.5 font-mono text-[10px] text-muted">
						{resolution}
					</span>
				{/if}
				{#if duration !== undefined}
					<span class="rounded bg-success/15 px-1.5 py-0.5 font-mono text-[10px] text-success">
						{duration}s
					</span>
				{:else if videoDuration !== undefined && kind === 'video'}
					<span class="rounded bg-success/15 px-1.5 py-0.5 font-mono text-[10px] text-success">
						{videoDuration}s
					</span>
				{/if}
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="media-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						generating
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div
			class="flex flex-1 flex-col items-center justify-center overflow-auto bg-background p-4"
			data-testid="media-canvas-body"
		>
			{#if isRunning && !filePath}
				<div class="flex items-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Generating media…
				</div>
			{:else if isError}
				<div
					class="w-full max-w-xl rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="media-canvas-error"
				>
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
			{:else if filePath}
				{#if kind === 'image'}
					<img
						src={filePath}
						alt={prompt || fileName}
						class="max-h-full max-w-full rounded-lg border border-border-subtle object-contain shadow-sm"
						data-testid="media-canvas-image"
					/>
				{:else if kind === 'video'}
					<!-- svelte-ignore a11y_media_has_caption -->
					<video
						src={filePath}
						controls
						class="max-h-full max-w-full rounded-lg border border-border-subtle shadow-sm"
						data-testid="media-canvas-video"
					></video>
				{:else if kind === 'audio'}
					<div class="w-full max-w-xl">
						<audio src={filePath} controls class="w-full" data-testid="media-canvas-audio"></audio>
					</div>
				{:else}
					<div
						class="flex items-center gap-3 rounded-lg border border-border-subtle bg-surface px-4 py-3"
						data-testid="media-canvas-file"
					>
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
							class="text-accent"
						>
							<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
							<polyline points="7 10 12 15 17 10" />
							<line x1="12" x2="12" y1="15" y2="3" />
						</svg>
						<div class="min-w-0">
							<div class="truncate text-[13px] font-medium text-foreground">{fileName}</div>
							<div class="truncate font-mono text-[11px] text-muted">
								{isGcs ? filePath : truncatePath(filePath, 4)}
							</div>
						</div>
					</div>
				{/if}
				{#if prompt}
					<p class="mt-3 max-w-xl text-center text-[12px] italic text-muted">"{prompt}"</p>
				{/if}
			{:else if envelope.message}
				<p class="text-[12px] italic text-subtle">{envelope.message}</p>
			{/if}
		</div>
	</div>
</div>
