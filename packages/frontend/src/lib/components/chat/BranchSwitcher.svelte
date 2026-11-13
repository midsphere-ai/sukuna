<script lang="ts">
	import { goto } from '$app/navigation';
	import { getConversationIcon } from '$stores/conversations';
	import type { BranchInfo } from '$stores/branches';

	type Props = {
		conversationId: string;
		parentConversationId: string | null;
		branches: BranchInfo[];
	};

	let { conversationId, parentConversationId, branches }: Props = $props();

	let open = $state(false);

	let totalBranches = $derived(branches.length);

	function toggleDropdown(): void {
		open = !open;
	}

	function closeDropdown(): void {
		open = false;
	}

	function navigateTo(id: string): void {
		open = false;
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic branch navigation
		goto(`/chat/${id}`);
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			open = false;
		}
	}
</script>

{#if totalBranches > 0 || parentConversationId}
	<div class="relative" data-testid="branch-switcher">
		<button
			onclick={toggleDropdown}
			class="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
			aria-expanded={open}
			aria-haspopup="true"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="12"
				height="12"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<circle cx="12" cy="18" r="3" />
				<circle cx="6" cy="6" r="3" />
				<circle cx="18" cy="6" r="3" />
				<path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9" />
				<path d="M12 12v3" />
			</svg>
			{#if parentConversationId}
				Branch
			{:else}
				{totalBranches} branch{totalBranches !== 1 ? 'es' : ''}
			{/if}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="10"
				height="10"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2.5"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="transition-transform {open ? 'rotate-180' : ''}"
			>
				<path d="m6 9 6 6 6-6" />
			</svg>
		</button>

		{#if open}
			<!-- Backdrop -->
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="fixed inset-0 z-40" onclick={closeDropdown} onkeydown={handleKeydown}></div>

			<!-- Dropdown -->
			<div
				class="absolute left-0 top-full z-50 mt-1 min-w-[200px] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-lg"
				role="menu"
			>
				<!-- Parent conversation link -->
				{#if parentConversationId}
					<button
						onclick={() => navigateTo(parentConversationId)}
						class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition-colors hover:bg-surface-2"
						role="menuitem"
					>
						<img
							src={getConversationIcon(parentConversationId)}
							alt=""
							class="h-4 w-4 shrink-0 rounded opacity-60"
							aria-hidden="true"
						/>
						<span class="flex min-w-0 flex-1 flex-col">
							<span class="truncate font-medium text-foreground">Original conversation</span>
							<span class="text-[10.5px] text-muted">{parentConversationId.slice(0, 8)}...</span>
						</span>
					</button>
				{/if}

				<!-- Branch list -->
				{#each branches as branch (branch.branchConversationId)}
					{@const isCurrent = branch.branchConversationId === conversationId}
					<button
						onclick={() => navigateTo(branch.branchConversationId)}
						class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs transition-colors
							{isCurrent ? 'bg-accent/5 text-foreground' : 'hover:bg-surface-2 text-foreground'}"
						role="menuitem"
						aria-current={isCurrent ? 'page' : undefined}
					>
						<img
							src={getConversationIcon(branch.branchConversationId)}
							alt=""
							class="h-4 w-4 shrink-0 rounded opacity-60"
							aria-hidden="true"
						/>
						<span class="flex min-w-0 flex-1 flex-col">
							<span class="truncate font-medium">
								Branch {isCurrent ? '(current)' : ''}
							</span>
							<span class="text-[10.5px] text-muted">
								from message #{branch.fromMessageIndex + 1}
							</span>
						</span>
					</button>
				{/each}
			</div>
		{/if}
	</div>
{/if}
