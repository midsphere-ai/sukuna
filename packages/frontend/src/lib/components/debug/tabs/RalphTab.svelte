<script lang="ts">
	import { onDestroy } from 'svelte';
	import { debugBus, type DebugEvent } from '$stores/debugBus';
	import JsonViewer from '../JsonViewer.svelte';

	let events: DebugEvent[] = $state([]);
	const unsubBus = debugBus.subscribe((v) => (events = v));
	onDestroy(unsubBus);

	let ralphEvents = $derived(
		events.filter(
			(e) =>
				e.type === 'ralph_iteration' ||
				e.type === 'ralph_stop' ||
				e.type === 'reasoning' ||
				e.type === 'planner_plan'
		)
	);

	let iterationCount = $derived(ralphEvents.filter((e) => e.type === 'ralph_iteration').length);
	let reasoningCount = $derived(ralphEvents.filter((e) => e.type === 'reasoning').length);
	let plannerCount = $derived(ralphEvents.filter((e) => e.type === 'planner_plan').length);

	function formatTime(ms: number): string {
		return new Date(ms).toLocaleTimeString();
	}
</script>

<div class="flex flex-col gap-3 p-3 text-[11.5px]">
	<section class="grid grid-cols-3 gap-2">
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Ralph iterations</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">{iterationCount}</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Reasoning</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">{reasoningCount}</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Plans</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">{plannerCount}</div>
		</div>
	</section>

	{#if ralphEvents.length === 0}
		<div
			class="rounded border border-dashed border-border-subtle bg-background/60 p-2 text-[11px] text-muted"
		>
			No Ralph / planner events observed yet. Ralph iterations, reflections, scorers, and plans
			require Phase 2 sandbox emissions from
			<code class="font-mono">agent_server/engine/run.py</code> forwarding exo's
			<code class="font-mono">RalphIterationEvent</code> and
			<code class="font-mono">RalphStopEvent</code>. Reasoning events are already surfaced when the
			planner emits them.
		</div>
	{:else}
		<section class="rounded border border-border-subtle bg-background p-2">
			<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Timeline</div>
			<ul class="space-y-1.5">
				{#each ralphEvents as e, i (i)}
					<li
						class="rounded border border-border-subtle bg-surface-2/50 p-1.5 font-mono text-[10.5px]"
					>
						<div class="flex items-center gap-2 text-foreground">
							<span class="text-muted">{formatTime(e.at)}</span>
							<span class="text-subtle">#{e.seq}</span>
							<span class="text-accent">{e.type}</span>
						</div>
						<details class="mt-1">
							<summary class="cursor-pointer text-subtle">payload</summary>
							<div class="mt-1">
								<JsonViewer value={e.payload} collapseDepth={2} />
							</div>
						</details>
					</li>
				{/each}
			</ul>
		</section>
	{/if}
</div>
