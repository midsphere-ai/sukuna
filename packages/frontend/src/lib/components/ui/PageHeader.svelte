<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		title: string;
		description?: string;
		size?: 'sm' | 'md' | 'lg';
		class?: string;
		actions?: Snippet;
	};

	let { title, description, size = 'md', class: className = '', actions }: Props = $props();

	const sizeClasses: Record<string, string> = {
		sm: 'text-xl sm:text-2xl',
		md: 'text-2xl',
		lg: 'text-2xl sm:text-3xl'
	};
</script>

<div class={className}>
	<div class="flex items-center gap-2">
		<h1 class="font-medium tracking-tight text-foreground {sizeClasses[size]}">
			{title}
		</h1>
		{#if actions}
			{@render actions()}
		{/if}
	</div>
	{#if description}
		<p class="mt-1 text-[13px] text-subtle">{description}</p>
	{/if}
</div>
