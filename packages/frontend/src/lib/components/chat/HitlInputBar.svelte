<script lang="ts">
	import type { HitlRequest } from '$services/sse';

	type Props = {
		hitlRequest: HitlRequest;
		onSubmit: (requestId: string, response: string) => void;
	};

	let { hitlRequest, onSubmit }: Props = $props();

	let freeTextValue = $state('');
	let submitting = $state(false);

	let hasChoices = $derived(!!hitlRequest.choices && hitlRequest.choices.length > 0);

	async function handleChoiceClick(choice: string): Promise<void> {
		if (submitting) return;
		submitting = true;
		onSubmit(hitlRequest.requestId, choice);
	}

	async function handleFreeTextSubmit(): Promise<void> {
		const trimmed = freeTextValue.trim();
		if (!trimmed || submitting) return;
		submitting = true;
		onSubmit(hitlRequest.requestId, trimmed);
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			handleFreeTextSubmit();
		}
	}
</script>

<div
	class="border-t border-accent/15 bg-accent/[0.03]"
	style="padding-bottom: calc(env(safe-area-inset-bottom, 0px) + 12px);"
	data-testid="hitl-input-bar"
>
	<!-- Prompt header -->
	<div class="flex items-center gap-2.5 px-4 pb-2 pt-3 sm:px-5 md:px-6 lg:px-8">
		<span class="h-2 w-2 animate-pulse rounded-full bg-accent"></span>
		<span class="text-[13px] font-medium text-accent">Agent needs your input</span>
	</div>

	<div class="px-4 sm:px-5 md:px-6 lg:px-8">
		<p class="mb-3 text-[14px] leading-relaxed text-foreground">{hitlRequest.prompt}</p>

		{#if hasChoices}
			<!-- Choice pills -->
			<div class="flex flex-wrap gap-2 pb-2" data-testid="hitl-bar-choices">
				{#each hitlRequest.choices as choice (choice)}
					<button
						onclick={() => handleChoiceClick(choice)}
						disabled={submitting}
						class="rounded-full border border-accent/25 bg-surface px-4 py-2 text-[14px] font-medium text-foreground transition-all hover:border-accent/50 hover:bg-accent/10 hover:text-accent active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
					>
						{choice}
					</button>
				{/each}
			</div>
		{:else}
			<!-- Free-text input -->
			<div class="flex items-end gap-2 pb-1" data-testid="hitl-bar-free-text">
				<div
					class="flex min-h-[44px] flex-1 items-end rounded-xl border border-accent/20 bg-surface transition-colors focus-within:border-accent/50 focus-within:ring-2 focus-within:ring-accent/10"
				>
					<textarea
						bind:value={freeTextValue}
						onkeydown={handleKeydown}
						disabled={submitting}
						placeholder="Type your response..."
						rows={1}
						class="max-h-32 min-h-[44px] flex-1 resize-none bg-transparent px-3.5 py-2.5 text-[14px] text-foreground placeholder:text-muted focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
					></textarea>
				</div>
				<button
					onclick={handleFreeTextSubmit}
					disabled={submitting || !freeTextValue.trim()}
					class="flex h-[44px] shrink-0 items-center justify-center rounded-xl bg-accent px-5 text-[14px] font-medium text-white transition-all hover:bg-accent/90 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
					data-testid="hitl-bar-send"
				>
					{#if submitting}
						<svg
							class="h-4 w-4 animate-spin"
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
						>
							<circle
								class="opacity-25"
								cx="12"
								cy="12"
								r="10"
								stroke="currentColor"
								stroke-width="4"
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
		{/if}
	</div>
</div>
