<script lang="ts">
	import { onDestroy } from 'svelte';
	import { debugBus, type DebugEvent } from '$stores/debugBus';
	import { runStatus, type RunStatus } from '$services/sse';

	let events: DebugEvent[] = $state([]);
	let status: RunStatus = $state('idle');

	const unsubBus = debugBus.subscribe((v) => (events = v));
	const unsubStatus = runStatus.subscribe((v) => (status = v));

	onDestroy(() => {
		unsubBus();
		unsubStatus();
	});

	type StatusEntry = { at: number; status: string; seq: number };
	type McpEntry = {
		at: number;
		toolName: string;
		progress: number;
		total: number;
		message: string;
	};

	let statusTrace = $derived.by<StatusEntry[]>(() =>
		events
			.filter((e) => e.type === 'status' || e.type.startsWith('run_'))
			.map((e) => ({
				at: e.at,
				seq: e.seq,
				status: e.type === 'status' ? String(e.payload.status ?? '') : e.type.replace(/^run_/, '')
			}))
	);

	let mcpActivity = $derived.by<McpEntry[]>(() =>
		events
			.filter((e) => e.type === 'mcp_progress')
			.map((e) => ({
				at: e.at,
				toolName: String(e.payload.tool_name ?? ''),
				progress: Number(e.payload.progress ?? 0),
				total: Number(e.payload.total ?? 0),
				message: String(e.payload.message ?? '')
			}))
	);

	let mcpServers = $derived.by<string[]>(() => {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local dedup set inside a derivation; not reactive state
		const seen = new Set<string>();
		for (const m of mcpActivity) {
			const parts = m.toolName.split('__');
			if (parts.length > 1) seen.add(parts[0]);
		}
		return Array.from(seen);
	});

	let runId = $derived.by<string | null>(() => {
		for (let i = events.length - 1; i >= 0; i--) {
			const p = events[i].payload;
			if (typeof p.run_id === 'string') return p.run_id;
		}
		return null;
	});

	let sandboxId = $derived.by<string | null>(() => {
		for (let i = events.length - 1; i >= 0; i--) {
			const p = events[i].payload;
			if (typeof p.sandbox_id === 'string') return p.sandbox_id;
		}
		return null;
	});

	function formatTime(ms: number): string {
		return new Date(ms).toLocaleTimeString();
	}
</script>

<div class="flex flex-col gap-3 p-3 text-[11.5px]">
	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">Identity</div>
		<dl class="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
			<dt class="text-muted">run_id</dt>
			<dd class="break-all text-foreground">{runId ?? '—'}</dd>
			<dt class="text-muted">sandbox_id</dt>
			<dd class="break-all text-foreground">{sandboxId ?? '—'}</dd>
			<dt class="text-muted">status</dt>
			<dd class="text-foreground">{status}</dd>
		</dl>
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">
			Status trace ({statusTrace.length})
		</div>
		{#if statusTrace.length === 0}
			<div class="py-2 text-[11px] text-muted">No status transitions yet.</div>
		{:else}
			<ul class="space-y-0.5 font-mono text-[10.5px]">
				{#each statusTrace as e (`${e.seq}-${e.status}`)}
					<li class="flex gap-2">
						<span class="w-[72px] text-muted">{formatTime(e.at)}</span>
						<span class="w-[40px] text-subtle">#{e.seq}</span>
						<span class="text-foreground">{e.status}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">
			Attached MCP servers ({mcpServers.length})
		</div>
		{#if mcpServers.length === 0}
			<div class="py-2 text-[11px] text-muted">
				No MCP tools invoked yet. Servers are inferred from tool namespaces in <code
					class="font-mono">mcp_progress</code
				> events.
			</div>
		{:else}
			<ul class="flex flex-wrap gap-1">
				{#each mcpServers as s (s)}
					<li
						class="rounded border border-border-subtle bg-surface-2 px-2 py-0.5 font-mono text-[10.5px] text-foreground"
					>
						{s}
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section class="rounded border border-border-subtle bg-background p-2">
		<div class="mb-1 text-[10px] uppercase tracking-wide text-muted">
			MCP activity ({mcpActivity.length})
		</div>
		{#if mcpActivity.length === 0}
			<div class="py-2 text-[11px] text-muted">No MCP progress events.</div>
		{:else}
			<ul class="space-y-0.5 font-mono text-[10.5px]">
				{#each mcpActivity.slice(-20).reverse() as m, i (`${m.toolName}-${m.progress}-${i}`)}
					<li class="flex gap-2">
						<span class="w-[72px] text-muted">{formatTime(m.at)}</span>
						<span class="w-[160px] truncate text-foreground">{m.toolName}</span>
						<span class="w-[56px] text-subtle">{m.progress}/{m.total}</span>
						<span class="min-w-0 flex-1 truncate text-foreground/80">{m.message}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<div
		class="rounded border border-dashed border-border-subtle bg-background/60 p-2 text-[10.5px] text-muted"
	>
		Richer sandbox lifecycle (provisioning times, container state, startup duration, MCP attach
		errors) requires Phase 2 backend event emissions from
		<code class="font-mono">agent_server/api/startup.py</code>.
	</div>
</div>
