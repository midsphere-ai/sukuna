<script lang="ts">
	import { toasts } from '$stores/toast';
	import type { ToastType } from '$stores/toast';
	import { fly } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { cubicOut } from 'svelte/easing';

	const typeClasses: Record<ToastType, string> = {
		success: 'border-success/30 bg-success/10 text-success',
		error: 'border-accent/30 bg-accent/10 text-accent',
		warning: 'border-yellow-500/30 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400',
		info: 'border-accent/30 bg-accent/10 text-accent'
	};

	const progressColors: Record<ToastType, string> = {
		success: 'bg-success/40',
		error: 'bg-accent/40',
		warning: 'bg-yellow-500/40',
		info: 'bg-accent/40'
	};

	const icons: Record<ToastType, string> = {
		success: '✓',
		error: '✕',
		warning: '!',
		info: 'i'
	};
</script>

{#if $toasts.length > 0}
	<div
		class="fixed right-4 bottom-4 z-[9999] flex flex-col gap-2"
		role="region"
		aria-label="Notifications"
	>
		{#each $toasts as toast (toast.id)}
			<div
				class="relative flex min-w-72 max-w-sm items-start gap-3 overflow-hidden rounded-xl border bg-background px-4 py-3 shadow-sm {typeClasses[
					toast.type
				]}"
				class:toast-exit={toast.exiting}
				role="alert"
				in:fly={{ x: 120, duration: 250, easing: cubicOut }}
				animate:flip={{ duration: 200, easing: cubicOut }}
			>
				<span
					class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-medium {typeClasses[
						toast.type
					]}"
				>
					{icons[toast.type]}
				</span>
				<p class="flex-1 text-sm text-foreground">{toast.message}</p>
				<button
					type="button"
					class="shrink-0 cursor-pointer text-muted transition-colors hover:text-foreground"
					onclick={() => toasts.dismiss(toast.id)}
					aria-label="Dismiss notification"
				>
					✕
				</button>
				{#if toast.duration > 0 && !toast.exiting}
					<div
						class="absolute right-0 bottom-0 left-0 h-0.5 origin-left {progressColors[toast.type]}"
						style="animation: toastProgress {toast.duration}ms linear forwards"
					></div>
				{/if}
			</div>
		{/each}
	</div>
{/if}
