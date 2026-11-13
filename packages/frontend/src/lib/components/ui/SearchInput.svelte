<script lang="ts">
	type Props = {
		value: string;
		placeholder?: string;
		oninput?: (e: Event) => void;
		onclear?: () => void;
		showCancel?: boolean;
		class?: string;
		inputEl?: HTMLInputElement;
	};

	let {
		value = $bindable(''),
		placeholder = 'Search...',
		oninput,
		onclear,
		showCancel = false,
		class: className = '',
		inputEl = $bindable(undefined)
	}: Props = $props();
</script>

<div class="relative {className}" role="search">
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width="18"
		height="18"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		class="absolute top-1/2 left-3.5 -translate-y-1/2 text-muted"
		aria-hidden="true"
	>
		<circle cx="11" cy="11" r="8" />
		<path d="M21 21l-4.35-4.35" />
	</svg>
	<input
		bind:this={inputEl}
		bind:value
		{oninput}
		type="search"
		{placeholder}
		aria-label={placeholder.replace('...', '')}
		class="h-9 w-full rounded-xl border border-border-subtle bg-surface-2 pl-10 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)] {showCancel
			? 'pr-20'
			: 'pr-4'}"
	/>
	{#if showCancel && value}
		<button
			onclick={onclear}
			class="absolute top-1/2 right-3 -translate-y-1/2 rounded-full px-3 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent/10"
		>
			Cancel
		</button>
	{/if}
</div>
