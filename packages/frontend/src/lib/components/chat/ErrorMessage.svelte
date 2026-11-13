<script lang="ts">
	import type { ErrorMessage as ErrorMessageType } from '$services/sse';

	type Props = {
		message: ErrorMessageType;
		onRetry?: () => void;
	};

	let { message, onRetry }: Props = $props();
</script>

<div class="py-1.5" data-testid="error-message">
	<div class="flex min-w-0">
		<div class="min-w-0 flex-1 flex items-center gap-2">
			<span class="text-[14px] text-accent break-words">{message.message}</span>
			{#if onRetry}
				<button
					onclick={onRetry}
					class="flex-shrink-0 rounded-md px-2 py-0.5 text-[14px] font-medium text-accent hover:bg-accent/10 transition-colors"
				>
					Retry
				</button>
			{/if}
		</div>
	</div>
</div>
