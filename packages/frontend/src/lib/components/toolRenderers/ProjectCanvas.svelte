<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	// Tool name determines type (web or mobile) and operation (init or project mgmt)
	let projectType = $derived(toolCall.toolName.startsWith('mobile') ? 'mobile' : 'web');
	let opKind = $derived(toolCall.toolName.endsWith('_init') ? 'init' : 'setup');

	let action = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : opKind
	);
	let argName = $derived(
		typeof toolCall.args?.name === 'string' ? (toolCall.args.name as string) : ''
	);
	let argTitle = $derived(
		typeof toolCall.args?.title === 'string' ? (toolCall.args.title as string) : ''
	);
	let argDescription = $derived(
		typeof toolCall.args?.description === 'string' ? (toolCall.args.description as string) : ''
	);
	let argScaffold = $derived(
		typeof toolCall.args?.scaffold === 'string' ? (toolCall.args.scaffold as string) : ''
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

	// Defensive extraction: everything that isn't a standard envelope field
	const STANDARD_KEYS = new Set(['success', 'message', 'error', 'hint', 'output']);
	let extraFields = $derived.by(() => {
		const out: Array<[string, string]> = [];
		for (const [k, v] of Object.entries(resultObj)) {
			if (STANDARD_KEYS.has(k)) continue;
			if (v == null) continue;
			let display: string;
			if (typeof v === 'string') display = v;
			else if (typeof v === 'number' || typeof v === 'boolean') display = String(v);
			else {
				try {
					display = JSON.stringify(v);
				} catch {
					display = String(v);
				}
			}
			out.push([k, display]);
		}
		return out;
	});

	const TYPE_BADGE: Record<string, string> = {
		web: 'bg-accent/10 text-accent',
		mobile: 'bg-accent/15 text-accent'
	};
</script>

<div class="h-full p-2" data-testid="project-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="project-canvas"
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
					<path d="M3 3h7v7H3z" />
					<path d="M14 3h7v7h-7z" />
					<path d="M14 14h7v7h-7z" />
					<path d="M3 14h7v7H3z" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					project · {action}
				</span>
				<span
					class="rounded px-1.5 py-0.5 font-mono text-[10px] {TYPE_BADGE[projectType]}"
					data-testid="project-canvas-type"
				>
					{projectType}
				</span>
				{#if argName}
					<span
						class="truncate font-mono text-[11px] text-foreground"
						title={argName}
						data-testid="project-canvas-name"
					>
						{argName}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="project-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						working
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
						data-testid="project-canvas-error-badge"
					>
						error
					</span>
				{:else}
					<span
						class="rounded bg-success/15 px-2 py-0.5 font-mono text-[11px] text-success"
						data-testid="project-canvas-ok"
					>
						ok
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background p-4" data-testid="project-canvas-body">
			{#if isError}
				<div
					class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="project-canvas-error"
				>
					<div class="font-mono text-[10px] font-medium uppercase tracking-wide text-accent">
						{envelope.error ?? 'project error'}
					</div>
					{#if envelope.message}
						<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
					{/if}
					{#if envelope.hint}
						<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
					{/if}
				</div>
			{:else if isRunning}
				<div class="flex items-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					Setting up {projectType} project…
				</div>
			{:else}
				<div class="space-y-3">
					<!-- Args summary -->
					<div
						class="rounded border border-border-subtle bg-surface p-3"
						data-testid="project-canvas-args"
					>
						<div class="font-mono text-[10px] uppercase tracking-wide text-subtle">Arguments</div>
						<div class="mt-1.5 space-y-1 font-mono text-[11px]">
							{#if argName}
								<div class="flex gap-2">
									<span class="w-24 shrink-0 text-subtle">name</span>
									<span class="text-foreground">{argName}</span>
								</div>
							{/if}
							{#if argTitle}
								<div class="flex gap-2">
									<span class="w-24 shrink-0 text-subtle">title</span>
									<span class="text-foreground">{argTitle}</span>
								</div>
							{/if}
							{#if argScaffold}
								<div class="flex gap-2">
									<span class="w-24 shrink-0 text-subtle">scaffold</span>
									<span class="text-accent">{argScaffold}</span>
								</div>
							{/if}
							{#if argDescription}
								<div class="flex gap-2">
									<span class="w-24 shrink-0 text-subtle">description</span>
									<span class="text-foreground">{argDescription}</span>
								</div>
							{/if}
						</div>
					</div>

					<!-- Extra returned fields -->
					{#if extraFields.length > 0}
						<div
							class="rounded border border-border-subtle bg-surface p-3"
							data-testid="project-canvas-fields"
						>
							<div class="font-mono text-[10px] uppercase tracking-wide text-subtle">Result</div>
							<div class="mt-1.5 space-y-1 font-mono text-[11px]">
								{#each extraFields as [k, v] (k)}
									<div class="flex gap-2">
										<span class="w-24 shrink-0 text-subtle">{k}</span>
										<span class="min-w-0 flex-1 break-all text-foreground">{v}</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}

					<!-- Message text -->
					{#if rawMessage}
						<div
							class="whitespace-pre-wrap rounded border border-border-subtle bg-surface px-3 py-2 font-mono text-[11px] text-foreground"
							data-testid="project-canvas-message"
						>
							{rawMessage}
						</div>
					{/if}

					{#if !rawMessage && extraFields.length === 0 && !argName}
						<div class="text-[12px] italic text-subtle">No project info</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
