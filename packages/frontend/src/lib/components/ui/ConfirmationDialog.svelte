<script lang="ts">
	type Props = {
		open: boolean;
		title: string;
		message: string;
		confirmLabel?: string;
		cancelLabel?: string;
		destructive?: boolean;
		onconfirm: () => void;
		oncancel: () => void;
	};

	let {
		open = false,
		title,
		message,
		confirmLabel = 'Confirm',
		cancelLabel = 'Cancel',
		destructive = false,
		onconfirm,
		oncancel
	}: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let previouslyFocused: HTMLElement | null = null;

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			e.preventDefault();
			oncancel();
		}
	}

	function handleBackdropClick(e: MouseEvent): void {
		if (e.target === dialogEl) {
			oncancel();
		}
	}

	$effect(() => {
		if (!dialogEl) return;
		if (open && !dialogEl.open) {
			previouslyFocused = document.activeElement as HTMLElement | null;
			dialogEl.showModal();
		} else if (!open && dialogEl.open) {
			dialogEl.close();
			if (previouslyFocused) {
				previouslyFocused.focus();
				previouslyFocused = null;
			}
		}
	});
</script>

<dialog
	bind:this={dialogEl}
	class="animate-dialog fixed inset-0 m-auto w-full max-w-sm rounded-2xl border border-border-subtle bg-surface-2 p-0 shadow-xl backdrop:bg-foreground/40"
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
	aria-labelledby="confirm-dialog-title"
	aria-describedby="confirm-dialog-message"
>
	{#if open}
		<div class="p-6">
			<h3 id="confirm-dialog-title" class="text-base font-medium text-foreground">{title}</h3>
			<p id="confirm-dialog-message" class="mt-2 text-sm text-subtle">{message}</p>
			<div class="mt-5 flex justify-end gap-2">
				<button
					onclick={oncancel}
					class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface"
				>
					{cancelLabel}
				</button>
				<button
					onclick={onconfirm}
					class={destructive
						? 'rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-70'
						: 'rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:opacity-70'}
				>
					{confirmLabel}
				</button>
			</div>
		</div>
	{/if}
</dialog>

<style>
	.animate-dialog[open] {
		animation: dialog-in 100ms ease-out;
	}
	.animate-dialog[open]::backdrop {
		animation: backdrop-in 80ms ease-out;
	}
	@keyframes dialog-in {
		from {
			opacity: 0;
			transform: scale(0.97);
		}
		to {
			opacity: 1;
			transform: scale(1);
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
</style>
