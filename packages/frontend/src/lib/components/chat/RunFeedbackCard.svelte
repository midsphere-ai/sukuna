<script lang="ts">
	import { slide, fade, fly } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import { submitRunFeedback } from '$api/chat';
	import { toasts } from '$stores/toast';

	type Props = {
		conversationId: string;
		onSubmitted?: (rating: number) => void;
		onDismiss?: () => void;
	};

	let { conversationId, onSubmitted, onDismiss }: Props = $props();

	let hoveredStar = $state(0);
	let selectedRating = $state(0);
	let submitting = $state(false);
	let error = $state('');

	async function handleRate(rating: number): Promise<void> {
		selectedRating = rating;
		submitting = true;
		error = '';
		try {
			await submitRunFeedback(conversationId, rating);
			onSubmitted?.(rating);
			toasts.success('Thanks for your feedback!');
			onDismiss?.();
		} catch {
			error = 'Failed to submit rating';
			submitting = false;
		}
	}
</script>

<div transition:fly={{ y: 12, duration: 300, easing: cubicOut }} class="mt-1 mb-2">
	<div
		class="inline-flex items-center gap-3 rounded-lg border border-border-subtle bg-surface px-3 py-2"
	>
		<span class="text-xs text-muted">How did the agent do?</span>
		<div class="flex gap-0.5" role="radiogroup" aria-label="Rate agent performance">
			{#each [1, 2, 3, 4, 5] as star, i}
				<button
					type="button"
					class="cursor-pointer p-0.5 transition-transform hover:scale-110 disabled:opacity-50"
					style="animation: scaleIn 0.2s {100 + i * 50}ms var(--ease-spring) both"
					disabled={submitting}
					onmouseenter={() => (hoveredStar = star)}
					onmouseleave={() => (hoveredStar = 0)}
					onclick={() => handleRate(star)}
					aria-label="{star} star{star > 1 ? 's' : ''}"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill={star <= (hoveredStar || selectedRating) ? 'currentColor' : 'none'}
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
						stroke-linejoin="round"
						class={star <= (hoveredStar || selectedRating) ? 'text-accent' : 'text-muted'}
					>
						<polygon
							points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
						/>
					</svg>
				</button>
			{/each}
		</div>
		<button
			type="button"
			class="ml-1 cursor-pointer p-0.5 text-muted transition-colors hover:text-foreground"
			onclick={() => onDismiss?.()}
			aria-label="Dismiss feedback"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="14"
				height="14"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<line x1="18" x2="6" y1="6" y2="18" />
				<line x1="6" x2="18" y1="6" y2="18" />
			</svg>
		</button>
	</div>
	{#if error}
		<p transition:fade class="mt-1 text-xs text-accent">{error}</p>
	{/if}
</div>
