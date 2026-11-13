<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { renderMarkdown } from '$lib/utils/markdown';
	import { parseEnvelope } from './_shared';

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

	let toolName = $derived(toolCall.toolName ?? '');
	let action = $derived(toolName.replace(/^km_/, ''));

	// km_read / km_delete: path arg
	let path = $derived(
		typeof resultObj.path === 'string'
			? (resultObj.path as string)
			: typeof toolCall.args?.path === 'string'
				? (toolCall.args.path as string)
				: ''
	);

	// km_read
	let summary = $derived(
		typeof resultObj.summary === 'string' ? (resultObj.summary as string) : ''
	);
	let raw = $derived(typeof resultObj.raw === 'string' ? (resultObj.raw as string) : '');

	// km_write
	let writeScope = $derived(typeof resultObj.scope === 'string' ? (resultObj.scope as string) : '');
	let writeCategory = $derived(
		typeof resultObj.category === 'string' ? (resultObj.category as string) : ''
	);
	let contentHash = $derived(
		typeof resultObj.content_hash === 'string' ? (resultObj.content_hash as string) : ''
	);
	let indexAction = $derived(
		typeof resultObj.index_action === 'string' ? (resultObj.index_action as string) : ''
	);
	let writeTitle = $derived(
		typeof toolCall.args?.title === 'string' ? (toolCall.args.title as string) : ''
	);

	// km_list
	interface KmItem {
		path: string;
		scope?: string;
		category?: string;
		title?: string;
		rationale?: string;
	}
	let items = $derived(Array.isArray(resultObj.items) ? (resultObj.items as KmItem[]) : []);
	let count = $derived(
		typeof resultObj.count === 'number' ? (resultObj.count as number) : items.length
	);

	// km_delete
	let rowsDeactivated = $derived(
		typeof resultObj.index_rows_deactivated === 'number'
			? (resultObj.index_rows_deactivated as number)
			: undefined
	);

	// km_nudge
	let nudgeTitle = $derived(
		typeof resultObj.title === 'string'
			? (resultObj.title as string)
			: typeof toolCall.args?.title === 'string'
				? (toolCall.args.title as string)
				: ''
	);
	let nudgeTargetRole = $derived(
		typeof resultObj.target_role === 'string'
			? (resultObj.target_role as string)
			: typeof toolCall.args?.target_role === 'string'
				? (toolCall.args.target_role as string)
				: ''
	);
	let nudgeUrgency = $derived(
		typeof resultObj.urgency === 'string'
			? (resultObj.urgency as string)
			: typeof toolCall.args?.urgency === 'string'
				? (toolCall.args.urgency as string)
				: ''
	);
	let nudgeMessage = $derived(
		typeof toolCall.args?.message === 'string' ? (toolCall.args.message as string) : ''
	);

	let expanded = $state<Record<string, boolean>>({});
	function toggleItem(p: string): void {
		expanded[p] = !expanded[p];
	}

	let renderedSummary = $derived(summary ? renderMarkdown(summary) : '');

	let chip = $derived.by(() => {
		if (action === 'read' || action === 'delete') return path;
		if (action === 'write') return writeTitle || path;
		if (action === 'nudge') return nudgeTargetRole;
		return '';
	});
</script>

<div class="h-full p-2" data-testid="km-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="km-canvas"
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
					<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					knowledge manager · {action}
				</span>
				{#if chip}
					<span
						class="truncate rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
						title={chip}
						data-testid="km-canvas-chip"
					>
						{chip}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="km-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						running
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
		<div class="flex-1 overflow-auto bg-background p-4" data-testid="km-canvas-body">
			{#if isRunning}
				<div class="flex items-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Working…
				</div>
			{:else if isError}
				<div
					class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="km-canvas-error"
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
			{:else if action === 'read'}
				<div class="space-y-3" data-testid="km-canvas-read">
					{#if path}
						<div class="font-mono text-[10px] uppercase tracking-wide text-subtle">
							{path}
						</div>
					{/if}
					{#if summary}
						<div
							class="prose prose-sm max-w-none text-foreground
								[&_h1]:text-[16px] [&_h1]:font-medium [&_h1]:text-foreground [&_h1]:mt-0
								[&_h2]:text-[14px] [&_h2]:font-medium [&_h2]:text-foreground
								[&_p]:text-[13px] [&_p]:leading-relaxed
								[&_code]:rounded [&_code]:bg-surface [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[12px]
								[&_pre]:rounded [&_pre]:bg-surface [&_pre]:p-3 [&_pre]:text-[12px]
								[&_a]:text-accent [&_a]:underline
								[&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5"
						>
							<!-- eslint-disable-next-line svelte/no-at-html-tags -->
							{@html renderedSummary}
						</div>
					{:else if raw}
						<pre
							class="rounded border border-border-subtle bg-surface p-3 font-mono text-[12px] whitespace-pre-wrap break-all text-foreground">{raw}</pre>
					{:else}
						<div class="text-[12px] italic text-subtle">No content</div>
					{/if}
				</div>
			{:else if action === 'write'}
				<div
					class="rounded-lg border border-border-subtle bg-surface px-3 py-3"
					data-testid="km-canvas-write"
				>
					<div class="flex items-start gap-3">
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
							class="mt-0.5 shrink-0 text-success"
						>
							<polyline points="20 6 9 17 4 12" />
						</svg>
						<div class="min-w-0 flex-1">
							<div class="text-[13px] font-medium text-foreground">
								KM file {indexAction === 'updated' ? 'updated' : 'written'}
							</div>
							{#if writeTitle}
								<div class="mt-1 text-[12px] text-muted">{writeTitle}</div>
							{/if}
							{#if path}
								<div class="mt-1 font-mono text-[11px] break-all text-subtle">{path}</div>
							{/if}
							<div class="mt-2 flex flex-wrap items-center gap-2">
								{#if writeScope}
									<span
										class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
									>
										scope: {writeScope}
									</span>
								{/if}
								{#if writeCategory}
									<span
										class="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted"
									>
										{writeCategory}
									</span>
								{/if}
								{#if contentHash}
									<span
										class="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-subtle"
									>
										{contentHash.slice(0, 10)}
									</span>
								{/if}
							</div>
						</div>
					</div>
				</div>
			{:else if action === 'list'}
				{#if items.length === 0}
					<div class="text-[12px] italic text-subtle">
						{envelope.message ?? 'No KM files'}
					</div>
				{:else}
					<div class="mb-2 font-mono text-[10px] uppercase tracking-wide text-subtle">
						{count} file{count === 1 ? '' : 's'}
					</div>
					<div class="space-y-1.5" data-testid="km-canvas-list">
						{#each items as item (item.path)}
							<button
								type="button"
								onclick={() => toggleItem(item.path)}
								class="w-full rounded border border-border-subtle bg-surface px-3 py-2 text-left transition-colors hover:bg-surface-2"
							>
								<div class="flex items-center gap-2">
									{#if item.scope}
										<span
											class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
										>
											{item.scope}
										</span>
									{/if}
									{#if item.category}
										<span
											class="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted"
										>
											{item.category}
										</span>
									{/if}
									<span class="min-w-0 flex-1 truncate text-[12px] text-foreground">
										{item.title || item.path}
									</span>
								</div>
								{#if expanded[item.path]}
									<div class="mt-1.5 font-mono text-[10px] break-all text-subtle">
										{item.path}
									</div>
									{#if item.rationale}
										<div class="mt-1 text-[11px] text-muted">{item.rationale}</div>
									{/if}
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			{:else if action === 'delete'}
				<div
					class="rounded-lg border border-border-subtle bg-surface px-3 py-3"
					data-testid="km-canvas-delete"
				>
					<div class="flex items-start gap-3">
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
							<path d="M3 6h18" />
							<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
							<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
						</svg>
						<div class="min-w-0 flex-1">
							<div class="text-[13px] font-medium text-foreground">KM file deleted</div>
							{#if path}
								<div class="mt-1 font-mono text-[11px] break-all text-subtle">{path}</div>
							{/if}
							{#if rowsDeactivated !== undefined}
								<div class="mt-1 font-mono text-[10px] text-subtle">
									{rowsDeactivated} index row{rowsDeactivated === 1 ? '' : 's'} deactivated
								</div>
							{/if}
						</div>
					</div>
				</div>
			{:else if action === 'nudge'}
				<div
					class="rounded-lg border border-accent/30 bg-accent/5 px-3 py-3"
					data-testid="km-canvas-nudge"
				>
					<div class="flex items-start gap-3">
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
							<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
							<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
						</svg>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="text-[13px] font-medium text-foreground">Nudge queued</span>
								{#if nudgeUrgency}
									<span
										class="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted uppercase"
									>
										{nudgeUrgency}
									</span>
								{/if}
								{#if nudgeTargetRole}
									<span
										class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
									>
										→ {nudgeTargetRole}
									</span>
								{/if}
							</div>
							{#if nudgeTitle}
								<div class="mt-1 font-mono text-[11px] text-subtle">{nudgeTitle}</div>
							{/if}
							{#if nudgeMessage}
								<div
									class="mt-2 rounded border border-border-subtle bg-background px-2.5 py-2 text-[12px] text-foreground whitespace-pre-wrap"
								>
									{nudgeMessage}
								</div>
							{/if}
						</div>
					</div>
				</div>
			{:else}
				<div class="text-[12px] italic text-subtle">
					{envelope.message ?? 'KM operation complete'}
				</div>
			{/if}
		</div>
	</div>
</div>
