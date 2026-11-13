<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let projectType = $derived(toolCall.toolName.startsWith('mobile') ? 'mobile' : 'web');
	let isInit = $derived(toolCall.toolName.endsWith('_init'));
	let argName = $derived(
		typeof toolCall.args?.name === 'string' ? (toolCall.args.name as string) : ''
	);
	let action = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : ''
	);

	let verb = $derived.by(() => {
		if (isInit) return 'Initialized';
		if (action === 'set') return 'Activated';
		if (action === 'list') return 'Listed';
		return 'Updated';
	});
</script>

<div
	class="flex items-center gap-2 rounded-lg border border-border-subtle bg-surface-2 px-2.5 py-1.5"
	data-testid="project-renderer"
>
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width="12"
		height="12"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		class="shrink-0 text-muted"
	>
		<path d="M3 3h7v7H3z" />
		<path d="M14 3h7v7h-7z" />
		<path d="M14 14h7v7h-7z" />
		<path d="M3 14h7v7H3z" />
	</svg>
	<span class="font-mono text-[10px] uppercase tracking-wide text-muted">project</span>
	<span
		class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
		data-testid="project-renderer-type"
	>
		{projectType}
	</span>
	<span class="min-w-0 flex-1 truncate text-[11px] text-foreground">
		{#if isError}
			<span class="text-accent">{envelope.error ?? 'project error'}</span>
		{:else if isRunning}
			<span class="italic text-subtle">Setting up {projectType} project…</span>
		{:else if argName}
			{verb} {projectType} project <span class="font-mono text-accent">{argName}</span>
		{:else if action}
			{verb} {projectType} project
		{:else}
			<span class="italic text-subtle">{projectType} project</span>
		{/if}
	</span>
	{#if isError}
		<span class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] text-accent">error</span>
	{/if}
</div>
