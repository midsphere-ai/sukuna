<script lang="ts">
	import { onDestroy } from 'svelte';
	import { streamTransport, directStreamFailureReason, type StreamTransport } from '$services/sse';
	import {
		streamDiagnostics,
		debugBus,
		computeEventRate,
		type StreamDiagnostics,
		type DebugEvent
	} from '$stores/debugBus';

	let transport: StreamTransport = $state('none');
	let failureReason: string | null = $state(null);
	let diagnostics: StreamDiagnostics = $state({
		url: null,
		transport: 'none',
		connectedAt: null,
		disconnectedAt: null,
		consecutiveFailures: 0,
		reconnectCount: 0,
		reconnectHistory: [],
		lastSeq: -1,
		lastEventAt: null,
		eventsReceived: 0,
		fallbackActive: false,
		fallbackReason: null
	});
	let events: DebugEvent[] = $state([]);

	const unsubTransport = streamTransport.subscribe((v) => (transport = v));
	const unsubFailure = directStreamFailureReason.subscribe((v) => (failureReason = v));
	const unsubDiag = streamDiagnostics.subscribe((v) => (diagnostics = v));
	const unsubBus = debugBus.subscribe((v) => (events = v));

	onDestroy(() => {
		unsubTransport();
		unsubFailure();
		unsubDiag();
		unsubBus();
	});

	let eventRate = $state(0);
	let tick = $state(0);
	const timer = setInterval(() => (tick += 1), 1000);
	onDestroy(() => clearInterval(timer));
	$effect(() => {
		void tick;
		eventRate = computeEventRate(events);
	});

	let timeSinceLast = $derived.by(() => {
		void tick;
		if (!diagnostics.lastEventAt) return null;
		return Math.round((Date.now() - diagnostics.lastEventAt) / 1000);
	});

	function transportTone(t: StreamTransport): string {
		if (t === 'direct') return 'bg-success/15 text-success';
		if (t === 'shared') return 'bg-accent/15 text-accent';
		return 'bg-border text-subtle';
	}

	function formatTime(ms: number): string {
		return new Date(ms).toLocaleTimeString();
	}
</script>

<div class="flex flex-col gap-3 p-3 text-[11.5px]">
	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="flex items-center gap-2">
			<span class="text-[10px] uppercase tracking-wide text-muted">transport</span>
			<span class="rounded px-2 py-0.5 font-mono text-[11px] capitalize {transportTone(transport)}"
				>{transport}</span
			>
			{#if diagnostics.fallbackActive}
				<span class="text-[10px] text-amber-700">fallback active</span>
			{/if}
		</div>
		{#if failureReason}
			<div class="mt-1 break-words font-mono text-[10.5px] text-amber-700">
				direct stream failure: {failureReason}
			</div>
		{/if}
		{#if diagnostics.fallbackReason}
			<div class="mt-1 break-words font-mono text-[10.5px] text-amber-700">
				fallback reason: {diagnostics.fallbackReason}
			</div>
		{/if}
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Connection</div>
		<dl class="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
			<dt class="text-muted">url</dt>
			<dd class="break-all text-foreground">{diagnostics.url ?? '—'}</dd>
			<dt class="text-muted">connected at</dt>
			<dd class="text-foreground">
				{diagnostics.connectedAt ? formatTime(diagnostics.connectedAt) : '—'}
			</dd>
			{#if diagnostics.disconnectedAt}
				<dt class="text-muted">disconnected</dt>
				<dd class="text-foreground">{formatTime(diagnostics.disconnectedAt)}</dd>
			{/if}
			<dt class="text-muted">consec. fails</dt>
			<dd class="text-foreground">{diagnostics.consecutiveFailures}</dd>
			<dt class="text-muted">reconnects</dt>
			<dd class="text-foreground">{diagnostics.reconnectCount}</dd>
			<dt class="text-muted">events</dt>
			<dd class="text-foreground">{diagnostics.eventsReceived}</dd>
			<dt class="text-muted">last seq</dt>
			<dd class="text-foreground">{diagnostics.lastSeq >= 0 ? diagnostics.lastSeq : '—'}</dd>
			<dt class="text-muted">events/sec (5s)</dt>
			<dd class="text-foreground">{eventRate.toFixed(2)}</dd>
			<dt class="text-muted">last event</dt>
			<dd class="text-foreground">{timeSinceLast !== null ? `${timeSinceLast}s ago` : '—'}</dd>
		</dl>
	</section>

	{#if diagnostics.reconnectHistory.length > 0}
		<section class="rounded border border-border-subtle bg-background p-2">
			<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Reconnect history</div>
			<ul class="space-y-0.5 font-mono text-[10.5px]">
				{#each diagnostics.reconnectHistory.slice().reverse() as entry, i (i)}
					<li class="flex gap-2">
						<span class="w-[72px] shrink-0 text-muted">{formatTime(entry.at)}</span>
						<span class="w-[40px] shrink-0 text-subtle">#{entry.attempt}</span>
						<span class="min-w-0 flex-1 break-words text-foreground">{entry.reason}</span>
					</li>
				{/each}
			</ul>
		</section>
	{/if}
</div>
