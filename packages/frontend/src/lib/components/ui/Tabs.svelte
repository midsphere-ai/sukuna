<script lang="ts">
	import type { Component } from 'svelte';

	interface Tab {
		id: string;
		label: string;
		icon?: Component;
		disabled?: boolean;
	}

	type Props = {
		value?: string;
		tabs: Tab[];
		class?: string;
		onchange?: (id: string) => void;
	};

	let { value = $bindable(''), tabs, class: className = '', onchange }: Props = $props();

	function select(tab: Tab): void {
		if (tab.disabled) return;
		value = tab.id;
		onchange?.(tab.id);
	}
</script>

<div role="tablist" class="flex gap-1 border-b border-border-subtle {className}">
	{#each tabs as tab (tab.id)}
		{@const active = value === tab.id}
		<button
			type="button"
			role="tab"
			aria-selected={active}
			aria-disabled={tab.disabled ? 'true' : undefined}
			disabled={tab.disabled}
			onclick={() => select(tab)}
			class="flex items-center gap-1.5 rounded-t-md px-3 py-2 text-sm transition-colors duration-150
				{active
				? 'bg-surface-2 text-foreground border-b-2 border-accent -mb-px font-medium'
				: 'text-muted hover:text-foreground'}
				disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:text-muted"
		>
			{#if tab.icon}
				{@const TabIcon = tab.icon}
				<TabIcon size={13} strokeWidth={2} aria-hidden="true" />
			{/if}
			<span>{tab.label}</span>
		</button>
	{/each}
</div>
