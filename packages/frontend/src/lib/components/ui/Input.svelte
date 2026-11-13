<script lang="ts">
	type Props = {
		label?: string;
		error?: string;
		id?: string;
		type?: 'text' | 'email' | 'password' | 'number' | 'search' | 'tel' | 'url';
		value?: string;
		placeholder?: string;
		disabled?: boolean;
		required?: boolean;
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
		type = 'text',
		value = $bindable(''),
		placeholder,
		disabled = false,
		required = false,
		class: className = '',
		oninput,
		onblur,
		onfocus,
		...rest
	}: Props = $props();

	const fallbackId = `input-${Math.random().toString(36).slice(2, 9)}`;
	const inputId = $derived(id ?? fallbackId);

	const isPasswordType = $derived(type === 'password');
	let showPassword = $state(false);
	const effectiveType = $derived(isPasswordType && showPassword ? 'text' : type);
</script>

<div class="flex flex-col gap-1.5 {className}">
	{#if label}
		<label for={inputId} class="text-sm font-medium text-foreground">
			{label}
			{#if required}<span class="text-accent">*</span>{/if}
		</label>
	{/if}
	<div class="relative">
		<input
			{...rest}
			id={inputId}
			type={effectiveType}
			bind:value
			{placeholder}
			{disabled}
			{required}
			{oninput}
			{onblur}
			{onfocus}
			aria-invalid={error ? 'true' : undefined}
			aria-describedby={error ? `${inputId}-error` : undefined}
			class="w-full rounded-xl border bg-surface-2 px-4 py-2.5 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted
				{error
				? 'border-accent/50 focus:border-accent focus:ring-2 focus:ring-accent/20'
				: 'border-border-subtle focus:border-border-strong focus:ring-2 focus:ring-[rgba(59,130,246,0.3)]'}
				disabled:cursor-not-allowed disabled:opacity-50
				{isPasswordType ? 'pr-10' : ''}"
		/>
		{#if isPasswordType}
			<button
				type="button"
				class="absolute top-1/2 right-3 -translate-y-1/2 cursor-pointer text-muted transition-colors hover:text-foreground"
				onclick={() => (showPassword = !showPassword)}
				aria-label={showPassword ? 'Hide password' : 'Show password'}
				tabindex={-1}
			>
				{#if showPassword}
					<!-- Eye-off icon -->
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
						aria-hidden="true"
					>
						<path
							d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"
						/>
						<path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
						<path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
						<line x1="1" x2="23" y1="1" y2="23" />
					</svg>
				{:else}
					<!-- Eye icon -->
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
						aria-hidden="true"
					>
						<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
						<circle cx="12" cy="12" r="3" />
					</svg>
				{/if}
			</button>
		{/if}
	</div>
	{#if error}
		<p id="{inputId}-error" class="text-xs text-accent" role="alert">{error}</p>
	{/if}
</div>
