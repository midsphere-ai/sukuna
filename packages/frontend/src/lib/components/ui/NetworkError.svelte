<script lang="ts">
	type Props = {
		message?: string;
		onretry?: () => void;
		class?: string;
		[key: string]: unknown;
	};

	let {
		message = 'Unable to load data. Check your connection and try again.',
		onretry,
		class: className = '',
		...rest
	}: Props = $props();
</script>

<div
	class="flex items-center gap-3 rounded-xl border border-accent-negative/[0.12] bg-accent-negative/[0.04] px-4 py-3 {className}"
	role="alert"
	{...rest}
>
	<div
		class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-negative/[0.08]"
	>
		<svg
			class="h-4 w-4 text-accent-negative/70"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="1.5"
			stroke-linecap="round"
			stroke-linejoin="round"
			aria-hidden="true"
		>
			<line x1="1" y1="1" x2="23" y2="23" />
			<path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
			<path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
			<path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
			<line x1="12" y1="20" x2="12.01" y2="20" />
		</svg>
	</div>
	<p class="flex-1 text-sm text-subtle">{message}</p>
	{#if onretry}
		<button
			onclick={onretry}
			class="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg bg-accent-negative/[0.08] px-3 py-1.5 text-xs font-medium text-accent-negative/80 transition-colors duration-200 hover:bg-accent-negative/[0.14] hover:text-accent-negative"
		>
			<svg
				class="h-3 w-3"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<polyline points="23 4 23 10 17 10" />
				<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
			</svg>
			Retry
		</button>
	{/if}
</div>
