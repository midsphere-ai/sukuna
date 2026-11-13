<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);
	let isSuccess = $derived(!isRunning && !isError);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let toolName = $derived(toolCall.toolName ?? '');
	let action = $derived(toolName.replace(/^km_/, ''));

	let path = $derived(
		typeof resultObj.path === 'string'
			? (resultObj.path as string)
			: typeof toolCall.args?.path === 'string'
				? (toolCall.args.path as string)
				: ''
	);
	let title = $derived(
		typeof toolCall.args?.title === 'string' ? (toolCall.args.title as string) : ''
	);
	let count = $derived(
		typeof resultObj.count === 'number' ? (resultObj.count as number) : undefined
	);
	let targetRole = $derived(
		typeof resultObj.target_role === 'string'
			? (resultObj.target_role as string)
			: typeof toolCall.args?.target_role === 'string'
				? (toolCall.args.target_role as string)
				: ''
	);

	const PAST: Record<string, string> = {
		read: 'Read',
		write: 'Wrote',
		list: 'Listed',
		delete: 'Deleted',
		nudge: 'Nudged'
	};
	const PROGRESSIVE: Record<string, string> = {
		read: 'Reading',
		write: 'Writing',
		list: 'Listing',
		delete: 'Deleting',
		nudge: 'Nudging'
	};
	let verb = $derived.by(() => {
		if (isRunning) return (PROGRESSIVE[action] ?? 'Running') + '…';
		if (isError) return `Failed to ${action}`;
		return PAST[action] ?? 'Done';
	});

	let detail = $derived.by(() => {
		if (action === 'list' && count !== undefined) {
			return `${count} file${count === 1 ? '' : 's'}`;
		}
		if (action === 'nudge') return title || targetRole;
		return path || title;
	});
</script>

<div data-testid="km-renderer">
	<div
		class="flex items-start gap-2.5 rounded-lg border border-border-subtle bg-surface px-3 py-2.5"
		data-testid="km-card"
	>
		{#if isRunning}
			<span
				class="mt-0.5 inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
				aria-hidden="true"
			></span>
		{:else if isSuccess}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="16"
				height="16"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="mt-0.5 shrink-0 text-success"
			>
				<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
			</svg>
		{:else}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="16"
				height="16"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="mt-0.5 shrink-0 text-accent"
			>
				<circle cx="12" cy="12" r="10" />
				<line x1="15" x2="9" y1="9" y2="15" />
				<line x1="9" x2="15" y1="9" y2="15" />
			</svg>
		{/if}

		<div class="min-w-0 flex-1">
			<div class="flex items-center gap-1.5 text-xs">
				<span class="font-mono text-[10px] uppercase tracking-wide text-subtle">km</span>
				<span class="text-subtle">{verb}</span>
				{#if detail}
					<span class="truncate font-mono text-foreground" data-testid="km-detail">{detail}</span>
				{/if}
			</div>
			{#if isError}
				<div class="mt-1 rounded border border-accent/30 bg-accent/5 px-2 py-1">
					<div class="font-mono text-[10px] font-medium uppercase text-accent">
						{envelope.error ?? 'error'}
					</div>
					{#if envelope.message}
						<div class="mt-0.5 text-[11px] text-foreground">{envelope.message}</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
