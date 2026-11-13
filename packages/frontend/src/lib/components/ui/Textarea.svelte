<script lang="ts">
	type Props = {
		label?: string;
		error?: string;
		id?: string;
		value?: string;
		placeholder?: string;
		disabled?: boolean;
		required?: boolean;
		rows?: number;
		autoResize?: boolean;
		class?: string;
		oninput?: (e: Event) => void;
		onblur?: (e: FocusEvent) => void;
		onfocus?: (e: FocusEvent) => void;
		[key: string]: unknown;
	};

	let {
		label,
		error,
		id,
		value = $bindable(''),
		placeholder,
		disabled = false,
		required = false,
		rows = 3,
		autoResize = false,
		class: className = '',
		oninput,
		onblur,
		onfocus,
		...rest
	}: Props = $props();

	const fallbackId = `textarea-${Math.random().toString(36).slice(2, 9)}`;
	const textareaId = $derived(id ?? fallbackId);

	let textareaEl: HTMLTextAreaElement | undefined = $state();

	function handleInput(e: Event): void {
		if (autoResize && textareaEl) {
			textareaEl.style.height = 'auto';
			textareaEl.style.height = `${textareaEl.scrollHeight}px`;
		}
		oninput?.(e);
	}
</script>

<div class="flex flex-col gap-1.5 {className}">
	{#if label}
		<label for={textareaId} class="text-sm font-medium text-foreground">
			{label}
			{#if required}<span class="text-accent">*</span>{/if}
		</label>
	{/if}
	<textarea
		{...rest}
		bind:this={textareaEl}
		id={textareaId}
		bind:value
		{placeholder}
		{disabled}
		{required}
		{rows}
		oninput={handleInput}
		{onblur}
		{onfocus}
		aria-invalid={error ? 'true' : undefined}
		aria-describedby={error ? `${textareaId}-error` : undefined}
		class="w-full rounded-xl border bg-surface-2 px-4 py-2.5 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted resize-y
			{error
			? 'border-accent/50 focus:border-accent focus:ring-2 focus:ring-accent/20'
			: 'border-border-subtle focus:border-border-strong focus:ring-2 focus:ring-[rgba(59,130,246,0.3)]'}
			disabled:cursor-not-allowed disabled:opacity-50"
	></textarea>
	{#if error}
		<p id="{textareaId}-error" class="text-xs text-accent" role="alert">{error}</p>
	{/if}
</div>
