<script lang="ts">
	import { Dialog } from '$components/ui';
	import { listOrganizations, type Organization } from '$api/organizations';
	import { moveProject } from '$api/projects';
	import { toasts } from '$stores/toast';
	import { invalidateProjects } from '$stores/projects';

	type Props = {
		open: boolean;
		projectId: string;
		projectTitle: string;
		currentOrgId: string | null;
		onclose: () => void;
		onmoved?: (orgId: string | null) => void;
	};

	let {
		open = $bindable(false),
		projectId,
		projectTitle,
		currentOrgId,
		onclose,
		onmoved
	}: Props = $props();

	let orgs: Organization[] = $state([]);
	let loading = $state(false);
	let moving = $state(false);
	let selectedOrgId: string | null = $state(null);
	let warnings: string[] = $state([]);

	$effect(() => {
		if (open) {
			selectedOrgId = null;
			warnings = [];
			loadOrgs();
		}
	});

	async function loadOrgs(): Promise<void> {
		loading = true;
		try {
			orgs = await listOrganizations();
		} catch {
			toasts.error('Failed to load organizations');
		} finally {
			loading = false;
		}
	}

	async function handleMove(): Promise<void> {
		moving = true;
		warnings = [];
		try {
			const result = await moveProject(projectId, selectedOrgId);
			if (result.warnings.length > 0) {
				warnings = result.warnings;
			}
			invalidateProjects();
			toasts.success(
				selectedOrgId
					? `Moved "${projectTitle}" to organization`
					: `Moved "${projectTitle}" to personal space`
			);
			onmoved?.(selectedOrgId);
			if (warnings.length === 0) {
				open = false;
				onclose();
			}
		} catch {
			toasts.error('Failed to move project');
		} finally {
			moving = false;
		}
	}

	function handleClose(): void {
		open = false;
		onclose();
	}

	// Filter out the current org from options
	let availableOrgs = $derived(currentOrgId ? orgs.filter((o) => o.id !== currentOrgId) : orgs);
	let showPersonalOption = $derived(currentOrgId !== null);
</script>

<Dialog bind:open {onclose} aria-label="Move project to organization">
	<!-- Header -->
	<div class="flex items-center justify-between border-b border-border-subtle px-5 py-4">
		<h2 class="text-base font-medium text-foreground">Move Project</h2>
		<button
			onclick={handleClose}
			class="rounded-md p-1 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
			aria-label="Close"
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
				<path d="M18 6L6 18" />
				<path d="M6 6l12 12" />
			</svg>
		</button>
	</div>

	<!-- Body -->
	<div class="space-y-4 overflow-y-auto px-5 py-4">
		<p class="text-sm text-subtle">
			Choose where to move <strong class="text-foreground">{projectTitle}</strong>. All
			conversations and files will remain intact.
		</p>

		{#if loading}
			<div class="flex items-center justify-center py-8">
				<div
					class="h-5 w-5 animate-spin rounded-full border-2 border-border-strong border-t-accent"
				></div>
			</div>
		{:else}
			<div class="space-y-1">
				{#if showPersonalOption}
					<button
						onclick={() => (selectedOrgId = null)}
						class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors {selectedOrgId ===
						null
							? 'bg-accent/10 ring-1 ring-accent/30'
							: 'hover:bg-surface-2'}"
					>
						<div
							class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface text-sm"
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
								class="text-muted"
							>
								<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
								<circle cx="12" cy="7" r="4" />
							</svg>
						</div>
						<div>
							<p class="text-sm font-medium text-foreground">Personal Space</p>
							<p class="text-xs text-muted">Move back to your personal projects</p>
						</div>
					</button>
				{/if}

				{#each availableOrgs as org (org.id)}
					<button
						onclick={() => (selectedOrgId = org.id)}
						class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors {selectedOrgId ===
						org.id
							? 'bg-accent/10 ring-1 ring-accent/30'
							: 'hover:bg-surface-2'}"
						disabled={org.your_role !== 'owner' && org.your_role !== 'admin'}
					>
						<div
							class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface text-sm font-medium text-subtle"
						>
							{org.name.charAt(0).toUpperCase()}
						</div>
						<div class="min-w-0 flex-1">
							<p class="truncate text-sm font-medium text-foreground">{org.name}</p>
							<p class="text-xs text-muted">
								{org.member_count} member{org.member_count !== 1 ? 's' : ''}
								{#if org.your_role !== 'owner' && org.your_role !== 'admin'}
									&middot; Admin role required
								{/if}
							</p>
						</div>
					</button>
				{/each}

				{#if availableOrgs.length === 0 && !showPersonalOption}
					<p class="py-4 text-center text-sm text-muted">
						No organizations available. Create or join an organization first.
					</p>
				{/if}
			</div>
		{/if}

		<!-- Warnings -->
		{#if warnings.length > 0}
			<div
				class="rounded-lg border border-amber-200 bg-amber-50/50 p-3 dark:border-amber-500/20 dark:bg-amber-500/5"
			>
				<p class="mb-1 text-xs font-medium text-amber-800 dark:text-amber-400">Warnings</p>
				{#each warnings as warning}
					<p class="text-xs text-amber-700 dark:text-amber-300">{warning}</p>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Footer -->
	<div class="flex items-center justify-end gap-3 border-t border-border-subtle px-5 py-4">
		<button
			onclick={handleClose}
			class="rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
		>
			Cancel
		</button>
		<button
			onclick={handleMove}
			disabled={moving || (selectedOrgId === null && !showPersonalOption)}
			class="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
		>
			{moving ? 'Moving...' : 'Move Project'}
		</button>
	</div>
</Dialog>
