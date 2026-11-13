<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, detectLanguage } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);
	let isSkill = $derived(toolCall.toolName === 'skill');

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	// The `file` tool's `read` action returns the raw string content directly.
	// The `skill` tool's `get` action returns a dict with `name` and `content`.
	// Some code paths wrap text into `{ message, content }`.
	let content = $derived.by(() => {
		const r = toolCall.result;
		if (typeof r === 'string') return r;
		if (typeof resultObj.content === 'string') return resultObj.content as string;
		if (typeof resultObj.message === 'string') return resultObj.message as string;
		return '';
	});

	let filePath = $derived(
		(typeof toolCall.args?.path === 'string'
			? (toolCall.args.path as string)
			: typeof resultObj.file_path === 'string'
				? (resultObj.file_path as string)
				: '') ?? ''
	);
	let skillName = $derived(
		typeof toolCall.args?.name === 'string' ? (toolCall.args.name as string) : ''
	);
	let headerName = $derived(
		isSkill ? skillName || 'skill' : (filePath.split('/').pop() ?? filePath ?? 'file')
	);
	let language = $derived(isSkill ? 'markdown' : detectLanguage(filePath));
	let lines = $derived(content ? content.split('\n') : []);

	let copied = $state(false);
	function copyContent(): void {
		if (!content) return;
		navigator.clipboard.writeText(content).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}
</script>

<div class="h-full p-2" data-testid="code-viewer-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="code-viewer-canvas"
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
					{#if isSkill}
						<path d="M12 2 2 7l10 5 10-5-10-5Z" />
						<path d="m2 17 10 5 10-5" />
						<path d="m2 12 10 5 10-5" />
					{:else}
						<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
						<path d="M14 2v4a2 2 0 0 0 2 2h4" />
					{/if}
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					{isSkill ? 'skill · get' : 'file · read'}
				</span>
				<span class="truncate font-mono text-[11px] text-foreground" title={filePath || skillName}>
					{headerName}
				</span>
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if language && !isSkill}
					<span class="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted">
						{language}
					</span>
				{/if}
				{#if lines.length > 0 && !isRunning}
					<span class="font-mono text-[10px] text-subtle">
						{lines.length}
						{lines.length === 1 ? 'line' : 'lines'}
					</span>
				{/if}
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						reading
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{/if}
				<button
					onclick={copyContent}
					class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
					disabled={!content}
					title="Copy content"
					aria-label="Copy content"
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
		<div class="flex-1 overflow-auto bg-background font-mono text-[13px] leading-relaxed">
			{#if isRunning && !content}
				<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					{isSkill ? 'Loading skill…' : 'Reading file…'}
				</div>
			{:else if isError}
				<div class="p-3">
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
			{:else if !content}
				<div class="flex h-full items-center justify-center text-[12px] italic text-subtle">
					Empty file
				</div>
			{:else}
				{#each lines as line, i (i)}
					<div class="flex hover:bg-surface-2">
						<span
							class="w-12 shrink-0 select-none border-r border-border-subtle px-2 text-right text-[10px] text-subtle"
						>
							{i + 1}
						</span>
						<span class="min-w-0 flex-1 whitespace-pre-wrap px-3 py-px text-foreground">
							{line}
						</span>
					</div>
				{/each}
			{/if}
		</div>
	</div>
</div>
