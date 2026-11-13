<script lang="ts">
	import type { Snippet } from 'svelte';

	type Props = {
		open: boolean;
		onclose?: () => void;
		children: Snippet;
		class?: string;
		closeOnBackdrop?: boolean;
		closeOnEscape?: boolean;
		'aria-label'?: string;
		'aria-labelledby'?: string;
		[key: string]: unknown;
	};

	let {
		open = $bindable(false),
		onclose,
		children,
		class: className = '',
		closeOnBackdrop = true,
		closeOnEscape = true,
		'aria-label': ariaLabel,
		'aria-labelledby': ariaLabelledby,
		...rest
	}: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let previouslyFocused: HTMLElement | null = null;
	let closing = $state(false);

	function close(): void {
		if (closing) return;
		closing = true;
		// Let the exit animation play, then actually close
		setTimeout(() => {
			closing = false;
			open = false;
			onclose?.();
			if (previouslyFocused) {
				previouslyFocused.focus();
				previouslyFocused = null;
			}
		}, 120);
	}

	function handleBackdropClick(e: MouseEvent): void {
		if (closeOnBackdrop && e.target === dialogEl) {
			close();
		}
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (closeOnEscape && e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	$effect(() => {
		if (!dialogEl) return;
		if (open && !dialogEl.open) {
			previouslyFocused = document.activeElement as HTMLElement | null;
			dialogEl.showModal();
		} else if (!open && dialogEl.open) {
			dialogEl.close();
		}
	});
</script>

<dialog
	bind:this={dialogEl}
	class="animate-dialog fixed inset-0 m-auto max-h-[85vh] w-full max-w-lg rounded-2xl border border-border-subtle bg-surface-2 p-0 shadow-xl backdrop:bg-foreground/40 open:flex open:flex-col {className}"
	class:dialog-closing={closing}
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
	aria-label={ariaLabel}
	aria-labelledby={ariaLabelledby}
	{...rest}
>
	{#if open}
		<div class="flex flex-col overflow-hidden">
			{@render children()}
		</div>
	{/if}
</dialog>

<style>
	.animate-dialog[open] {
		animation: dialog-in 120ms ease-out;
	}
	.animate-dialog[open]::backdrop {
		animation: backdrop-in 100ms ease-out;
	}
	.animate-dialog.dialog-closing {
		animation: dialog-out 120ms ease-in forwards;
	}
	.animate-dialog.dialog-closing::backdrop {
		animation: backdrop-out 120ms ease-in forwards;
	}
	@keyframes dialog-in {
		from {
			opacity: 0;
			transform: scale(0.96) translateY(8px);
		}
		to {
			opacity: 1;
			transform: scale(1) translateY(0);
		}
	}
	@keyframes dialog-out {
		from {
			opacity: 1;
			transform: scale(1) translateY(0);
		}
		to {
			opacity: 0;
			transform: scale(0.96) translateY(8px);
		}
	}
	@keyframes backdrop-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}
	@keyframes backdrop-out {
		from {
			opacity: 1;
		}
		to {
			opacity: 0;
		}
	}
</style>
