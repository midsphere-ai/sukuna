<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';

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

	const REASONING_ACTIONS = new Set(['reason', 'guard']);
	let rawAction = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'reason'
	);
	let action = $derived(REASONING_ACTIONS.has(rawAction) ? rawAction : 'reason');

	let question = $derived(
		typeof toolCall.args?.question === 'string' ? (toolCall.args.question as string) : ''
	);

	// Tool returns `result` (string) — contains reasoning + final answer
	let fullText = $derived(
		typeof resultObj.result === 'string'
			? (resultObj.result as string)
			: typeof resultObj.reasoning === 'string'
				? (resultObj.reasoning as string)
				: typeof resultObj.answer === 'string'
					? (resultObj.answer as string)
					: ''
	);

	// Try to split a final answer off the end if the LLM structured it.
	let split = $derived.by(() => {
		if (!fullText) return { body: '', answer: '' };
		const m = fullText.match(/(?:^|\n)\s*(?:final answer|answer|conclusion)\s*[:\-]\s*([\s\S]+)$/i);
		if (m && m.index !== undefined && m.index > 50) {
			return { body: fullText.slice(0, m.index).trimEnd(), answer: m[1].trim() };
		}
		return { body: fullText, answer: '' };
	});

	let copied = $state(false);
	function copyText(): void {
		if (!fullText) return;
		navigator.clipboard.writeText(fullText).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}
</script>

<div class="h-full p-2" data-testid="reasoning-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="reasoning-canvas"
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
					<path d="M9.663 17h4.673M12 3v1M3.34 7l.94.94M20.66 7l-.94.94M2 13h2M20 13h2M6 21h12" />
					<path d="M12 16a5 5 0 0 0 3-9 5 5 0 0 0-6 0 5 5 0 0 0 3 9Z" />
				</svg>
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide">
					reasoning · {action}
				</span>
				{#if question}
					<span
						class="truncate text-[11px] text-foreground"
						title={question}
						data-testid="reasoning-canvas-question"
					>
						{question}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="reasoning-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						thinking
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						error
					</span>
				{:else if action === 'guard'}
					<span
						class="rounded bg-accent/10 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
					>
						assessed
					</span>
				{:else}
					<span
						class="rounded bg-success/15 px-2 py-0.5 font-mono text-[11px] font-medium text-success"
					>
						ok
					</span>
				{/if}

				<button
					onclick={copyText}
					disabled={!fullText}
					class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted"
					title="Copy reasoning"
					aria-label="Copy reasoning"
					data-testid="reasoning-canvas-copy"
				>
					{#if copied}
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
							class="text-success"
						>
							<polyline points="20 6 9 17 4 12" />
						</svg>
					{:else}
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
						>
							<rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
							<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
						</svg>
					{/if}
				</button>
			</div>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-auto bg-background p-4" data-testid="reasoning-canvas-body">
			{#if isRunning && !fullText}
				<div class="flex items-center gap-2 text-[12px] text-muted">
					<span
						class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
						aria-hidden="true"
					></span>
					{action === 'guard' ? 'Assessing reasoning…' : 'Thinking through the problem…'}
				</div>
			{:else if isError}
				<div
					class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="reasoning-canvas-error"
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
			{:else if !fullText}
				<div class="text-[12px] italic text-subtle">
					{envelope.message ?? 'No reasoning output'}
				</div>
			{:else}
				<div class="space-y-4">
					<div
						class="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground"
						data-testid="reasoning-canvas-body-text"
					>
						{split.body}
					</div>

					{#if split.answer}
						<div
							class="rounded-lg border border-success/30 bg-success/15 px-3 py-3"
							data-testid="reasoning-canvas-answer"
						>
							<div
								class="mb-1 font-mono text-[10px] font-medium uppercase tracking-wide text-success"
							>
								{action === 'guard' ? 'assessment' : 'final answer'}
							</div>
							<div class="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground">
								{split.answer}
							</div>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
