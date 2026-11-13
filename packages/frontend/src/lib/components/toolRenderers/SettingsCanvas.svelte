<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	// Normalize actions: tool uses 'add' (set), 'remove' (unset), 'list'
	let rawAction = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'list'
	);
	let action = $derived.by(() => {
		if (rawAction === 'add' || rawAction === 'set') return 'set';
		if (rawAction === 'remove' || rawAction === 'unset') return 'unset';
		return 'list';
	});

	let argKey = $derived(
		typeof toolCall.args?.key === 'string' ? (toolCall.args.key as string) : ''
	);
	let argValue = $derived(
		typeof toolCall.args?.value === 'string' ? (toolCall.args.value as string) : ''
	);
	let envFile = $derived(
		typeof toolCall.args?.env_file === 'string' ? (toolCall.args.env_file as string) : '.env.local'
	);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);
	let rawMessage = $derived(
		typeof toolCall.result === 'string'
			? (toolCall.result as string)
			: typeof resultObj.message === 'string'
				? (resultObj.message as string)
				: ''
	);

	// Parse env vars from structured field OR from list-style text output
	let envVars: Record<string, string> = $derived.by(() => {
		if (resultObj.env_vars && typeof resultObj.env_vars === 'object') {
			return resultObj.env_vars as Record<string, string>;
		}
		const out: Record<string, string> = {};
		if (action === 'list' && rawMessage) {
			const lines = rawMessage.split('\n');
			for (const line of lines) {
				const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
				if (m) out[m[1]] = m[2];
			}
		}
		return out;
	});

	const SECRET_RE = /token|key|secret|password|auth/i;
	function isSecret(k: string): boolean {
		return SECRET_RE.test(k);
	}
	function redact(v: string): string {
		if (!v) return '';
		if (v.length <= 6) return '•'.repeat(v.length);
		return v.slice(0, 2) + '•'.repeat(Math.max(4, v.length - 4)) + v.slice(-2);
	}
</script>

<div class="h-full p-2" data-testid="settings-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="settings-canvas"
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
					<path
						d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
					/>
					<circle cx="12" cy="12" r="3" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					env · {action}
				</span>
				<span
					class="truncate rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
					title={envFile}
				>
					{envFile}
				</span>
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						applying
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
						data-testid="settings-canvas-error-badge"
					>
						error
					</span>
				{:else}
					<span
						class="rounded bg-success/15 px-2 py-0.5 font-mono text-[11px] text-success"
						data-testid="settings-canvas-ok"
					>
						ok
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background p-4" data-testid="settings-canvas-body">
			{#if isError}
				<div
					class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="settings-canvas-error"
				>
					<div class="font-mono text-[10px] font-medium uppercase tracking-wide text-accent">
						{envelope.error ?? 'env error'}
					</div>
					{#if envelope.message}
						<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
					{/if}
					{#if envelope.hint}
						<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
					{/if}
				</div>
			{:else if action === 'set'}
				<div
					class="rounded border border-border-subtle bg-surface p-3"
					data-testid="settings-canvas-set"
				>
					<div class="font-mono text-[10px] uppercase tracking-wide text-subtle">Set</div>
					<div class="mt-1 flex flex-wrap items-baseline gap-2 font-mono text-[12px]">
						<span class="text-accent">{argKey}</span>
						<span class="text-subtle">=</span>
						<span class="text-foreground">
							{isSecret(argKey) ? redact(argValue) : argValue}
						</span>
						{#if isSecret(argKey)}
							<span class="rounded bg-warning/20 px-1.5 py-0.5 text-[9px] text-warning">
								redacted
							</span>
						{/if}
					</div>
				</div>
			{:else if action === 'unset'}
				<div
					class="rounded border border-border-subtle bg-surface p-3"
					data-testid="settings-canvas-unset"
				>
					<div class="font-mono text-[10px] uppercase tracking-wide text-subtle">Unset</div>
					<div class="mt-1 font-mono text-[12px]">
						<span class="text-accent">{argKey}</span>
					</div>
				</div>
			{:else if action === 'list'}
				{#if Object.keys(envVars).length > 0}
					<div class="space-y-1.5" data-testid="settings-canvas-list">
						{#each Object.entries(envVars) as [k, v] (k)}
							<div
								class="flex items-baseline gap-2 rounded border border-border-subtle bg-surface px-3 py-1.5"
								data-testid="settings-canvas-item"
							>
								<span class="font-mono text-[11px] text-accent">{k}</span>
								<span class="text-subtle">=</span>
								<span class="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground">
									{isSecret(k) ? redact(v) : v}
								</span>
								{#if isSecret(k)}
									<span class="rounded bg-warning/20 px-1.5 py-0.5 text-[9px] text-warning">
										redacted
									</span>
								{/if}
							</div>
						{/each}
					</div>
				{:else if rawMessage}
					<div
						class="whitespace-pre-wrap rounded border border-border-subtle bg-surface px-3 py-2 font-mono text-[11px] text-foreground"
					>
						{rawMessage}
					</div>
				{:else}
					<div class="text-[12px] italic text-subtle">No environment variables</div>
				{/if}
			{/if}
		</div>
	</div>
</div>
