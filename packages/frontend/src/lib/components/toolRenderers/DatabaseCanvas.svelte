<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let action = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'query'
	);
	let query = $derived(
		typeof toolCall.args?.query === 'string' ? (toolCall.args.query as string) : ''
	);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let columns: string[] = $derived(
		Array.isArray(resultObj.columns) ? (resultObj.columns as string[]) : []
	);
	let rows: unknown[][] = $derived.by(() => {
		if (!Array.isArray(resultObj.rows)) return [];
		return (resultObj.rows as unknown[]).map((r) => {
			if (Array.isArray(r)) return r as unknown[];
			if (r && typeof r === 'object') {
				const obj = r as Record<string, unknown>;
				return columns.length > 0 ? columns.map((c) => obj[c]) : Object.values(obj);
			}
			return [r];
		});
	});
	let count = $derived(
		typeof resultObj.count === 'number' ? (resultObj.count as number) : rows.length
	);

	function fmtCell(v: unknown): string {
		if (v == null) return '';
		if (typeof v === 'string') return v;
		try {
			return JSON.stringify(v);
		} catch {
			return String(v);
		}
	}
</script>

<div class="h-full p-2" data-testid="database-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="database-canvas"
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
					<ellipse cx="12" cy="5" rx="9" ry="3" />
					<path d="M3 5v14a9 3 0 0 0 18 0V5" />
					<path d="M3 12a9 3 0 0 0 18 0" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					database · {action}
				</span>
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="database-canvas-running"
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
						data-testid="database-canvas-error-badge"
					>
						error
					</span>
				{:else}
					<span
						class="rounded bg-success/15 px-2 py-0.5 font-mono text-[11px] text-success"
						data-testid="database-canvas-count"
					>
						{count}
						{count === 1 ? 'row' : 'rows'}
					</span>
				{/if}
			</div>
		</div>

		<!-- Query -->
		{#if query}
			<div
				class="shrink-0 border-b border-border-subtle bg-surface px-3 py-2 font-mono text-[11px] text-foreground"
				data-testid="database-canvas-query"
			>
				<span class="select-none text-accent">sql&gt;</span>
				<span class="ml-2 whitespace-pre-wrap break-all">{query}</span>
			</div>
		{/if}

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background" data-testid="database-canvas-body">
			{#if isError}
				<div class="p-3">
					<div
						class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
						data-testid="database-canvas-error"
					>
						<div class="font-mono text-[10px] font-medium uppercase tracking-wide text-accent">
							{envelope.error ?? 'query failed'}
						</div>
						{#if envelope.message}
							<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
						{/if}
						{#if envelope.hint}
							<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
						{/if}
					</div>
				</div>
			{:else if isRunning && rows.length === 0}
				<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Executing query…
				</div>
			{:else if count === 0 || rows.length === 0}
				<div class="flex h-full items-center justify-center text-[12px] italic text-subtle">
					No rows returned
				</div>
			{:else}
				<table class="w-full border-collapse font-mono text-[11px]">
					<thead class="sticky top-0 bg-surface">
						<tr>
							{#each columns as col (col)}
								<th
									class="border-b border-border-strong px-3 py-1.5 text-left font-medium uppercase tracking-wide text-muted"
									data-testid="database-canvas-header"
								>
									{col}
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each rows as row, i (i)}
							<tr class="odd:bg-background even:bg-surface-2" data-testid="database-canvas-row">
								{#each row as cell, j (j)}
									<td class="border-b border-border-subtle px-3 py-1.5 align-top text-foreground">
										{fmtCell(cell)}
									</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	</div>
</div>
