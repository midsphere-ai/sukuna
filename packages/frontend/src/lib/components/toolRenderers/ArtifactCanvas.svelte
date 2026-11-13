<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { renderMarkdown } from '$lib/utils/markdown';
	import { parseEnvelope } from './_shared';
	import PdfArtifactViewer from './PdfArtifactViewer.svelte';

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
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'create'
	);
	let artifactType = $derived(
		typeof resultObj.artifact_type === 'string'
			? (resultObj.artifact_type as string)
			: typeof toolCall.args?.artifact_type === 'string'
				? (toolCall.args.artifact_type as string)
				: 'code'
	);
	let title = $derived(
		typeof resultObj.title === 'string'
			? (resultObj.title as string)
			: typeof toolCall.args?.title === 'string'
				? (toolCall.args.title as string)
				: 'Untitled'
	);
	let artifactId = $derived(
		typeof resultObj.artifact_id === 'string' ? (resultObj.artifact_id as string) : ''
	);
	let language = $derived(
		typeof resultObj.language === 'string'
			? (resultObj.language as string)
			: typeof toolCall.args?.language === 'string'
				? (toolCall.args.language as string)
				: ''
	);
	let content = $derived(
		typeof resultObj.content === 'string'
			? (resultObj.content as string)
			: typeof toolCall.args?.content === 'string'
				? (toolCall.args.content as string)
				: ''
	);

	const TYPE_LABELS: Record<string, string> = {
		html: 'html',
		markdown: 'markdown',
		svg: 'svg',
		code: 'code',
		mermaid: 'mermaid',
		pdf: 'pdf'
	};

	let copied = $state(false);
	function copyContent(): void {
		if (!content) return;
		navigator.clipboard.writeText(content).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}

	function wrapHtmlContent(html: string): string {
		const trimmed = html.trim().toLowerCase();
		if (trimmed.startsWith('<!doctype') || trimmed.startsWith('<html')) return html;
		return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:16px;font-family:system-ui,sans-serif;}</style></head><body>${html}</body></html>`;
	}

	let renderedMarkdown = $derived(
		artifactType === 'markdown' && content ? renderMarkdown(content) : ''
	);
</script>

<div class="h-full p-2" data-testid="artifact-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="artifact-canvas"
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
					<path
						d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"
					/>
					<path d="M7 7h.01" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					artifact · {action}
				</span>
				<span
					class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
					data-testid="artifact-canvas-type"
				>
					{TYPE_LABELS[artifactType] ?? artifactType}
				</span>
				{#if title}
					<span
						class="truncate text-[11px] text-foreground"
						{title}
						data-testid="artifact-canvas-title"
					>
						{title}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if artifactId}
					<span
						class="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-subtle"
						data-testid="artifact-canvas-id"
					>
						{artifactId}
					</span>
				{/if}
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="artifact-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						rendering
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

				<button
					onclick={copyContent}
					disabled={!content}
					class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
					title="Copy source"
					aria-label="Copy source"
					data-testid="artifact-canvas-copy"
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
		<div class="min-h-0 flex-1 overflow-hidden bg-background" data-testid="artifact-canvas-body">
			{#if isRunning && !content}
				<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Rendering artifact…
				</div>
			{:else if isError}
				<div class="p-4">
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
			{:else if artifactType === 'html'}
				<iframe
					srcdoc={wrapHtmlContent(content)}
					title="Artifact: {title}"
					class="h-full w-full border-0 bg-background"
					sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
					data-testid="artifact-canvas-html"
				></iframe>
			{:else if artifactType === 'svg'}
				<div
					class="flex h-full items-center justify-center overflow-auto p-4"
					data-testid="artifact-canvas-svg"
				>
					<!-- eslint-disable-next-line svelte/no-at-html-tags -->
					{@html content}
				</div>
			{:else if artifactType === 'markdown'}
				<div class="h-full overflow-auto p-4" data-testid="artifact-canvas-markdown">
					<div
						class="prose prose-sm max-w-none text-foreground
							[&_h1]:text-[18px] [&_h1]:font-medium [&_h1]:text-foreground [&_h1]:mt-0
							[&_h2]:text-[16px] [&_h2]:font-medium [&_h2]:text-foreground
							[&_h3]:text-[14px] [&_h3]:font-medium [&_h3]:text-foreground
							[&_p]:text-[13px] [&_p]:leading-relaxed
							[&_code]:rounded [&_code]:bg-surface [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[12px]
							[&_pre]:rounded [&_pre]:bg-surface [&_pre]:p-3 [&_pre]:text-[12px]
							[&_a]:text-accent [&_a]:underline
							[&_blockquote]:border-l-2 [&_blockquote]:border-border-subtle [&_blockquote]:pl-3 [&_blockquote]:text-muted
							[&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5"
					>
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html renderedMarkdown}
					</div>
				</div>
			{:else if artifactType === 'code'}
				<div class="h-full overflow-auto" data-testid="artifact-canvas-code">
					{#if language}
						<div
							class="sticky top-0 z-10 flex justify-end border-b border-border-subtle bg-surface px-3 py-1"
						>
							<span class="font-mono text-[10px] text-muted">{language}</span>
						</div>
					{/if}
					<pre
						class="p-4 font-mono text-[12px] leading-relaxed whitespace-pre-wrap break-all text-foreground">{content}</pre>
				</div>
			{:else if artifactType === 'mermaid'}
				<div class="h-full overflow-auto p-4" data-testid="artifact-canvas-mermaid">
					<div class="mb-2 font-mono text-[10px] uppercase tracking-wide text-subtle">
						mermaid source
					</div>
					<pre
						class="rounded border border-border-subtle bg-surface p-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap break-all text-foreground">{content}</pre>
				</div>
			{:else if artifactType === 'pdf'}
				<div class="h-full" data-testid="artifact-canvas-pdf">
					<PdfArtifactViewer {content} {title} />
				</div>
			{:else}
				<div class="h-full overflow-auto p-4">
					<pre
						class="font-mono text-[12px] whitespace-pre-wrap break-all text-muted">{content}</pre>
				</div>
			{/if}
		</div>
	</div>
</div>
