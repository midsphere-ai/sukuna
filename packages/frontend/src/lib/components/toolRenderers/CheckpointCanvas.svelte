<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface Commit {
		hash: string;
		message: string;
		author: string;
		date: string;
	}

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	const GIT_ACTIONS = new Set(['checkpoint', 'list', 'rollback']);
	let rawAction = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'checkpoint'
	);
	let action = $derived(GIT_ACTIONS.has(rawAction) ? rawAction : 'checkpoint');

	let commitHash = $derived(
		typeof resultObj.commit === 'string' ? (resultObj.commit as string) : ''
	);
	let commitMessage = $derived(
		typeof resultObj.commit_message === 'string'
			? (resultObj.commit_message as string)
			: typeof toolCall.args?.commit_message === 'string'
				? (toolCall.args.commit_message as string)
				: ''
	);
	let commitTime = $derived(typeof resultObj.time === 'string' ? (resultObj.time as string) : '');
	let rollbackMode = $derived(typeof resultObj.mode === 'string' ? (resultObj.mode as string) : '');
	let commits = $derived(
		Array.isArray(resultObj.checkpoints) ? (resultObj.checkpoints as Commit[]) : []
	);
	let commitCount = $derived(
		typeof resultObj.count === 'number' ? (resultObj.count as number) : commits.length
	);

	const ACTION_LABELS: Record<string, string> = {
		checkpoint: 'checkpoint',
		list: 'history',
		rollback: 'rollback'
	};
</script>

<div class="h-full p-2" data-testid="checkpoint-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="checkpoint-canvas"
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
					<circle cx="12" cy="12" r="3" />
					<line x1="3" x2="9" y1="12" y2="12" />
					<line x1="15" x2="21" y1="12" y2="12" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					git · {ACTION_LABELS[action] ?? action}
				</span>
				{#if commitHash && action !== 'list'}
					<span
						class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
						data-testid="checkpoint-canvas-hash"
					>
						{commitHash}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="checkpoint-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						running
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{:else if action === 'list'}
					<span
						class="rounded bg-success/15 px-2 py-0.5 font-mono text-[11px] font-medium text-success"
					>
						{commitCount} checkpoint{commitCount === 1 ? '' : 's'}
					</span>
				{:else}
					<span
						class="rounded bg-success/15 px-2 py-0.5 font-mono text-[11px] font-medium text-success"
					>
						ok
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background p-4" data-testid="checkpoint-canvas-body">
			{#if isRunning && !isError}
				<div class="flex items-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					{#if action === 'checkpoint'}
						Saving checkpoint…
					{:else if action === 'rollback'}
						Rolling back…
					{:else}
						Loading history…
					{/if}
				</div>
			{:else if isError}
				<div
					class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="checkpoint-canvas-error"
				>
					<div class="font-mono text-[10px] font-medium uppercase text-accent">
						{envelope.error ?? 'error'}
					</div>
					{#if envelope.message}
						<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
					{/if}
					{#if envelope.hint}
						<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
					{/if}
				</div>
			{:else if action === 'checkpoint'}
				<div
					class="rounded-lg border border-border-subtle bg-surface px-3 py-3"
					data-testid="checkpoint-canvas-detail"
				>
					<div class="flex items-start gap-3">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="18"
							height="18"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="mt-0.5 shrink-0 text-success"
						>
							<polyline points="20 6 9 17 4 12" />
						</svg>
						<div class="min-w-0 flex-1">
							<div class="text-[13px] font-medium text-foreground">Checkpoint saved</div>
							{#if commitMessage}
								<div class="mt-1 text-[12px] text-muted">{commitMessage}</div>
							{/if}
							{#if commitTime}
								<div class="mt-1 font-mono text-[10px] text-subtle">{commitTime}</div>
							{/if}
						</div>
					</div>
				</div>
			{:else if action === 'rollback'}
				<div
					class="rounded-lg border border-accent/30 bg-accent/5 px-3 py-3"
					data-testid="checkpoint-canvas-rollback"
				>
					<div class="flex items-start gap-3">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="18"
							height="18"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="mt-0.5 shrink-0 text-accent"
						>
							<path d="m12 8-4 4 4 4" />
							<path d="M4 12h12a4 4 0 1 1 0 8h-4" />
							<circle cx="12" cy="12" r="10" />
						</svg>
						<div class="min-w-0 flex-1">
							<div class="text-[13px] font-medium text-foreground">Rolled back</div>
							{#if commitMessage}
								<div class="mt-1 text-[12px] text-muted">{commitMessage}</div>
							{/if}
							{#if rollbackMode}
								<div class="mt-1 font-mono text-[10px] text-accent">{rollbackMode}</div>
							{/if}
						</div>
					</div>
				</div>
			{:else if action === 'list'}
				{#if commits.length === 0}
					<div class="flex h-full items-center justify-center text-[12px] italic text-subtle">
						{envelope.message ?? 'No checkpoints'}
					</div>
				{:else}
					<div class="space-y-1.5" data-testid="checkpoint-canvas-timeline">
						{#each commits as c, i (c.hash + i)}
							<div
								class="rounded border border-border-subtle bg-surface px-3 py-2"
								data-testid="checkpoint-canvas-commit"
							>
								<div class="flex items-start gap-3">
									<div class="flex flex-col items-center">
										<span class="inline-block size-2 rounded-full bg-success" aria-hidden="true"
										></span>
										{#if i < commits.length - 1}
											<span class="mt-1 block h-3 w-px bg-border-subtle" aria-hidden="true"></span>
										{/if}
									</div>
									<div class="min-w-0 flex-1">
										<div class="flex items-center gap-2">
											<span
												class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
											>
												{c.hash}
											</span>
											<span class="truncate text-[12px] text-foreground">{c.message}</span>
										</div>
										<div class="mt-0.5 flex items-center gap-2 text-[10px] text-subtle">
											{#if c.author}<span>{c.author}</span>{/if}
											{#if c.date}<span class="font-mono">{c.date}</span>{/if}
										</div>
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		</div>
	</div>
</div>
