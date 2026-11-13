<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import { Skeleton } from '$components/ui';
	import type { UserAddon, UserMCPConfig } from '$api/types';
	import type { SkillCatalog } from '$api/skills';

	interface Props {
		loading: boolean;
		availableAddons: UserAddon[];
		selectedAddonIds: SvelteSet<string>;
		addonLoading: boolean;
		availableMCPs: UserMCPConfig[];
		selectedMCPIds: SvelteSet<string>;
		mcpLoading: boolean;
		availableSkills?: SkillCatalog[];
		selectedSkillIds?: SvelteSet<string>;
		skillLoading?: boolean;
		onfileselect: (files: FileList) => void;
	}

	let {
		loading,
		availableAddons,
		selectedAddonIds,
		addonLoading,
		availableMCPs,
		selectedMCPIds,
		mcpLoading,
		availableSkills = [],
		selectedSkillIds = new SvelteSet<string>(),
		skillLoading = false,
		onfileselect
	}: Props = $props();

	let toolsPopoverOpen = $state(false);
	let fileInputEl: HTMLInputElement | undefined = $state(undefined);

	let selectedAddonCount = $derived(selectedAddonIds.size);
	let selectedMCPCount = $derived(selectedMCPIds.size);
	let selectedSkillCount = $derived(selectedSkillIds.size);

	function toggleAddon(addonId: string): void {
		if (selectedAddonIds.has(addonId)) {
			selectedAddonIds.delete(addonId);
		} else {
			selectedAddonIds.add(addonId);
		}
	}

	function toggleMCP(mcpId: string): void {
		if (selectedMCPIds.has(mcpId)) {
			selectedMCPIds.delete(mcpId);
		} else {
			selectedMCPIds.add(mcpId);
		}
	}

	function toggleSkill(slug: string): void {
		if (selectedSkillIds.has(slug)) {
			selectedSkillIds.delete(slug);
		} else {
			selectedSkillIds.add(slug);
		}
	}

	function handleFileInputChange(e: Event): void {
		const input = e.target as HTMLInputElement;
		if (input.files) {
			onfileselect(input.files);
		}
		input.value = '';
	}

	function handleWindowClick(e: MouseEvent): void {
		const target = e.target as HTMLElement;
		if (toolsPopoverOpen && !target.closest('[data-tools-popover]')) {
			toolsPopoverOpen = false;
		}
	}
</script>

<svelte:window onclick={handleWindowClick} />

<div class="relative" data-tools-popover>
	<button
		onclick={() => (toolsPopoverOpen = !toolsPopoverOpen)}
		disabled={loading}
		class="flex h-8 w-8 items-center justify-center rounded-lg transition-colors disabled:opacity-50 {selectedAddonCount >
			0 ||
		selectedMCPCount > 0 ||
		selectedSkillCount > 0
			? 'text-accent hover:bg-accent/10'
			: 'text-muted hover:bg-surface-2 hover:text-foreground'}"
		aria-label="Attach files and tools"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="18"
			height="18"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<path d="M5 12h14" />
			<path d="M12 5v14" />
		</svg>
	</button>
	<input
		bind:this={fileInputEl}
		type="file"
		multiple
		class="hidden"
		onchange={handleFileInputChange}
		aria-label="File input"
	/>

	{#if toolsPopoverOpen}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<div
			class="absolute bottom-full left-0 z-50 mb-2 w-80 max-h-[60vh] overflow-y-auto rounded-xl border border-border-subtle bg-surface-2 shadow-sm lg:bottom-auto lg:top-full lg:mb-0 lg:mt-2"
			onclick={(e) => e.stopPropagation()}
		>
			<!-- Attach file row -->
			<button
				onclick={() => {
					fileInputEl?.click();
					toolsPopoverOpen = false;
				}}
				class="flex w-full items-center gap-3 rounded-t-xl px-4 py-3 text-left transition-colors hover:bg-surface-2"
			>
				<div
					class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<path
							d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"
						/>
					</svg>
				</div>
				<div>
					<div class="text-sm font-medium text-foreground">Attach files</div>
					<div class="text-xs text-muted">Upload images, documents, up to 50MB</div>
				</div>
			</button>

			<div class="border-t border-border-subtle"></div>

			<!-- Addons section -->
			<div class="px-4 py-3">
				<div class="mb-2 flex items-center justify-between">
					<span class="text-xs font-medium text-muted">Addons</span>
					{#if selectedAddonCount > 0}
						<span class="text-[10px] font-medium text-accent">{selectedAddonCount} selected</span>
					{/if}
				</div>
				{#if addonLoading}
					<div class="flex flex-wrap gap-2 py-1">
						<Skeleton class="rounded-full" width="80px" height="28px" />
						<Skeleton class="rounded-full" width="96px" height="28px" stagger={1} />
						<Skeleton class="rounded-full" width="72px" height="28px" stagger={2} />
					</div>
				{:else if availableAddons.length === 0}
					<p class="py-2 text-xs text-muted">No authorized addons. Install some from Connectors.</p>
				{:else}
					<div class="flex flex-wrap gap-2">
						{#each availableAddons as addon (addon.id)}
							<button
								onclick={() => toggleAddon(addon.id)}
								class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-150 {selectedAddonIds.has(
									addon.id
								)
									? 'border-accent bg-accent/10 text-accent'
									: 'border-border-subtle bg-surface-2/60 text-foreground hover:border-border hover:bg-surface-2'}"
								aria-pressed={selectedAddonIds.has(addon.id)}
							>
								{#if addon.enabled_addon.logo}
									<img src={addon.enabled_addon.logo} alt="" class="h-4 w-4 rounded-sm" />
								{/if}
								{addon.enabled_addon.name}
								{#if selectedAddonIds.has(addon.id)}
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="12"
										height="12"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="3"
										stroke-linecap="round"
										stroke-linejoin="round"
									>
										<polyline points="20 6 9 17 4 12" />
									</svg>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<div class="border-t border-border-subtle"></div>

			<!-- MCPs section -->
			<div class="px-4 py-3">
				<div class="mb-2 flex items-center justify-between">
					<span class="text-xs font-medium text-muted">MCPs</span>
					{#if selectedMCPCount > 0}
						<span class="text-[10px] font-medium text-accent">{selectedMCPCount} selected</span>
					{/if}
				</div>
				{#if mcpLoading}
					<div class="flex flex-col gap-2 py-1">
						<div class="flex items-center gap-3">
							<Skeleton class="shrink-0 rounded-lg" width="32px" height="32px" />
							<div class="flex flex-1 flex-col gap-1.5">
								<Skeleton class="rounded" width="70%" height="10px" />
								<Skeleton class="rounded" width="40%" height="8px" stagger={1} />
							</div>
						</div>
					</div>
				{:else if availableMCPs.length === 0}
					<p class="py-2 text-xs text-muted">No custom MCPs configured. Add them in Settings.</p>
				{:else}
					<div class="flex flex-col gap-1">
						{#each availableMCPs as mcp (mcp.id)}
							<button
								onclick={() => toggleMCP(mcp.id)}
								class="flex items-center gap-3 rounded-lg px-3 py-2 text-left transition-all duration-150 {selectedMCPIds.has(
									mcp.id
								)
									? 'bg-accent/10'
									: 'hover:bg-surface-2'}"
								aria-pressed={selectedMCPIds.has(mcp.id)}
							>
								<div
									class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg {selectedMCPIds.has(
										mcp.id
									)
										? 'bg-accent/20 text-accent'
										: 'bg-surface-2 text-muted'}"
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="16"
										height="16"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										stroke-linecap="round"
										stroke-linejoin="round"
									>
										<path
											d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"
										/>
									</svg>
								</div>
								<div class="min-w-0 flex-1">
									<div
										class="truncate text-xs font-medium {selectedMCPIds.has(mcp.id)
											? 'text-accent'
											: 'text-foreground'}"
									>
										{mcp.server_name}
									</div>
									{#if mcp.description}
										<div class="truncate text-[10px] text-muted">{mcp.description}</div>
									{/if}
								</div>
								{#if selectedMCPIds.has(mcp.id)}
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="14"
										height="14"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="3"
										stroke-linecap="round"
										stroke-linejoin="round"
										class="shrink-0 text-accent"
									>
										<polyline points="20 6 9 17 4 12" />
									</svg>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>

			<div class="border-t border-border-subtle"></div>

			<!-- Skills section -->
			<div class="px-4 py-3">
				<div class="mb-2 flex items-center justify-between">
					<span class="text-xs font-medium text-muted">Skills</span>
					{#if selectedSkillCount > 0}
						<span class="text-[10px] font-medium text-accent">{selectedSkillCount} selected</span>
					{/if}
				</div>
				{#if skillLoading}
					<div class="flex flex-col gap-2 py-1">
						<div class="flex items-center gap-3">
							<Skeleton class="shrink-0 rounded-lg" width="32px" height="32px" />
							<div class="flex flex-1 flex-col gap-1.5">
								<Skeleton class="rounded" width="70%" height="10px" />
								<Skeleton class="rounded" width="40%" height="8px" stagger={1} />
							</div>
						</div>
					</div>
				{:else if availableSkills.length === 0}
					<p class="py-2 text-xs text-muted">No installed skills. Browse the Skills marketplace.</p>
				{:else}
					<div class="flex flex-col gap-1">
						{#each availableSkills as skill (skill.slug)}
							<button
								onclick={() => toggleSkill(skill.slug)}
								class="flex items-center gap-3 rounded-lg px-3 py-2 text-left transition-all duration-150 {selectedSkillIds.has(
									skill.slug
								)
									? 'bg-accent/10'
									: 'hover:bg-surface-2'}"
								aria-pressed={selectedSkillIds.has(skill.slug)}
							>
								<div
									class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg {selectedSkillIds.has(
										skill.slug
									)
										? 'bg-accent/20 text-accent'
										: 'bg-surface-2 text-muted'}"
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="16"
										height="16"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										stroke-linecap="round"
										stroke-linejoin="round"
									>
										<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
									</svg>
								</div>
								<div class="min-w-0 flex-1">
									<div
										class="truncate text-xs font-medium {selectedSkillIds.has(skill.slug)
											? 'text-accent'
											: 'text-foreground'}"
									>
										{skill.name}
									</div>
									{#if skill.description}
										<div class="truncate text-[10px] text-muted">{skill.description}</div>
									{/if}
								</div>
								{#if selectedSkillIds.has(skill.slug)}
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="14"
										height="14"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="3"
										stroke-linecap="round"
										stroke-linejoin="round"
										class="shrink-0 text-accent"
									>
										<polyline points="20 6 9 17 4 12" />
									</svg>
								{/if}
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
