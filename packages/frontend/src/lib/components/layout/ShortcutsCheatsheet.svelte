<script lang="ts">
	import Dialog from '$components/ui/Dialog.svelte';
	import {
		shortcuts,
		formatLabel,
		getCategoryLabel,
		cheatsheetOpen,
		type Shortcut
	} from '$stores/shortcuts';

	let open = $state(false);

	cheatsheetOpen.subscribe((v) => {
		open = v;
	});

	function handleClose(): void {
		cheatsheetOpen.set(false);
	}

	function onOpenChange(v: boolean): void {
		if (!v) handleClose();
	}

	$effect(() => {
		onOpenChange(open);
	});

	const categories: Shortcut['category'][] = ['navigation', 'chat', 'panels', 'general'];

	function shortcutsForCategory(category: Shortcut['category']): Shortcut[] {
		return shortcuts.filter((s) => s.category === category);
	}
</script>

<Dialog bind:open onclose={handleClose} class="max-w-xl">
	<div class="p-6">
		<div class="mb-6 flex items-center justify-between">
			<h2 class="font-display text-xl text-foreground dark:text-background">Keyboard Shortcuts</h2>
			<button
				class="rounded-lg p-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-foreground dark:hover:text-background"
				onclick={handleClose}
				aria-label="Close"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d="M18 6 6 18" />
					<path d="m6 6 12 12" />
				</svg>
			</button>
		</div>

		<div class="grid grid-cols-1 gap-6 sm:grid-cols-2">
			{#each categories as category (category)}
				{@const items = shortcutsForCategory(category)}
				{#if items.length > 0}
					<div>
						<h3 class="mb-3 text-xs font-medium uppercase tracking-wider text-muted">
							{getCategoryLabel(category)}
						</h3>
						<div class="space-y-2">
							{#each items as shortcut (shortcut.keys.join('-'))}
								<div class="flex items-center justify-between rounded-lg px-2 py-1.5">
									<span class="text-sm text-foreground dark:text-background">
										{shortcut.description}
									</span>
									<kbd
										class="ml-4 shrink-0 rounded-md border border-border-strong bg-surface-2 px-2 py-0.5 font-mono text-xs text-muted dark:border-background/[0.12]"
									>
										{formatLabel(shortcut)}
									</kbd>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			{/each}
		</div>

		<div class="mt-6 border-t border-border pt-4 dark:border-background/[0.08]">
			<p class="text-center text-xs text-muted">
				Press <kbd
					class="rounded border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-xs dark:border-background/[0.12]"
					>?</kbd
				>
				or
				<kbd
					class="rounded border border-border-strong bg-surface-2 px-1.5 py-0.5 font-mono text-xs dark:border-background/[0.12]"
					>Ctrl+/</kbd
				> to toggle this panel
			</p>
		</div>
	</div>
</Dialog>
