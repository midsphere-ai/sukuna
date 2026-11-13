<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		variant?: 'default' | 'coral' | 'blue' | 'green' | 'warning' | 'muted';
		children: Snippet;
		class?: string;
	};

	let { variant = 'default', children, class: className = '' }: Props = $props();

	const variantClasses: Record<string, string> = {
		default: 'bg-surface text-foreground',
		coral: 'bg-accent/10 text-accent',
		blue: 'bg-accent/10 text-accent',
		green: 'bg-success/15 text-success',
		warning: 'bg-amber-500/10 text-amber-600',
		muted: 'bg-muted text-subtle'
	};
</script>

<span
	class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {variantClasses[
		variant
	]} {className}"
>
	{@render children()}
</span>
