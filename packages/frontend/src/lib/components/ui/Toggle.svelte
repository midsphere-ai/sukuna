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

	const fallbackId = `toggle-${Math.random().toString(36).slice(2, 9)}`;
	const toggleId = $derived(id ?? fallbackId);

	// When onchange is provided, the toggle is "controlled" — clicks don't
	// auto-flip the checkbox; the parent must update `checked` explicitly.
	const controlled = $derived(!!onchange);
</script>

<label
	for={toggleId}
	class="inline-flex cursor-pointer items-center gap-3 select-none {disabled
		? 'cursor-not-allowed opacity-50'
		: ''} {className}"
>
	<div class="relative">
		<input
			{...rest}
			id={toggleId}
			type="checkbox"
			role="switch"
			{checked}
			{disabled}
			onclick={(e: MouseEvent) => {
				if (controlled) {
					// Block the checkbox from toggling — the parent controls `checked`.
					e.preventDefault();
					if (onchange) onchange(e);
				}
			}}
			onchange={(e: Event) => {
				if (!controlled) {
					checked = (e.target as HTMLInputElement).checked;
				}
			}}
			aria-checked={checked}
			class="peer sr-only"
		/>
		<div
			class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent peer-disabled:cursor-not-allowed"
		></div>
		<div
			class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
		></div>
	</div>
	{#if label}
		<span class="text-sm text-foreground">{label}</span>
	{/if}
</label>
