<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { TextMessage } from '$services/sse';
	import { renderMarkdown, renderMarkdownExperimental } from '$lib/utils/markdown';
	import { flagEnabled } from '$stores/featureFlags';

	type Props = {
		message: TextMessage;
		startedByName?: string;
		muted?: boolean;
	};

	let { message, startedByName, muted = false }: Props = $props();
	let renderedHtml = $state('');
	let hasVisibleText = $derived(message.text.trim().length > 0);
	let containerClass = $derived(muted ? 'my-0.5 min-w-0' : 'min-w-0');

	const expMdFlag = flagEnabled('experimental-markdown');
	let useExpMd = $state(false);
	const unsubExpMd = expMdFlag.subscribe((v) => {
		useExpMd = v;
	});
	onDestroy(() => unsubExpMd());

	$effect(() => {
		const text = message.text;
		const streaming = message.isStreaming;
		const render = useExpMd ? renderMarkdownExperimental : renderMarkdown;

		if (!streaming) {
			renderedHtml = render(text);
			return;
		}

		// Prioritize immediate visual feedback while the model is typing.
		renderedHtml = render(text, true);
	});
</script>

<div class={containerClass} data-testid="agent-message">
	{#if startedByName}
		<div class="mb-1.5 text-[11.5px] text-muted">
			Started by {startedByName}
		</div>
	{/if}
	{#if hasVisibleText}
		<!-- Text content with markdown (uniform text color across elements) -->
		<div
			data-prose
			class="prose max-w-none break-words font-normal text-[14px] leading-relaxed {muted
				? 'text-foreground/70'
				: 'text-foreground/70'} [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_a]:text-current [&_a]:underline [&_a]:decoration-current/30 hover:[&_a]:decoration-current/60 [&_strong]:font-medium [&_strong]:text-current [&_p]:mb-3 [&_h1]:text-[18px] [&_h1]:font-normal [&_h1]:tracking-tight [&_h1]:text-current [&_h1]:mt-5 [&_h1]:mb-2 [&_h2]:text-[16px] [&_h2]:font-normal [&_h2]:text-current [&_h2]:mt-4 [&_h2]:mb-1.5 [&_h3]:text-[15px] [&_h3]:font-normal [&_h3]:text-current [&_h3]:mt-3 [&_h3]:mb-1 [&_code]:rounded [&_code]:border [&_code]:border-border-subtle [&_code]:bg-surface [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-[13px] [&_code]:font-mono [&_code]:text-current [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-background [&_pre]:p-3 [&_pre]:my-3 [&_pre]:border [&_pre]:border-border-subtle [&_pre_code]:border-0 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-[12.5px] [&_ol]:pl-5 [&_ol]:mb-3 [&_ul]:pl-5 [&_ul]:mb-3 [&_li]:my-0.5 [&_blockquote]:border-l-2 [&_blockquote]:border-accent/40 [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-current [&_blockquote]:my-3 [&_hr]:hidden [&_table]:w-full [&_table]:text-sm [&_table]:my-3 [&_th]:text-left [&_th]:font-medium [&_th]:text-current [&_th]:pb-2 [&_th]:border-b [&_th]:border-border-strong [&_td]:py-1.5 [&_td]:pr-4 [&_td]:border-b [&_td]:border-border-subtle"
		>
			<!-- eslint-disable svelte/no-at-html-tags -->
			{@html renderedHtml}
			<!-- eslint-enable svelte/no-at-html-tags -->
		</div>
	{/if}
</div>
