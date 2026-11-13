<script lang="ts">
	import { onDestroy } from 'svelte';
	import { debugBus, type DebugEvent } from '$stores/debugBus';
	import JsonViewer from '../JsonViewer.svelte';

	let events: DebugEvent[] = $state([]);
	const unsubBus = debugBus.subscribe((v) => (events = v));
	onDestroy(unsubBus);

	let guardEvents = $derived(events.filter((e) => e.type === 'guard_violation'));
	let mcpErrors = $derived(events.filter((e) => e.type === 'mcp_error'));
	let errorEvents = $derived(events.filter((e) => e.type === 'error' || e.type === 'run_failed'));

	function formatTime(ms: number): string {
		return new Date(ms).toLocaleTimeString();
	}
</script>

<div class="flex flex-col gap-3 p-3 text-[11.5px]">
	<section class="grid grid-cols-3 gap-2">
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Guard violations</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">{guardEvents.length}</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">MCP errors</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">{mcpErrors.length}</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Errors</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">{errorEvents.length}</div>
		</div>
	</section>

	{#if guardEvents.length === 0 && mcpErrors.length === 0}
		<div
			class="rounded border border-dashed border-border-subtle bg-background/60 p-2 text-[11px] text-muted"
		>
			No guard or MCP error events observed. Structured guard violations and MCP connection errors
			require Phase 2 sandbox emissions from
			<code class="font-mono">agent_server/infra/guards.py</code>.
		</div>
	{/if}

	{#if guardEvents.length > 0}
		<section class="rounded border border-border-subtle bg-background p-2">
			<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Guard violations</div>
			<ul class="space-y-1.5">
				{#each guardEvents as e, i (i)}
					<li class="rounded border border-accent/30 bg-accent/5 p-1.5 font-mono text-[10.5px]">
						<div class="flex items-center gap-2">
							<span class="text-muted">{formatTime(e.at)}</span>
							<span class="text-subtle">#{e.seq}</span>
							<span class="font-medium text-accent">{String(e.payload.rail_name ?? 'unknown')}</span
							>
							<span class="rounded bg-accent/10 px-1.5 text-accent"
								>{String(e.payload.action ?? '')}</span
							>
						</div>
						<div class="mt-1">
							<JsonViewer value={e.payload} collapseDepth={2} />
						</div>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if mcpErrors.length > 0}
		<section class="rounded border border-border-subtle bg-background p-2">
			<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">MCP errors</div>
			<ul class="space-y-1.5">
				{#each mcpErrors as e, i (i)}
					<li
						class="rounded border border-amber-500/30 bg-amber-500/5 p-1.5 font-mono text-[10.5px]"
					>
						<div class="flex items-center gap-2">
							<span class="text-muted">{formatTime(e.at)}</span>
							<span class="text-subtle">#{e.seq}</span>
							<span class="text-amber-700">{String(e.payload.server_name ?? 'unknown')}</span>
						</div>
						<div class="mt-1">
							<JsonViewer value={e.payload} collapseDepth={2} />
						</div>
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if errorEvents.length > 0}
		<section class="rounded border border-border-subtle bg-background p-2">
			<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Errors</div>
			<ul class="space-y-0.5 font-mono text-[10.5px]">
				{#each errorEvents as e, i (i)}
					<li class="flex gap-2 border-t border-border-subtle pt-0.5 first:border-t-0">
						<span class="w-[72px] shrink-0 text-muted">{formatTime(e.at)}</span>
						<span class="w-[40px] shrink-0 text-subtle">#{e.seq}</span>
						<span class="min-w-0 flex-1 break-words text-accent">
							{String(e.payload.message ?? e.payload.error ?? JSON.stringify(e.payload)).slice(
								0,
								200
							)}
						</span>
					</li>
				{/each}
			</ul>
		</section>
	{/if}
</div>
