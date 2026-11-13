<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		label?: string;
		error?: string;
		id?: string;
		value?: string;
		disabled?: boolean;
		required?: boolean;
		children: Snippet;
		class?: string;
		onchange?: (e: Event) => void;
		[key: string]: unknown;
	};

	let {
		label,
		error,
		id,
		value = $bindable(''),
		disabled = false,
		required = false,
		children,
		class: className = '',
		onchange,
		...rest
	}: Props = $props();

	const fallbackId = `select-${Math.random().toString(36).slice(2, 9)}`;
	const selectId = $derived(id ?? fallbackId);
</script>

<div class="flex flex-col gap-1.5 {className}">
	{#if label}
		<label for={selectId} class="text-sm font-medium text-foreground">
			{label}
			{#if required}<span class="text-accent">*</span>{/if}
		</label>
	{/if}
	<div class="relative">
		<select
			{...rest}
			id={selectId}
			bind:value
			{disabled}
			{required}
			{onchange}
			aria-invalid={error ? 'true' : undefined}
			aria-describedby={error ? `${selectId}-error` : undefined}
			class="w-full appearance-none rounded-xl border bg-surface-2 px-4 py-2.5 pr-10 text-sm text-foreground outline-none transition-all duration-200
				{error
				? 'border-accent/50 focus:border-accent focus:ring-2 focus:ring-accent/20'
				: 'border-border-subtle focus:border-border-strong focus:ring-2 focus:ring-[rgba(59,130,246,0.3)]'}
				disabled:cursor-not-allowed disabled:opacity-50"
		>
			{@render children()}
		</select>
		<svg
			class="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
			fill="none"
			stroke="currentColor"
			viewBox="0 0 24 24"
			aria-hidden="true"
		>
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m6 9 6 6 6-6" />
		</svg>
	</div>
	{#if error}
		<p id="{selectId}-error" class="text-xs text-accent" role="alert">{error}</p>
	{/if}
</div>
