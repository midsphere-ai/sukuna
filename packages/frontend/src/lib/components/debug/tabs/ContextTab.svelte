<script lang="ts">
	import { onDestroy } from 'svelte';
	import { debugBus, type DebugEvent } from '$stores/debugBus';
	import JsonViewer from '../JsonViewer.svelte';

	let events: DebugEvent[] = $state([]);
	const unsubBus = debugBus.subscribe((v) => (events = v));
	onDestroy(unsubBus);

	type CtxEntry = {
		seq: number;
		at: number;
		action: string;
		before: number;
		after: number;
		payload: Record<string, unknown>;
	};

	let entries = $derived.by<CtxEntry[]>(() =>
		events
			.filter((e) => e.type === 'context')
			.map((e) => ({
				seq: e.seq,
				at: e.at,
				action: String(e.payload.action ?? ''),
				before: Number(e.payload.before_count ?? 0),
				after: Number(e.payload.after_count ?? 0),
				payload: e.payload
			}))
	);

	let injected = $derived.by(() => events.filter((e) => e.type === 'message_injected'));

	function formatTime(ms: number): string {
		return new Date(ms).toLocaleTimeString();
	}
</script>

<div class="flex flex-col gap-3 p-3 text-[11.5px]">
	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">
			Context reductions ({entries.length})
		</div>
		{#if entries.length === 0}
			<div class="py-2 text-[11px] text-muted">
				No context reductions yet. Fires when the agent summarises or truncates older turns.
			</div>
		{:else}
			<ul class="space-y-1.5">
				{#each entries as c (c.seq)}
					<li
						class="rounded border border-border-subtle bg-surface-2/50 p-1.5 font-mono text-[10.5px]"
					>
						<div class="flex items-center gap-2 text-foreground">
							<span class="text-muted">{formatTime(c.at)}</span>
							<span class="text-subtle">#{c.seq}</span>
							<span class="rounded bg-accent/15 px-1.5 text-accent">{c.action || 'reduction'}</span>
							<span class="ml-auto">{c.before} → {c.after}</span>
						</div>
						<details class="mt-1">
							<summary class="cursor-pointer text-subtle">payload</summary>
							<div class="mt-1">
								<JsonViewer value={c.payload} collapseDepth={2} />
							</div>
						</details>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">
			Message injections ({injected.length})
		</div>
		{#if injected.length === 0}
			<div class="py-2 text-[11px] text-muted">No messages injected mid-run.</div>
		{:else}
			<ul class="space-y-0.5 font-mono text-[10.5px]">
				{#each injected as e, i (i)}
					<li class="flex gap-2">
						<span class="w-[72px] text-muted">{formatTime(e.at)}</span>
						<span class="text-subtle">#{e.seq}</span>
						<span class="min-w-0 flex-1 truncate text-foreground"
							>{String(e.payload.text ?? e.payload.message ?? JSON.stringify(e.payload)).slice(
								0,
								140
							)}</span
						>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</div>
