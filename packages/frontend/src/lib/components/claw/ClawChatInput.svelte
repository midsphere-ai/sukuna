<script lang="ts">
	let {
		disabled = false,
		sending = false,
		placeholder = 'Type a message...',
		onsend
	}: {
		disabled?: boolean;
		sending?: boolean;
		placeholder?: string;
		onsend: (text: string) => void;
	} = $props();

	let text = $state('');

	function handleSubmit(): void {
		const trimmed = text.trim();
		if (!trimmed || disabled || sending) return;
		onsend(trimmed);
		text = '';
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSubmit();
		}
	}
</script>

<div class="flex gap-2">
	<textarea
		bind:value={text}
		onkeydown={handleKeydown}
		{placeholder}
		rows="2"
		disabled={disabled || sending}
		class="w-full resize-none rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm text-foreground outline-none placeholder:text-muted disabled:opacity-50"
	></textarea>
	<button
		onclick={handleSubmit}
		disabled={!text.trim() || disabled || sending}
		class="shrink-0 self-end rounded-xl bg-foreground px-6 py-3 text-sm font-medium text-background hover:opacity-70 disabled:opacity-50"
	>
		{#if sending}
			<svg
				class="h-4 w-4 animate-spin"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				aria-hidden="true"
			>
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
				></circle>
				<path
					class="opacity-75"
					fill="currentColor"
					d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
				></path>
			</svg>
		{:else}
			Send
		{/if}
	</button>
</div>
