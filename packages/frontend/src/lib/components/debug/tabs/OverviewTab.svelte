<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		runStatus,
		streamTransport,
		tokenUsage,
		toolCalls,
		creditBurn,
		type RunStatus,
		type StreamTransport,
		type TokenUsage,
		type ToolCallMessage
	} from '$services/sse';
	import {
		streamDiagnostics,
		debugBus,
		type StreamDiagnostics,
		type DebugEvent
	} from '$stores/debugBus';

	let status: RunStatus = $state('idle');
	let transport: StreamTransport = $state('none');
	let tokens: TokenUsage = $state({ inputTokens: 0, outputTokens: 0, totalTokens: 0, model: '' });
	let burn = $state(0);
	let tcMap = $state<Map<string, ToolCallMessage>>(new Map());
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

	const unsubStatus = runStatus.subscribe((v) => (status = v));
	const unsubTransport = streamTransport.subscribe((v) => (transport = v));
	const unsubTokens = tokenUsage.subscribe((v) => (tokens = v));
	const unsubBurn = creditBurn.subscribe((v) => (burn = v));
	const unsubToolCalls = toolCalls.subscribe((v) => (tcMap = v));
	const unsubDiag = streamDiagnostics.subscribe((v) => (diagnostics = v));
	const unsubBus = debugBus.subscribe((v) => (events = v));

	onDestroy(() => {
		unsubStatus();
		unsubTransport();
		unsubTokens();
		unsubBurn();
		unsubToolCalls();
		unsubDiag();
		unsubBus();
	});

	let toolCallsList = $derived(Array.from(tcMap.values()));
	let runningCount = $derived(toolCallsList.filter((t) => t.status === 'running').length);
	let errorCount = $derived(toolCallsList.filter((t) => t.status === 'error').length);
	let successCount = $derived(toolCallsList.filter((t) => t.status === 'success').length);

	let elapsed = $state(0);
	let elapsedTimer: ReturnType<typeof setInterval> | null = null;
	$effect(() => {
		if (elapsedTimer) clearInterval(elapsedTimer);
		if (diagnostics.connectedAt) {
			elapsed = Math.round((Date.now() - diagnostics.connectedAt) / 1000);
			elapsedTimer = setInterval(() => {
				if (diagnostics.connectedAt) {
					elapsed = Math.round((Date.now() - diagnostics.connectedAt) / 1000);
				}
			}, 1000);
		} else {
			elapsed = 0;
		}
		return () => {
			if (elapsedTimer) clearInterval(elapsedTimer);
			elapsedTimer = null;
		};
	});

	let lastEvent = $derived(events[events.length - 1]);
	let lastError = $derived.by(() => {
		for (let i = events.length - 1; i >= 0; i--) {
			if (events[i].type === 'error' || events[i].type === 'run_failed') return events[i];
		}
		return null;
	});

	function formatElapsed(sec: number): string {
		if (sec < 60) return `${sec}s`;
		const m = Math.floor(sec / 60);
		const s = sec % 60;
		if (m < 60) return `${m}m ${s}s`;
		const h = Math.floor(m / 60);
		return `${h}h ${m % 60}m`;
	}

	function transportClass(t: StreamTransport): string {
		if (t === 'direct') return 'bg-success/15 text-success';
		if (t === 'shared') return 'bg-accent/15 text-accent';
		return 'bg-border text-subtle';
	}

	function statusClass(s: RunStatus): string {
		if (s === 'running') return 'bg-success/15 text-success';
		if (s === 'completed') return 'bg-success/20 text-success';
		if (s === 'failed' || s === 'error') return 'bg-accent/20 text-accent';
		if (s === 'cancelled') return 'bg-border text-subtle';
		if (s === 'queued' || s === 'provisioning' || s === 'connecting')
			return 'bg-amber-500/15 text-amber-700';
		if (s === 'waiting_for_input') return 'bg-accent/15 text-accent';
		return 'bg-border text-subtle';
	}
</script>

<div class="flex flex-col gap-3 p-3 text-[11.5px]">
	<section class="grid grid-cols-2 gap-2">
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Status</div>
			<div class="mt-1">
				<span class="rounded px-1.5 py-0.5 text-[11px] font-medium capitalize {statusClass(status)}"
					>{status}</span
				>
			</div>
		</div>
		<div class="rounded border border-border-subtle bg-background p-2">
			<div class="text-[10px] uppercase tracking-wide text-muted">Transport</div>
			<div class="mt-1">
				<span
					class="rounded px-1.5 py-0.5 text-[11px] font-medium capitalize {transportClass(
						transport
					)}">{transport}</span
				>
				{#if diagnostics.fallbackActive}
					<span class="ml-1 text-[10px] text-amber-700">(fallback)</span>
				{/if}
			</div>
		</div>
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Stream</div>
		<dl class="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
			<dt class="text-muted">events</dt>
			<dd class="text-foreground">{diagnostics.eventsReceived}</dd>
			<dt class="text-muted">last seq</dt>
			<dd class="text-foreground">{diagnostics.lastSeq >= 0 ? diagnostics.lastSeq : '—'}</dd>
			<dt class="text-muted">reconnects</dt>
			<dd class="text-foreground">{diagnostics.reconnectCount}</dd>
			<dt class="text-muted">elapsed</dt>
			<dd class="text-foreground">{formatElapsed(elapsed)}</dd>
		</dl>
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Tokens</div>
		<dl class="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[11px]">
			<dt class="text-muted">input</dt>
			<dd class="text-foreground">{tokens.inputTokens.toLocaleString()}</dd>
			<dt class="text-muted">output</dt>
			<dd class="text-foreground">{tokens.outputTokens.toLocaleString()}</dd>
			<dt class="text-muted">total</dt>
			<dd class="text-foreground">{tokens.totalTokens.toLocaleString()}</dd>
			<dt class="text-muted">model</dt>
			<dd class="truncate text-foreground">{tokens.model || '—'}</dd>
			<dt class="text-muted">credit burn</dt>
			<dd class="text-foreground">{burn}</dd>
		</dl>
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Tool calls</div>
		<div class="flex items-center gap-3 font-mono text-[11px]">
			<span class="text-muted"
				>total <span class="text-foreground">{toolCallsList.length}</span></span
			>
			<span class="text-success">success {successCount}</span>
			<span class="text-amber-700">running {runningCount}</span>
			<span class="text-accent">error {errorCount}</span>
		</div>
	</section>

	{#if lastError}
		<section class="rounded border border-accent/30 bg-accent/5 p-2">
			<div class="mb-1 text-[10px] uppercase tracking-wide text-accent">Last error</div>
			<div class="break-words font-mono text-[11px] text-accent">
				{String(lastError.payload.message ?? lastError.payload.error ?? 'unknown error')}
			</div>
		</section>
	{/if}

	{#if lastEvent}
		<section class="rounded border border-border-subtle bg-background p-2 font-mono text-[10.5px]">
			<div class="text-muted">last event</div>
			<div class="mt-0.5 text-foreground">
				<span class="text-accent">{lastEvent.type}</span>
				<span class="ml-2 text-subtle">seq {lastEvent.seq >= 0 ? lastEvent.seq : '—'}</span>
			</div>
		</section>
	{/if}
</div>
