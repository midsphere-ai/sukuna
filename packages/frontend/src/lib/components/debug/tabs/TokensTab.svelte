<script lang="ts">
	import { onDestroy } from 'svelte';
	import { tokenUsage, creditBurn, type TokenUsage } from '$services/sse';
	import { debugBus, type DebugEvent } from '$stores/debugBus';

	let tokens: TokenUsage = $state({ inputTokens: 0, outputTokens: 0, totalTokens: 0, model: '' });
	let burn = $state(0);
	let events: DebugEvent[] = $state([]);

	const unsubTokens = tokenUsage.subscribe((v) => (tokens = v));
	const unsubBurn = creditBurn.subscribe((v) => (burn = v));
	const unsubBus = debugBus.subscribe((v) => (events = v));

	onDestroy(() => {
		unsubTokens();
		unsubBurn();
		unsubBus();
	});

	type UsageRow = {
		seq: number;
		at: number;
		source: 'step' | 'usage';
		inputTokens: number;
		outputTokens: number;
		totalTokens: number;
		costUsd: number;
		model: string;
		stepNumber?: number;
	};

	let rows = $derived.by<UsageRow[]>(() => {
		const out: UsageRow[] = [];
		for (const e of events) {
			const p = e.payload;
			if (e.type === 'step' && p.status === 'completed' && p.usage && typeof p.usage === 'object') {
				const u = p.usage as Record<string, unknown>;
				out.push({
					seq: e.seq,
					at: e.at,
					source: 'step',
					inputTokens: Number(u.input_tokens ?? 0),
					outputTokens: Number(u.output_tokens ?? 0),
					totalTokens: Number(u.total_tokens ?? 0),
					costUsd: Number(u.cost_usd ?? 0),
					model: String(u.model ?? p.model ?? ''),
					stepNumber: Number(p.step_number)
				});
			} else if (e.type === 'usage') {
				const u = (typeof p.usage === 'object' && p.usage ? p.usage : p) as Record<string, unknown>;
				out.push({
					seq: e.seq,
					at: e.at,
					source: 'usage',
					inputTokens: Number(u.input_tokens ?? 0),
					outputTokens: Number(u.output_tokens ?? 0),
					totalTokens: Number(u.total_tokens ?? 0),
					costUsd: Number(u.cost_usd ?? p.cost_usd ?? 0),
					model: String(u.model ?? p.model ?? '')
				});
			}
		}
		return out;
	});

	let totalCost = $derived(rows.reduce((acc, r) => acc + r.costUsd, 0));

	function formatTime(ms: number): string {
		return new Date(ms).toLocaleTimeString();
	}
</script>

<div class="flex flex-col gap-3 p-3 text-[11.5px]">
	<section class="grid grid-cols-2 gap-2">
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Cumulative input</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">
				{tokens.inputTokens.toLocaleString()}
			</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Cumulative output</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">
				{tokens.outputTokens.toLocaleString()}
			</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Total</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">
				{tokens.totalTokens.toLocaleString()}
			</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Cost (USD)</div>
			<div class="mt-0.5 font-mono text-[13px] text-foreground">
				${totalCost.toFixed(4)}
			</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2 col-span-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Model · credit burn</div>
			<div class="mt-0.5 flex items-center gap-3 font-mono text-[11.5px] text-foreground">
				<span class="truncate">{tokens.model || '—'}</span>
				<span class="text-subtle">burn {burn}</span>
			</div>
		</div>
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">
			Per-event usage ({rows.length})
		</div>
		{#if rows.length === 0}
			<div class="py-4 text-center text-[11px] text-muted">
				No usage events seen yet. Sandbox emits <code class="font-mono">usage</code> on each LLM
				call and <code class="font-mono">step</code> with usage on step completion.
			</div>
		{:else}
			<div class="overflow-auto">
				<table class="w-full text-left font-mono text-[10.5px]">
					<thead class="text-muted">
						<tr>
							<th class="px-1 py-0.5 font-normal">time</th>
							<th class="px-1 py-0.5 font-normal">src</th>
							<th class="px-1 py-0.5 font-normal">step</th>
							<th class="px-1 py-0.5 text-right font-normal">in</th>
							<th class="px-1 py-0.5 text-right font-normal">out</th>
							<th class="px-1 py-0.5 text-right font-normal">total</th>
							<th class="px-1 py-0.5 text-right font-normal">cost</th>
							<th class="px-1 py-0.5 font-normal">model</th>
						</tr>
					</thead>
					<tbody>
						{#each rows as r (`${r.seq}-${r.source}`)}
							<tr class="border-t border-border-subtle">
								<td class="px-1 py-0.5 text-muted">{formatTime(r.at)}</td>
								<td class="px-1 py-0.5 text-subtle">{r.source}</td>
								<td class="px-1 py-0.5 text-foreground">{r.stepNumber ?? '—'}</td>
								<td class="px-1 py-0.5 text-right text-foreground"
									>{r.inputTokens.toLocaleString()}</td
								>
								<td class="px-1 py-0.5 text-right text-foreground"
									>{r.outputTokens.toLocaleString()}</td
								>
								<td class="px-1 py-0.5 text-right text-foreground"
									>{r.totalTokens.toLocaleString()}</td
								>
								<td class="px-1 py-0.5 text-right text-foreground">${r.costUsd.toFixed(4)}</td>
								<td class="px-1 py-0.5 text-foreground">{r.model || '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</div>
