<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, truncatePath } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface BrowserLink {
		url: string;
		text?: string;
	}

	interface BrowserResultData {
		url?: string;
		title?: string;
		output?: string;
		screenshot_path?: string;
		has_forms?: boolean;
		links?: BrowserLink[];
		message?: string;
	}

	// Tool name: 'browser' or 'browser_*' sub-tools
	let subTool = $derived(toolCall.toolName.replace(/^browser_?/, '') || 'navigate');

	let intent = $derived(
		typeof toolCall.args?.intent === 'string' ? (toolCall.args.intent as string) : ''
	);
	let argUrl = $derived(
		typeof toolCall.args?.url === 'string' ? (toolCall.args.url as string) : ''
	);
	let focus = $derived(
		typeof toolCall.args?.focus === 'string' ? (toolCall.args.focus as string) : ''
	);

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	// Parse the output text block: contains "Title: X\nURL: Y\nClean screenshot path: Z\n..."
	let rawOutput = $derived(
		typeof resultObj.output === 'string' ? (resultObj.output as string) : ''
	);

	let parsed: BrowserResultData = $derived.by(() => {
		const data: BrowserResultData = {
			url: typeof resultObj.url === 'string' ? (resultObj.url as string) : undefined,
			title: typeof resultObj.title === 'string' ? (resultObj.title as string) : undefined,
			output: rawOutput,
			screenshot_path:
				typeof resultObj.screenshot_path === 'string'
					? (resultObj.screenshot_path as string)
					: undefined,
			has_forms:
				typeof resultObj.has_forms === 'boolean' ? (resultObj.has_forms as boolean) : undefined,
			links: Array.isArray(resultObj.links) ? (resultObj.links as BrowserLink[]) : undefined,
			message: typeof resultObj.message === 'string' ? (resultObj.message as string) : undefined
		};
		if (rawOutput) {
			const titleMatch = rawOutput.match(/^Title:\s*(.+)$/m);
			if (titleMatch && !data.title) data.title = titleMatch[1].trim();
			const urlMatch = rawOutput.match(/^URL:\s*(.+)$/m);
			if (urlMatch && !data.url) data.url = urlMatch[1].trim();
			const shotMatch = rawOutput.match(/^Clean screenshot path:\s*(.+)$/m);
			if (shotMatch && !data.screenshot_path) data.screenshot_path = shotMatch[1].trim();
		}
		return data;
	});

	let currentUrl = $derived(parsed.url || argUrl);
	let markdown = $derived.by(() => {
		if (!rawOutput) return '';
		const mdIdx = rawOutput.indexOf('Extracted page content in markdown:');
		if (mdIdx >= 0)
			return rawOutput.slice(mdIdx + 'Extracted page content in markdown:'.length).trim();
		return rawOutput;
	});

	let showAllLinks = $state(false);
	let visibleLinks = $derived.by(() => {
		const l = parsed.links ?? [];
		return showAllLinks ? l : l.slice(0, 10);
	});
	let hasMoreLinks = $derived((parsed.links?.length ?? 0) > 10);

	const INTENT_BADGE: Record<string, string> = {
		navigational: 'bg-accent/10 text-accent',
		informational: 'bg-success/15 text-success',
		transactional: 'bg-accent/15 text-accent'
	};
</script>

<div class="h-full p-2" data-testid="browser-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="browser-canvas"
	>
		<!-- Title bar -->
		<div
			class="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface px-3 py-2"
		>
			<div class="flex shrink-0 gap-1.5" aria-hidden="true">
				<div class="size-2.5 rounded-full bg-accent/70"></div>
				<div class="size-2.5 rounded-full bg-warning/70"></div>
				<div class="size-2.5 rounded-full bg-success/70"></div>
			</div>

			<div class="flex min-w-0 flex-1 items-center gap-2">
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide text-muted">
					browser · {subTool}
				</span>
				{#if currentUrl}
					<span
						class="truncate rounded bg-background px-2 py-0.5 font-mono text-[11px] text-foreground"
						title={currentUrl}
						data-testid="browser-canvas-url"
					>
						{truncatePath(currentUrl, 4)}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if intent && INTENT_BADGE[intent]}
					<span
						class="rounded px-1.5 py-0.5 font-mono text-[10px] {INTENT_BADGE[intent]}"
						data-testid="browser-canvas-intent"
					>
						{intent}
					</span>
				{/if}
				{#if parsed.has_forms}
					<span
						class="rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
						title="Page contains forms"
						data-testid="browser-canvas-has-forms"
					>
						forms
					</span>
				{/if}
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="browser-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						loading
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
						data-testid="browser-canvas-error-badge"
					>
						error
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex flex-1 min-h-0 overflow-hidden" data-testid="browser-canvas-body">
			<!-- Main view -->
			<div class="flex-1 overflow-auto bg-background">
				{#if isRunning && !parsed.screenshot_path && !markdown}
					<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
						<span
							class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
							aria-hidden="true"
						></span>
						Loading page…
					</div>
				{:else if isError}
					<div class="p-4">
						<div
							class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
							data-testid="browser-canvas-error"
						>
							<div class="font-mono text-[10px] font-medium uppercase tracking-wide text-accent">
								{envelope.error ?? 'browser error'}
							</div>
							{#if envelope.message}
								<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
							{/if}
							{#if envelope.hint}
								<div class="mt-1 text-[11px] italic text-muted">hint: {envelope.hint}</div>
							{/if}
						</div>
					</div>
				{:else if parsed.screenshot_path}
					<div class="flex flex-col items-center p-3" data-testid="browser-canvas-screenshot">
						<img
							src={parsed.screenshot_path}
							alt={parsed.title ?? 'page screenshot'}
							class="max-h-full max-w-full rounded border border-border-subtle bg-background object-contain"
							onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = 'none')}
						/>
						{#if parsed.title}
							<div class="mt-2 truncate font-mono text-[11px] text-muted" title={parsed.title}>
								{parsed.title}
							</div>
						{/if}
					</div>
				{:else if markdown}
					<div
						class="whitespace-pre-wrap break-words p-4 font-mono text-[12px] leading-relaxed text-foreground"
						data-testid="browser-canvas-output"
					>
						{markdown}
					</div>
				{:else if focus}
					<div class="p-4 text-[12px] italic text-subtle">
						Focus: {focus}
					</div>
				{:else}
					<div class="flex h-full items-center justify-center text-[12px] italic text-subtle">
						No page content
					</div>
				{/if}
			</div>

			<!-- Side panel: links -->
			{#if parsed.links && parsed.links.length > 0}
				<div
					class="w-56 shrink-0 overflow-auto border-l border-border-subtle bg-surface p-2"
					data-testid="browser-canvas-links"
				>
					<div class="mb-1.5 px-1 font-mono text-[10px] uppercase tracking-wide text-subtle">
						Links ({parsed.links.length})
					</div>
					<div class="space-y-1">
						{#each visibleLinks as link, i (i)}
							<div
								class="truncate rounded border border-border-subtle bg-surface-2 px-2 py-1 text-[11px] text-foreground"
								title={link.url}
								data-testid="browser-canvas-link"
							>
								<div class="truncate text-foreground">{link.text || link.url}</div>
								{#if link.text && link.url}
									<div class="truncate font-mono text-[10px] text-subtle">{link.url}</div>
								{/if}
							</div>
						{/each}
					</div>
					{#if hasMoreLinks && !showAllLinks}
						<button
							onclick={() => (showAllLinks = true)}
							class="mt-2 w-full rounded border border-border-subtle bg-surface-2 py-1 text-[10px] text-muted hover:bg-surface-2 hover:text-accent"
						>
							Show all {parsed.links.length}
						</button>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
