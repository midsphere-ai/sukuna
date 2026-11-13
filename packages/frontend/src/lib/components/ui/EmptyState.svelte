<script lang="ts">
	import type { Snippet } from 'svelte';
	import Button from './Button.svelte';

	type Props = {
		title: string;
		description?: string;
		ctaLabel?: string;
		ctaHref?: string;
		onctaclick?: () => void;
		illustration?: Snippet;
		class?: string;
		[key: string]: unknown;
	};

	let {
		title,
		description,
		ctaLabel,
		ctaHref,
		onctaclick,
		illustration,
		class: className = '',
		...rest
	}: Props = $props();
</script>

<div class="flex flex-col items-center justify-center px-6 py-16 text-center {className}" {...rest}>
	{#if illustration}
		<div class="mb-6">
			{@render illustration()}
		</div>
	{:else}
		<div class="mb-6 flex h-16 w-16 items-center justify-center rounded-lg bg-surface-2 text-muted">
			<svg class="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="1.5"
					d="M20 13V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7m16 0v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-5m16 0h-2.586a1 1 0 0 0-.707.293l-2.414 2.414a1 1 0 0 1-.707.293h-3.172a1 1 0 0 1-.707-.293l-2.414-2.414A1 1 0 0 0 6.586 13H4"
				/>
			</svg>
		</div>
	{/if}

	<h3 class="text-lg font-normal text-foreground">{title}</h3>

	{#if description}
		<p class="mt-2 max-w-sm text-sm text-subtle">{description}</p>
	{/if}

	{#if ctaLabel}
		<div class="mt-6">
			{#if ctaHref}
				<Button variant="primary" href={ctaHref}>{ctaLabel}</Button>
			{:else}
				<Button variant="primary" onclick={onctaclick}>{ctaLabel}</Button>
			{/if}
		</div>
	{/if}
</div>
