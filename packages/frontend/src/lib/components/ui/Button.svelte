<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		variant?: 'primary' | 'bordered' | 'default';
		children: Snippet;
		class?: string;
		href?: string;
		type?: 'button' | 'submit' | 'reset';
		disabled?: boolean;
		onclick?: (e: MouseEvent) => void;
		target?: string;
		rel?: string;
		[key: string]: unknown;
	};

	let {
		variant = 'default',
		children,
		class: className = '',
		href,
		type = 'button',
		disabled = false,
		onclick,
		target,
		rel,
		...rest
	}: Props = $props();

	const baseClasses =
		'inline-flex items-center justify-center font-medium transition-all duration-200 ease-out cursor-pointer active:scale-[0.97] disabled:opacity-50 disabled:pointer-events-none';

	const variantClasses: Record<string, string> = {
		primary: 'bg-foreground text-background rounded-xl px-6 py-3 text-sm hover:opacity-70',
		bordered:
			'border border-border-strong text-foreground rounded-xl px-6 py-3 text-sm hover:bg-foreground hover:text-background hover:border-foreground',
		default: 'text-foreground hover:text-accent hover:bg-surface rounded-lg px-4 py-2 text-sm'
	};
</script>

{#if href}
	<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- generic component, not always internal navigation -->
	<a {href} {target} {rel} class="{baseClasses} {variantClasses[variant]} {className}" {...rest}
		>{@render children()}</a
	>
{:else}
	<button
		{type}
		{disabled}
		{onclick}
		class="{baseClasses} {variantClasses[variant]} {className}"
		{...rest}>{@render children()}</button
	>
{/if}
