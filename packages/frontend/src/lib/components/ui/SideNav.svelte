<script lang="ts" generics="T extends string">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	interface Item {
		id: T;
		label: string;
		disabled?: boolean;
	}

	type Props = {
		value: T;
		items: Item[];
		title?: string;
		searchParamKey?: string;
		class?: string;
		onchange?: (id: T) => void;
	};

	let {
		value = $bindable(),
		items,
		title,
		searchParamKey,
		class: className = '',
		onchange
	}: Props = $props();

	onMount(() => {
		if (!searchParamKey) return;
		const fromUrl = page.url.searchParams.get(searchParamKey);
		const match = items.find((i) => i.id === fromUrl && !i.disabled);
		if (match) {
			value = match.id;
			onchange?.(match.id);
		}
	});

	function select(item: Item): void {
		if (item.disabled) return;
		value = item.id;
		onchange?.(item.id);
		if (searchParamKey) {
			const url = new URL(page.url);
			url.searchParams.set(searchParamKey, item.id);
			goto(url, { keepFocus: true, noScroll: true, replaceState: true });
		}
	}
</script>

<nav aria-label="Section navigation" class="flex w-56 shrink-0 flex-col gap-0.5 {className}">
	{#if title}
		<h1 class="mb-4 px-3 text-lg font-medium text-foreground">{title}</h1>
	{/if}
	{#each items as item (item.id)}
		{@const active = value === item.id}
		<button
			type="button"
			aria-current={active ? 'page' : undefined}
			disabled={item.disabled}
			onclick={() => select(item)}
			class="flex items-center rounded-md px-3 py-2 text-left text-sm transition-colors duration-150
				{active
				? 'bg-surface-2 font-medium text-foreground'
				: 'text-muted hover:bg-surface-2/60 hover:text-foreground'}
				disabled:cursor-not-allowed disabled:opacity-50"
		>
			{item.label}
		</button>
	{/each}
</nav>
