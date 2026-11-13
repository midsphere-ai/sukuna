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
				: '') ?? ''
	);
	let fileName = $derived(filePath.split('/').pop() ?? filePath);
	let isDryRun = $derived(resultObj.dry_run === true);
	let matchResults = $derived(
		Array.isArray(resultObj.match_results) ? (resultObj.match_results as MatchResult[]) : []
	);

	type DiffLine = {
		type: 'add' | 'remove' | 'context' | 'hunk';
		content: string;
		oldNum?: number;
		newNum?: number;
	};

	let parsedLines: DiffLine[] = $derived.by(() => {
		if (!diff) return [];
		const lines: DiffLine[] = [];
		let oldLine = 0;
		let newLine = 0;
		for (const raw of diff.split('\n')) {
			if (raw.startsWith('@@')) {
				const m = raw.match(/@@ -(\d+)(?:,\d+)? \+(\d+)/);
				if (m) {
					oldLine = parseInt(m[1], 10) - 1;
					newLine = parseInt(m[2], 10) - 1;
				}
				lines.push({ type: 'hunk', content: raw });
			} else if (raw.startsWith('---') || raw.startsWith('+++')) {
				// skip file headers
			} else if (raw.startsWith('+')) {
				newLine++;
				lines.push({ type: 'add', content: raw.slice(1), newNum: newLine });
			} else if (raw.startsWith('-')) {
				oldLine++;
				lines.push({ type: 'remove', content: raw.slice(1), oldNum: oldLine });
			} else {
				oldLine++;
				newLine++;
				lines.push({
					type: 'context',
					content: raw.startsWith(' ') ? raw.slice(1) : raw,
					oldNum: oldLine,
					newNum: newLine
				});
			}
		}
		return lines;
	});

	let addCount = $derived(parsedLines.filter((l) => l.type === 'add').length);
	let removeCount = $derived(parsedLines.filter((l) => l.type === 'remove').length);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let copied = $state(false);
	function copyDiff(): void {
		if (!diff) return;
		navigator.clipboard.writeText(diff).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}
</script>

<div class="h-full p-2" data-testid="diff-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="diff-canvas"
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
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide"> file · edit </span>
				{#if fileName}
					<span class="truncate font-mono text-[11px] text-foreground" title={filePath}>
						{fileName}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isDryRun}
					<span class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent">
						dry run
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
						editing
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{:else if addCount > 0 || removeCount > 0}
					<span class="flex items-center gap-2 font-mono text-[11px]">
						<span class="text-success">+{addCount}</span>
						<span class="text-accent">-{removeCount}</span>
					</span>
				{/if}

				<button
					onclick={copyDiff}
					class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
					disabled={!diff}
					title="Copy diff"
					aria-label="Copy diff"
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

		<!-- Content -->
		<div class="flex-1 overflow-auto bg-background" data-testid="diff-canvas-body">
			{#if isRunning && !diff}
				<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Editing…
				</div>
			{:else if matchResults.some((m) => m.match_type === 'failed')}
				<div class="p-3">
					<div class="mb-2 flex flex-wrap gap-1.5">
						{#each matchResults as m (m.edit_index)}
							<span
								class="rounded px-2 py-0.5 font-mono text-[10px] {m.match_type === 'exact'
									? 'bg-success/15 text-success'
									: m.match_type === 'fuzzy'
										? 'bg-accent/10 text-accent'
										: 'bg-accent/15 text-accent'}"
								title={m.details ?? ''}
							>
								edit {m.edit_index + 1}: {m.match_type}
							</span>
						{/each}
					</div>
					{#if isError}
						<div class="rounded border border-accent/30 bg-accent/5 px-3 py-2">
							<div class="font-mono text-[10px] font-medium uppercase text-accent">
								{envelope.error ?? 'edit failed'}
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
			{:else if !diff}
				<div class="flex h-full items-center justify-center text-[12px] italic text-subtle">
					{envelope.message ?? 'No changes'}
				</div>
			{:else}
				<div class="font-mono text-[12px] leading-relaxed">
					{#each parsedLines as line, i (i)}
						{#if line.type === 'hunk'}
							<div
								class="border-y border-border-subtle bg-surface px-3 py-0.5 text-[11px] text-muted"
							>
								{line.content}
							</div>
						{:else}
							<div
								class="flex {line.type === 'add'
									? 'bg-success/8'
									: line.type === 'remove'
										? 'bg-accent/8'
										: ''}"
								data-line-type={line.type}
							>
								<span class="w-10 shrink-0 select-none px-1.5 text-right text-[10px] text-subtle">
									{line.type !== 'add' && line.oldNum !== undefined ? line.oldNum : ''}
								</span>
								<span
									class="w-10 shrink-0 select-none border-r border-border-subtle px-1.5 text-right text-[10px] text-subtle"
								>
									{line.type !== 'remove' && line.newNum !== undefined ? line.newNum : ''}
								</span>
								<span
									class="w-5 shrink-0 select-none text-center {line.type === 'add'
										? 'text-success'
										: line.type === 'remove'
											? 'text-accent'
											: 'text-transparent'}"
								>
									{line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '}
								</span>
								<span class="min-w-0 flex-1 whitespace-pre-wrap break-all px-1 text-foreground">
									{line.content}
								</span>
							</div>
						{/if}
					{/each}
				</div>
			{/if}

			{#if isError && !matchResults.some((m) => m.match_type === 'failed')}
				<div class="border-t border-border-subtle p-3">
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
			{/if}
		</div>
	</div>
</div>
