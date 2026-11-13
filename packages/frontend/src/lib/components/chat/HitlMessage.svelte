<script lang="ts">
	import type { HitlMessage as HitlMessageType } from '$services/sse';

	type Props = {
		message: HitlMessageType;
	};

	let { message }: Props = $props();

	let hasResponded = $derived(!!message.response);
</script>

<div class="py-2" data-testid="hitl-message">
	<div class="flex min-w-0">
		<div class="min-w-0 flex-1 space-y-2">
			<!-- Prompt text -->
			<p class="text-[14px] leading-relaxed text-foreground/80">{message.prompt}</p>

			{#if hasResponded}
				<!-- Submitted response display -->
				<div
					class="flex items-center gap-2 rounded-lg bg-success/8 px-3 py-2"
					data-testid="hitl-response"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="13"
						height="13"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="shrink-0 text-success"
					>
						<polyline points="20 6 9 17 4 12" />
					</svg>
					<span class="text-xs text-subtle">
						Your response: <span class="font-medium text-foreground">{message.response}</span>
					</span>
				</div>
			{:else}
				<!-- Waiting indicator — input is at the bottom bar -->
				<div class="flex items-center gap-2" data-testid="hitl-waiting">
					<span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"></span>
					<span class="text-xs text-accent">Respond below</span>
				</div>
			{/if}
		</div>
	</div>
</div>
