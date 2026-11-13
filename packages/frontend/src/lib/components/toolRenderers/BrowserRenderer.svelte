<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, truncatePath } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);
	let rawOutput = $derived(
		typeof resultObj.output === 'string' ? (resultObj.output as string) : ''
	);
	let argUrl = $derived(
		typeof toolCall.args?.url === 'string' ? (toolCall.args.url as string) : ''
	);

	let currentUrl = $derived.by(() => {
		if (typeof resultObj.url === 'string') return resultObj.url as string;
		const m = rawOutput.match(/^URL:\s*(.+)$/m);
		if (m) return m[1].trim();
		return argUrl;
	});

	let screenshotPath = $derived.by(() => {
		if (typeof resultObj.screenshot_path === 'string') return resultObj.screenshot_path as string;
		const m = rawOutput.match(/^Clean screenshot path:\s*(.+)$/m);
		return m ? m[1].trim() : '';
	});

	let snippet = $derived.by(() => {
		if (!rawOutput) return '';
		const idx = rawOutput.indexOf('Extracted page content in markdown:');
		const md =
			idx >= 0 ? rawOutput.slice(idx + 'Extracted page content in markdown:'.length) : rawOutput;
		return md.trim().replace(/\s+/g, ' ').slice(0, 160);
	});
</script>

<div class="rounded-lg border border-border-subtle bg-surface-2" data-testid="browser-renderer">
	<div class="flex items-center gap-2 border-b border-border-subtle bg-surface px-2.5 py-1.5">
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
			<circle cx="12" cy="12" r="10" />
			<path d="M2 12h20" />
			<path
				d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
			/>
		</svg>
		<span class="font-mono text-[10px] uppercase tracking-wide text-muted">browser</span>
		{#if currentUrl}
			<span
				class="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground"
				title={currentUrl}
				data-testid="browser-renderer-url"
			>
				{truncatePath(currentUrl, 3)}
			</span>
		{/if}
		{#if isRunning}
			<span
				class="flex items-center gap-1 rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted"
			>
				<span class="inline-block size-1.5 animate-pulse rounded-full bg-accent"></span>
				loading
			</span>
		{:else if isError}
			<span class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] text-accent">error</span
			>
		{/if}
	</div>

	<div class="flex items-center gap-2 px-2.5 py-2">
		{#if screenshotPath}
			<img
				src={screenshotPath}
				alt="page thumbnail"
				class="size-10 shrink-0 rounded border border-border-subtle bg-background object-cover"
				onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = 'none')}
				data-testid="browser-renderer-thumb"
			/>
		{/if}
		<div class="min-w-0 flex-1 text-[11px] text-foreground">
			{#if isError}
				<span class="text-accent">{envelope.error ?? envelope.message ?? 'browser error'}</span>
			{:else if snippet}
				<span class="line-clamp-2 text-muted">{snippet}</span>
			{:else if isRunning}
				<span class="italic text-subtle">Loading page…</span>
			{:else}
				<span class="italic text-subtle">No content</span>
			{/if}
		</div>
	</div>
</div>
