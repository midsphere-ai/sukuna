<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let platform = $derived(toolCall.toolName.startsWith('mobile') ? 'mobile' : 'web');
	let action = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'status'
	);
	let argPort = $derived(
		typeof toolCall.args?.port === 'number' ? (toolCall.args.port as number) : undefined
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

	// Try to extract port/url/status from structured fields OR parse strings
	let port = $derived.by(() => {
		if (typeof resultObj.port === 'number') return resultObj.port as number;
		const m = rawMessage.match(/port\s+(\d+)/i);
		if (m) return parseInt(m[1], 10);
		return argPort;
	});

	let url = $derived.by(() => {
		if (typeof resultObj.url === 'string') return resultObj.url as string;
		const m = rawMessage.match(/https?:\/\/[^\s\n]+/);
		return m ? m[0] : '';
	});

	let serverStatus = $derived.by(() => {
		if (typeof resultObj.status === 'string') return resultObj.status as string;
		if (isError) return 'error';
		if (action === 'stop')
			return /stopped|force|available/i.test(rawMessage) ? 'stopped' : 'running';
		if (action === 'status') {
			if (/is running|started successfully/i.test(rawMessage)) return 'running';
			if (/stopped|no server|not running/i.test(rawMessage)) return 'stopped';
		}
		if (action === 'start' || action === 'restart') {
			return /started|running/i.test(rawMessage) ? 'running' : 'stopped';
		}
		return 'unknown';
	});

	const STATUS_CLASS: Record<string, string> = {
		running: 'bg-success/15 text-success',
		stopped: 'bg-surface text-subtle',
		error: 'bg-accent/15 text-accent',
		unknown: 'bg-surface text-subtle'
	};
</script>

<div class="h-full p-2" data-testid="dev-server-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="dev-server-canvas"
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
					<rect width="20" height="14" x="2" y="3" rx="2" />
					<line x1="8" x2="16" y1="21" y2="21" />
					<line x1="12" x2="12" y1="17" y2="21" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					{platform} dev server · {action}
				</span>
				<span
					class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
					data-testid="dev-server-canvas-platform"
				>
					{platform}
				</span>
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="dev-server-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						working
					</span>
				{:else}
					<span
						class="rounded px-2 py-0.5 font-mono text-[11px] font-medium {STATUS_CLASS[
							serverStatus
						] ?? STATUS_CLASS.unknown}"
						data-testid="dev-server-canvas-status"
					>
						{serverStatus}
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background p-4" data-testid="dev-server-canvas-body">
			{#if isError}
				<div
					class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="dev-server-canvas-error"
				>
					<div class="font-mono text-[10px] font-medium uppercase tracking-wide text-accent">
						{envelope.error ?? 'server error'}
					</div>
					{#if envelope.message}
						<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
					{/if}
					{#if envelope.hint}
						<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
					{/if}
				</div>
			{:else}
				<div class="space-y-3">
					{#if port !== undefined}
						<div
							class="flex items-center gap-3 rounded border border-border-subtle bg-surface px-3 py-2"
							data-testid="dev-server-canvas-port"
						>
							<span class="font-mono text-[10px] uppercase tracking-wide text-subtle">Port</span>
							<span class="font-mono text-[12px] text-foreground">{port}</span>
						</div>
					{/if}

					{#if url}
						<div
							class="flex items-center gap-3 rounded border border-border-subtle bg-surface px-3 py-2"
							data-testid="dev-server-canvas-url"
						>
							<span class="font-mono text-[10px] uppercase tracking-wide text-subtle">URL</span>
							<a
								href={url}
								target="_blank"
								rel="noopener noreferrer"
								class="truncate font-mono text-[12px] text-accent underline decoration-border-subtle hover:text-accent"
							>
								{url}
							</a>
						</div>
					{/if}

					{#if rawMessage}
						<div
							class="whitespace-pre-wrap rounded border border-border-subtle bg-surface px-3 py-2 font-mono text-[11px] text-foreground"
							data-testid="dev-server-canvas-message"
						>
							{rawMessage}
						</div>
					{/if}

					{#if !rawMessage && !port && !url && !isRunning}
						<div class="text-[12px] italic text-subtle">No server info</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
