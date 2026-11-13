<script lang="ts">
	type TabOption = {
		id: string;
		label: string;
		description: string;
	};

	type Props = {
		existing: TabOption[];
		suggested: TabOption[];
		onjump: (id: string) => void;
		onadd: (id: string) => void;
	};

	let { existing, suggested, onjump, onadd }: Props = $props();

	let search = $state('');

	function matches(t: TabOption): boolean {
		if (!search) return true;
		const s = search.toLowerCase();
		return t.label.toLowerCase().includes(s) || t.description.toLowerCase().includes(s);
	}

	function handleJump(id: string): void {
		onjump(id);
	}

	function handleAdd(id: string): void {
		onadd(id);
	}
</script>

<div class="h-full overflow-auto bg-background">
	<div class="mx-auto max-w-xl px-6 pt-10">
		<input
			type="text"
			bind:value={search}
			placeholder="Search for tools & files..."
			class="w-full rounded-lg border border-border-strong bg-surface px-4 py-2.5 text-sm text-foreground outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/15"
		/>

		<div class="mt-6 space-y-6">
			{#if existing.filter(matches).length > 0}
				<div>
					<p class="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-muted">
						Jump to existing tab
					</p>
					{#each existing.filter(matches) as t (t.id)}
						<button
							type="button"
							class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-surface-2"
							onclick={() => handleJump(t.id)}
						>
							<div
								class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-muted text-xs font-medium"
							>
								{t.label.slice(0, 2)}
							</div>
							<div class="min-w-0 flex-1">
								<p class="text-sm font-medium text-foreground">{t.label}</p>
								<p class="truncate text-xs text-muted">{t.description}</p>
							</div>
						</button>
					{/each}
				</div>
			{/if}

			{#if suggested.filter(matches).length > 0}
				<div>
					<p class="mb-2 text-[11.5px] font-medium uppercase tracking-wider text-muted">
						Suggested
					</p>
					{#each suggested.filter(matches) as t (t.id)}
						<button
							type="button"
							class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-surface-2"
							onclick={() => handleAdd(t.id)}
						>
							<div
								class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-muted text-xs font-medium"
							>
								{t.label.slice(0, 2)}
							</div>
							<div class="min-w-0 flex-1">
								<p class="text-sm font-medium text-foreground">{t.label}</p>
								<p class="truncate text-xs text-muted">{t.description}</p>
							</div>
						</button>
					{/each}
				</div>
			{/if}

			{#if existing.filter(matches).length === 0 && suggested.filter(matches).length === 0}
				<p class="py-8 text-center text-sm text-muted">No matching tools found</p>
			{/if}
		</div>
	</div>
</div>
