<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, detectLanguage } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isSkill = $derived(toolCall.toolName === 'skill');

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let fileContent = $derived.by(() => {
		const r = toolCall.result;
		if (typeof r === 'string') return r;
		if (typeof resultObj.content === 'string') return resultObj.content as string;
		if (typeof resultObj.message === 'string') return resultObj.message as string;
		return '';
	});

	let filePath = $derived(
		(typeof toolCall.args?.path === 'string'
			? (toolCall.args.path as string)
			: typeof toolCall.args?.file_path === 'string'
				? (toolCall.args.file_path as string)
				: '') ?? ''
	);
	let skillName = $derived(
		typeof toolCall.args?.name === 'string' ? (toolCall.args.name as string) : ''
	);
	let headerName = $derived(
		isSkill ? skillName || 'skill' : (filePath.split('/').pop() ?? filePath)
	);
	let language = $derived(isSkill ? 'markdown' : detectLanguage(filePath));
	let lines = $derived(fileContent.split('\n'));
	let lineCount = $derived(lines.length);

	let isLargeFile = $derived(lineCount > 100);
	let expanded = $state(false);
	let visibleLines = $derived(isLargeFile && !expanded ? lines.slice(0, 100) : lines);

	let copied = $state(false);
	function copyContent(): void {
		if (!fileContent) return;
		navigator.clipboard.writeText(fileContent).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}
</script>

<div data-testid="code-viewer-renderer">
	<!-- Header -->
	<div class="mb-2 flex items-center justify-between gap-2">
		<div class="flex min-w-0 items-center gap-2 text-xs">
			{#if headerName}
				<div class="flex min-w-0 items-center gap-1.5 text-subtle">
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
					<span
						class="truncate font-mono text-[11px] text-foreground"
						title={filePath || skillName}
						data-testid="code-file-path"
					>
						{headerName}
					</span>
				</div>
			{/if}

			<span
				class="rounded bg-surface px-1.5 py-0.5 font-mono text-[10px] font-medium text-muted"
				data-testid="code-language"
			>
				{language}
			</span>
		</div>

		<div class="flex shrink-0 items-center gap-2">
			{#if isError}
				<span
					class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-accent"
					data-testid="code-error-badge"
				>
					error
				</span>
			{:else}
				<span class="font-mono text-[10px] text-subtle" data-testid="code-line-count">
					{lineCount}
					{lineCount === 1 ? 'line' : 'lines'}
				</span>
			{/if}

			<button
				onclick={copyContent}
				class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
				disabled={!fileContent}
				title="Copy file content"
				data-testid="code-copy"
			>
				{#if copied}
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
						class="text-success"
					>
						<polyline points="20 6 9 17 4 12" />
					</svg>
				{:else}
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
					>
						<rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
						<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
					</svg>
				{/if}
			</button>
		</div>
	</div>

	{#if isError}
		<div class="rounded-lg border border-accent/30 bg-accent/5 px-3 py-2" data-testid="code-error">
			<div class="font-mono text-[10px] font-medium uppercase text-accent">
				{envelope.error ?? 'error'}
			</div>
			{#if envelope.message}
				<div class="mt-1 text-[11px] text-foreground">{envelope.message}</div>
			{/if}
			{#if envelope.hint}
				<div class="mt-1 text-[10px] italic text-muted">hint: {envelope.hint}</div>
			{/if}
		</div>
	{:else}
		<div class="overflow-hidden rounded-lg border border-border-subtle" data-testid="code-content">
			<div
				class="max-h-[400px] overflow-auto bg-background font-mono text-xs leading-relaxed"
				data-testid="code-lines"
			>
				{#each visibleLines as line, i (i)}
					<div class="flex hover:bg-surface-2" data-testid="code-line">
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
			</div>

			{#if isLargeFile && !expanded}
				<button
					onclick={() => (expanded = true)}
					class="flex w-full items-center justify-center gap-1 border-t border-border-subtle bg-surface py-1.5 text-[11px] text-muted transition-colors hover:bg-surface-2 hover:text-accent"
					data-testid="code-expand"
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
					>
						<path d="m6 9 6 6 6-6" />
					</svg>
					Show all {lineCount} lines
				</button>
			{/if}
		</div>
	{/if}
</div>
