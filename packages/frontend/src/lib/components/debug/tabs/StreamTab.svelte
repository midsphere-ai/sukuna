<script lang="ts">
	import { onDestroy } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { debugBus, clearDebugBus, type DebugEvent } from '$stores/debugBus';
	import { toasts } from '$stores/toast';
	import JsonViewer from '../JsonViewer.svelte';

	const KNOWN_TYPES = [
		'text',
		'tool_call',
		'tool_result',
		'tool_call_delta',
		'step',
		'status',
		'usage',
		'reasoning',
		'mcp_progress',
		'context',
		'message_injected',
		'error',
		'hitl_request',
		'user_message',
		'run_started',
		'run_completed',
		'run_failed',
		'run_cancelled'
	];

	let events: DebugEvent[] = $state([]);
	let paused = $state(false);
	let filter = $state('');
	const activeTypes = new SvelteSet<string>();
	const expanded = new SvelteSet<number>();

	const unsubBus = debugBus.subscribe((v) => {
		if (!paused) events = v;
	});

	onDestroy(unsubBus);

	function togglePause(): void {
		paused = !paused;
	}

	function toggleType(type: string): void {
		if (activeTypes.has(type)) activeTypes.delete(type);
		else activeTypes.add(type);
	}

	function toggleExpanded(idx: number): void {
		if (expanded.has(idx)) expanded.delete(idx);
		else expanded.add(idx);
	}

	async function copyAll(): Promise<void> {
		try {
			await navigator.clipboard.writeText(JSON.stringify(events, null, 2));
			toasts.success(`Copied ${events.length} events`);
		} catch {
			toasts.error('Copy failed');
		}
	}

	function downloadJson(): void {
		const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `debug-stream-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
		a.click();
		URL.revokeObjectURL(url);
	}

	let filtered = $derived.by(() => {
		const f = filter.trim().toLowerCase();
		return events
			.filter((e) => {
				if (activeTypes.size > 0 && !activeTypes.has(e.type)) return false;
				if (!f) return true;
				if (e.type.toLowerCase().includes(f)) return true;
				if (String(e.seq).includes(f)) return true;
				try {
					return JSON.stringify(e.payload).toLowerCase().includes(f);
				} catch {
					return false;
				}
			})
			.map((e) => ({ event: e, origIdx: events.indexOf(e) }));
	});

	let typeCounts = $derived.by(() => {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local map inside derivation; not reactive state
		const counts = new Map<string, number>();
		for (const e of events) counts.set(e.type, (counts.get(e.type) ?? 0) + 1);
		return counts;
	});

	function formatTime(ms: number): string {
		const d = new Date(ms);
		const hh = String(d.getHours()).padStart(2, '0');
		const mm = String(d.getMinutes()).padStart(2, '0');
		const ss = String(d.getSeconds()).padStart(2, '0');
		const mss = String(d.getMilliseconds()).padStart(3, '0');
		return `${hh}:${mm}:${ss}.${mss}`;
	}

	function typeColor(type: string): string {
		if (type === 'text') return 'text-success';
		if (type === 'tool_call' || type === 'tool_result' || type === 'tool_call_delta')
			return 'text-accent';
		if (type === 'step') return 'text-subtle';
		if (type === 'status') return 'text-accent';
		if (type === 'usage') return 'text-amber-700';
		if (type === 'reasoning') return 'text-amber-700';
		if (type === 'error' || type === 'run_failed') return 'text-accent';
		if (type === 'mcp_progress') return 'text-amber-700';
		if (type === 'context') return 'text-accent';
		if (type.startsWith('run_')) return 'text-foreground';
		return 'text-foreground';
	}
</script>

<div class="flex h-full flex-col">
	<div
		class="flex flex-wrap items-center gap-1.5 border-b border-border-subtle bg-background px-2 py-1.5"
	>
		<input
			type="text"
			bind:value={filter}
			placeholder="filter events…"
			class="min-w-0 flex-1 rounded border border-border-subtle bg-surface-2 px-2 py-1 text-[11px] text-foreground outline-none focus:border-border-strong"
		/>
		<button
			type="button"
			onclick={togglePause}
			class="rounded border border-border-subtle bg-surface-2 px-2 py-1 text-[11px] hover:bg-surface-2"
		>
			{paused ? 'Resume' : 'Pause'}
		</button>
		<button
			type="button"
			onclick={clearDebugBus}
			class="rounded border border-border-subtle bg-surface-2 px-2 py-1 text-[11px] hover:bg-surface-2"
			>Clear</button
		>
		<button
			type="button"
			onclick={copyAll}
			class="rounded border border-border-subtle bg-surface-2 px-2 py-1 text-[11px] hover:bg-surface-2"
			>Copy</button
		>
		<button
			type="button"
			onclick={downloadJson}
			class="rounded border border-border-subtle bg-surface-2 px-2 py-1 text-[11px] hover:bg-surface-2"
			>Export</button
		>
	</div>

	<div class="flex flex-wrap gap-1 border-b border-border-subtle bg-background px-2 py-1.5">
		{#each KNOWN_TYPES as t (t)}
			{@const count = typeCounts.get(t) ?? 0}
			{@const on = activeTypes.has(t)}
			<button
				type="button"
				onclick={() => toggleType(t)}
				class="rounded-full border px-2 py-0.5 font-mono text-[10px] {on
					? 'border-foreground bg-foreground text-background'
					: count === 0
						? 'border-border-subtle bg-surface-2 text-muted'
						: 'border-border-subtle bg-surface-2 text-foreground hover:bg-surface-2'}"
			>
				{t}{count > 0 ? ` ${count}` : ''}
			</button>
		{/each}
	</div>

	<div class="flex-1 overflow-auto">
		{#if filtered.length === 0}
			<div class="flex h-full items-center justify-center text-[11.5px] text-muted">
				{events.length === 0 ? 'No events yet.' : 'No events match the filter.'}
			</div>
		{:else}
			<ul class="divide-y divide-border-subtle font-mono text-[11px]">
				{#each filtered as { event, origIdx } (origIdx)}
					{@const payload = event.payload}
					<li class="px-2 py-1">
						<button
							type="button"
							onclick={() => toggleExpanded(origIdx)}
							class="flex w-full items-center gap-2 text-left hover:bg-surface-2"
						>
							<span class="text-[9px] text-subtle">{expanded.has(origIdx) ? '▾' : '▸'}</span>
							<span class="w-[72px] shrink-0 text-muted">{formatTime(event.at)}</span>
							<span class="w-[44px] shrink-0 text-subtle">#{event.seq >= 0 ? event.seq : '—'}</span>
							<span class="w-[140px] shrink-0 truncate {typeColor(event.type)}">{event.type}</span>
							<span class="min-w-0 flex-1 truncate text-foreground/80">
								{#if event.type === 'text'}
									"{String(payload.content ?? payload.text ?? '').slice(0, 80)}"
								{:else if event.type === 'tool_call'}
									{payload.tool_name ?? payload.name}({Object.keys(payload.arguments ?? {}).join(
										', '
									)})
								{:else if event.type === 'tool_result'}
									{payload.tool_name ?? payload.name} =>
									{payload.success === false ? 'error' : 'ok'}
								{:else if event.type === 'step'}
									{payload.status} step {payload.step_number}
								{:else if event.type === 'status'}
									{payload.status}
								{:else}
									{JSON.stringify(payload).slice(0, 80)}
								{/if}
							</span>
						</button>
						{#if expanded.has(origIdx)}
							<div class="mt-1 rounded bg-surface-2/50 p-1.5">
								<JsonViewer value={event.payload} collapseDepth={2} />
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</div>
