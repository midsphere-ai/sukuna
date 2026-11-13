<script lang="ts">
	type Props = {
		label?: string;
		id?: string;
		checked?: boolean;
		disabled?: boolean;
		class?: string;
		onchange?: (e: Event) => void;
		[key: string]: unknown;
	};

	let {
		label,
		id,
		checked = $bindable(false),
		disabled = false,
		class: className = '',
		onchange,
		...rest
	}: Props = $props();

	const fallbackId = `checkbox-${Math.random().toString(36).slice(2, 9)}`;
	const checkboxId = $derived(id ?? fallbackId);
</script>

<label
	for={checkboxId}
	class="inline-flex cursor-pointer items-center gap-2.5 select-none {disabled
		? 'cursor-not-allowed opacity-50'
		: ''} {className}"
>
	<div class="relative flex items-center justify-center">
		<input
			{...rest}
			id={checkboxId}
			type="checkbox"
			bind:checked
			{disabled}
			{onchange}
			class="peer h-[18px] w-[18px] cursor-pointer appearance-none rounded-md border border-border-strong bg-surface-2 transition-all duration-200
				checked:border-accent checked:bg-accent
				disabled:cursor-not-allowed"
		/>
		<svg
			class="pointer-events-none absolute h-3 w-3 text-background opacity-0 transition-opacity duration-200 peer-checked:opacity-100"
			fill="none"
			stroke="currentColor"
			viewBox="0 0 24 24"
			aria-hidden="true"
		>
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="m5 13 4 4L19 7" />
		</svg>
	</div>
	{#if label}
		<span class="text-sm text-foreground">{label}</span>
	{/if}
</label>
