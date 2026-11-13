<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface MatchResult {
		edit_index: number;
		match_type: 'exact' | 'fuzzy' | 'failed';
		details?: string;
	}

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);
	let diff = $derived(
		typeof toolCall.result === 'string'
			? (toolCall.result as string)
			: typeof resultObj.diff === 'string'
				? (resultObj.diff as string)
				: ''
	);
	let filePath = $derived(
		(typeof resultObj.file_path === 'string'
			? (resultObj.file_path as string)
			: typeof toolCall.args?.path === 'string'
				? (toolCall.args.path as string)
				: typeof toolCall.args?.file_path === 'string'
					? (toolCall.args.file_path as string)
					: '') ?? ''
	);
	let fileName = $derived(filePath.split('/').pop() ?? filePath);
	let isDryRun = $derived(resultObj.dry_run === true);
	let matchResults = $derived(
		Array.isArray(resultObj.match_results) ? (resultObj.match_results as MatchResult[]) : []
	);

	interface DiffLine {
		type: 'added' | 'removed' | 'context' | 'header';
		content: string;
		oldLineNum?: number;
		newLineNum?: number;
	}

	let diffLines: DiffLine[] = $derived.by(() => {
		if (!diff) return [];
		const out: DiffLine[] = [];
		let oldLine = 0;
		let newLine = 0;
		for (const line of diff.split('\n')) {
			if (line.startsWith('@@')) {
				const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
				if (m) {
					oldLine = parseInt(m[1], 10);
					newLine = parseInt(m[2], 10);
				}
				out.push({ type: 'header', content: line });
			} else if (line.startsWith('---') || line.startsWith('+++')) {
				// skip file headers
			} else if (line.startsWith('+')) {
				out.push({ type: 'added', content: line.slice(1), newLineNum: newLine });
				newLine++;
			} else if (line.startsWith('-')) {
				out.push({ type: 'removed', content: line.slice(1), oldLineNum: oldLine });
				oldLine++;
			} else {
				const content = line.startsWith(' ') ? line.slice(1) : line;
				if (line !== '') {
					out.push({ type: 'context', content, oldLineNum: oldLine, newLineNum: newLine });
					oldLine++;
					newLine++;
				}
			}
		}
		return out;
	});

	let addedCount = $derived(diffLines.filter((l) => l.type === 'added').length);
	let removedCount = $derived(diffLines.filter((l) => l.type === 'removed').length);

	let isLargeDiff = $derived(diffLines.length > 50);
	let expanded = $state(false);
	let visibleLines = $derived(isLargeDiff && !expanded ? diffLines.slice(0, 50) : diffLines);

	let copied = $state(false);
	function copyDiff(): void {
		if (!diff) return;
		navigator.clipboard.writeText(diff).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}

	function matchBadgeClass(matchType: string): string {
		switch (matchType) {
			case 'exact':
				return 'bg-success/15 text-success';
			case 'fuzzy':
				return 'bg-accent/10 text-accent';
			case 'failed':
				return 'bg-accent/15 text-accent';
			default:
				return 'bg-surface text-subtle';
		}
	}
</script>

<div data-testid="diff-renderer">
	<!-- Header -->
	<div class="mb-2 flex items-center justify-between gap-2">
		<div class="flex min-w-0 items-center gap-2 text-xs">
			{#if filePath}
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
						<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
						<path d="M14 2v4a2 2 0 0 0 2 2h4" />
					</svg>
					<span
						class="truncate font-mono text-[11px] text-foreground"
						title={filePath}
						data-testid="diff-file-path"
					>
						{fileName}
					</span>
				</div>
			{/if}

			{#if isDryRun}
				<span
					class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
					data-testid="diff-dry-run"
				>
					dry run
				</span>
			{/if}
		</div>

		<div class="flex shrink-0 items-center gap-2">
			{#if isError}
				<span
					class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-accent"
					data-testid="diff-error-badge"
				>
					error
				</span>
			{:else if addedCount > 0 || removedCount > 0}
				<span class="font-mono text-[10px]" data-testid="diff-stats">
					<span class="text-success">+{addedCount}</span>
					<span class="mx-0.5 text-subtle">/</span>
					<span class="text-accent">-{removedCount}</span>
				</span>
			{/if}

			<button
				onclick={copyDiff}
				class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
				disabled={!diff}
				title="Copy diff"
				aria-label="Copy diff"
				data-testid="diff-copy"
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

	<!-- Match results badges -->
	{#if matchResults.length > 0}
		<div class="mb-2 flex flex-wrap gap-1" data-testid="diff-match-results">
			{#each matchResults as match (match.edit_index)}
				<span
					class="rounded px-1.5 py-0.5 font-mono text-[10px] font-medium {matchBadgeClass(
						match.match_type
					)}"
					title={match.details ?? ''}
					data-testid="diff-match-badge"
				>
					Edit {match.edit_index + 1}: {match.match_type}
				</span>
			{/each}
		</div>
	{/if}

	<!-- Error block -->
	{#if isError}
		<div
			class="mb-2 rounded border border-accent/30 bg-accent/5 px-3 py-2"
			data-testid="diff-error"
		>
			<div class="font-mono text-[10px] font-medium uppercase text-accent">
				{envelope.error ?? 'edit failed'}
			</div>
			{#if envelope.message}
				<div class="mt-1 text-[11px] text-foreground">{envelope.message}</div>
			{/if}
			{#if envelope.hint}
				<div class="mt-1 text-[10px] italic text-muted">hint: {envelope.hint}</div>
			{/if}
		</div>
	{/if}

	<!-- Diff view -->
	{#if diff}
		<div
			class="overflow-hidden rounded-lg border border-border-subtle bg-background"
			data-testid="diff-content"
		>
			<div
				class="max-h-[400px] overflow-auto font-mono text-xs leading-relaxed"
				data-testid="diff-lines"
			>
				{#each visibleLines as line, i (i)}
					{#if line.type === 'header'}
						<div
							class="border-y border-border-subtle bg-surface px-3 py-0.5 text-[10px] text-muted"
							data-testid="diff-hunk-header"
						>
							{line.content}
						</div>
					{:else}
						<div
							class="flex {line.type === 'added'
								? 'bg-success/8'
								: line.type === 'removed'
									? 'bg-accent/8'
									: ''}"
							data-testid="diff-line"
							data-line-type={line.type}
						>
							<span class="w-10 shrink-0 select-none px-1.5 text-right text-[10px] text-subtle">
								{line.type !== 'added' && line.oldLineNum !== undefined ? line.oldLineNum : ''}
							</span>
							<span
								class="w-10 shrink-0 select-none border-r border-border-subtle px-1.5 text-right text-[10px] text-subtle"
							>
								{line.type !== 'removed' && line.newLineNum !== undefined ? line.newLineNum : ''}
							</span>
							<span
								class="w-5 shrink-0 select-none text-center {line.type === 'added'
									? 'text-success'
									: line.type === 'removed'
										? 'text-accent'
										: 'text-transparent'}"
							>
								{line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '}
							</span>
							<span class="min-w-0 flex-1 whitespace-pre-wrap px-1 text-foreground">
								{line.content}
							</span>
						</div>
					{/if}
				{/each}
			</div>

			{#if isLargeDiff && !expanded}
				<button
					onclick={() => (expanded = true)}
					class="flex w-full items-center justify-center gap-1 border-t border-border-subtle bg-surface py-1.5 text-[11px] text-muted transition-colors hover:bg-surface-2 hover:text-accent"
					data-testid="diff-expand"
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
					Show all {diffLines.length} lines
				</button>
			{/if}
		</div>
	{/if}
</div>
