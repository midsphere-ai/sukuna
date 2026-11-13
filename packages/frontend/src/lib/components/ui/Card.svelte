<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		as?: 'div' | 'article' | 'section';
		children: Snippet;
		class?: string;
		[key: string]: unknown;
	};

	let { as = 'div', children, class: className = '', ...rest }: Props = $props();
</script>

<svelte:element
	this={as}
	class="rounded-xl border border-border-subtle bg-surface-2 transition-shadow duration-150 ease-out hover:border-border-strong {className}"
	{...rest}
>
	{@render children()}
</svelte:element>
