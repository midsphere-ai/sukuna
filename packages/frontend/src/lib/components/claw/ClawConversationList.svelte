<script lang="ts">
	import { fade } from 'svelte/transition';
	import { formatDate } from '$utils/formatDate';
	import type { ClawConversation } from '$api/claw';

	let {
		conversations = [],
		loading = false
	}: {
		conversations: ClawConversation[];
		loading: boolean;
	} = $props();
</script>

<div class="rounded-xl border border-border p-4" in:fade={{ duration: 100, delay: 30 }}>
	<h2 class="mb-3 text-sm font-medium text-foreground">Conversations</h2>

	{#if loading && conversations.length === 0}
		<div class="flex items-center justify-center py-6">
			<svg
				class="h-5 w-5 animate-spin text-muted"
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
		</div>
	{:else if conversations.length === 0}
		<p class="py-4 text-center text-sm text-muted">
			No conversations yet. Send a message to start one.
		</p>
	{:else}
		<div class="space-y-1">
			{#each conversations as conversation (conversation.id)}
				<a
					href="/claw/{conversation.id}"
					class="flex items-center justify-between rounded-lg px-3 py-2.5 transition-colors hover:bg-surface"
				>
					<div class="min-w-0 flex-1">
						<p class="truncate text-sm font-medium text-foreground">
							{conversation.title || 'Untitled'}
						</p>
						<p class="text-xs text-muted">{formatDate(conversation.updated_at)}</p>
					</div>
					{#if conversation.on_going}
						<span
							class="ml-2 shrink-0 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700"
						>
							Active
						</span>
					{/if}
				</a>
			{/each}
		</div>
	{/if}
</div>
