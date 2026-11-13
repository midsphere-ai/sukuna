<script lang="ts">
	import { fade } from 'svelte/transition';
	import { goto } from '$app/navigation';
	import { toasts } from '$stores/toast';
	import {
		freezeOrg,
		unfreezeOrg,
		getDeletionPreview,
		deleteOrg,
		updateOrgSlug,
		type Organization,
		type DeletionPreview,
		type SlugChangeResult
	} from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	const isAdmin = $derived(org.your_role === 'admin' || org.your_role === 'owner');

	// Slug state
	let newSlug = $state('');
	let slugSaving = $state(false);
	let slugResult: SlugChangeResult | null = $state(null);

	// Freeze state
	let freezing = $state(false);
	let showFreezeConfirm = $state(false);

	// Delete state
	let showDeleteFlow = $state(false);
	let deletionPreview: DeletionPreview | null = $state(null);
	let previewLoading = $state(false);
	let confirmName = $state('');
	let deleting = $state(false);

	async function handleSlugChange() {
		if (!newSlug.trim()) return;
		slugSaving = true;
		slugResult = null;
		try {
			slugResult = await updateOrgSlug(orgId, { new_slug: newSlug.trim() });
			toasts.success('Organization slug updated.');
			newSlug = '';
		} catch {
			toasts.error('Failed to update slug.');
		} finally {
			slugSaving = false;
		}
	}

	async function handleFreeze() {
		freezing = true;
		try {
			await freezeOrg(orgId);
			toasts.success('Organization frozen.');
			showFreezeConfirm = false;
		} catch {
			toasts.error('Failed to freeze organization.');
		} finally {
			freezing = false;
		}
	}

	async function handleUnfreeze() {
		freezing = true;
		try {
			await unfreezeOrg(orgId);
			toasts.success('Organization unfrozen.');
		} catch {
			toasts.error('Failed to unfreeze organization.');
		} finally {
			freezing = false;
		}
	}

	async function startDeleteFlow() {
		showDeleteFlow = true;
		previewLoading = true;
		try {
			deletionPreview = await getDeletionPreview(orgId);
		} catch {
			toasts.error('Failed to load deletion preview.');
			showDeleteFlow = false;
		} finally {
			previewLoading = false;
		}
	}

	async function handleDelete() {
		if (!deletionPreview || confirmName !== org.name) return;
		deleting = true;
		try {
			await deleteOrg(orgId, { confirm_name: confirmName });
			toasts.success('Organization deleted.');
			goto('/');
		} catch {
			toasts.error('Failed to delete organization.');
		} finally {
			deleting = false;
		}
	}
</script>

<div class="space-y-8">
	<div>
		<h3 class="text-sm font-medium text-foreground">General Settings</h3>
		<p class="text-xs text-muted">Manage organization slug, freeze status, and deletion.</p>
	</div>

	{#if isAdmin}
		<!-- Slug section -->
		<div class="rounded-xl border border-border p-4">
			<h4 class="mb-1 text-xs font-medium text-foreground">Organization Slug</h4>
			<p class="mb-3 text-xs text-muted">
				Current slug: <span class="font-mono text-foreground">{org.slug}</span>
			</p>
			<div class="flex flex-col gap-3 sm:flex-row sm:items-end">
				<div class="flex-1">
					<label for="ol-slug" class="mb-1 block text-xs font-medium text-muted">New Slug</label>
					<input
						id="ol-slug"
						type="text"
						bind:value={newSlug}
						placeholder="new-org-slug"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					/>
				</div>
				<button
					onclick={handleSlugChange}
					disabled={slugSaving || !newSlug.trim()}
					class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
				>
					{slugSaving ? 'Changing...' : 'Change Slug'}
				</button>
			</div>
			{#if slugResult}
				<div
					class="mt-3 rounded-lg border border-green-300 bg-green-50 p-3 dark:border-green-700 dark:bg-green-900/20"
					transition:fade={{ duration: 100 }}
				>
					<p class="text-xs text-green-800 dark:text-green-300">Slug changed successfully.</p>
					<p class="mt-1 text-[10px] text-green-700 dark:text-green-400">
						Old endpoint: <span class="font-mono">{slugResult.old_endpoint_url}</span>
					</p>
					<p class="text-[10px] text-green-700 dark:text-green-400">
						New endpoint: <span class="font-mono">{slugResult.new_endpoint_url}</span>
					</p>
				</div>
			{/if}
		</div>

		<!-- Freeze section -->
		<div class="rounded-xl border border-border p-4">
			<h4 class="mb-1 text-xs font-medium text-foreground">Freeze Organization</h4>
			<p class="mb-3 text-xs text-muted">
				Freezing an organization prevents all members from creating new agent runs, conversations,
				or projects. Existing data remains accessible in read-only mode.
			</p>
			{#if showFreezeConfirm}
				<div class="flex items-center gap-3" transition:fade={{ duration: 100 }}>
					<span class="text-xs font-medium text-amber-600"
						>Are you sure you want to freeze this organization?</span
					>
					<button
						onclick={handleFreeze}
						disabled={freezing}
						class="rounded-lg bg-amber-500 px-4 py-2 text-xs font-medium text-white hover:bg-amber-600 disabled:opacity-50"
					>
						{freezing ? 'Freezing...' : 'Yes, Freeze'}
					</button>
					<button
						onclick={() => (showFreezeConfirm = false)}
						class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
					>
						Cancel
					</button>
				</div>
			{:else}
				<div class="flex gap-2">
					<button
						onclick={() => (showFreezeConfirm = true)}
						class="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-xs font-medium text-amber-700 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
					>
						Freeze Organization
					</button>
					<button
						onclick={handleUnfreeze}
						disabled={freezing}
						class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface disabled:opacity-50"
					>
						{freezing ? 'Unfreezing...' : 'Unfreeze Organization'}
					</button>
				</div>
			{/if}
		</div>

		<!-- Danger Zone -->
		<div class="rounded-xl border-2 border-red-300 p-6 dark:border-red-500/30">
			<h4 class="mb-1 text-xs font-medium text-red-700 dark:text-red-400">Danger Zone</h4>
			<p class="mb-4 text-xs text-muted">
				Permanently delete this organization and all associated data. This action cannot be undone.
			</p>

			{#if !showDeleteFlow}
				<button
					onclick={startDeleteFlow}
					class="rounded-lg bg-red-600 px-4 py-2 text-xs font-medium text-white hover:bg-red-700"
				>
					Delete Organization
				</button>
			{:else}
				<div class="space-y-4" transition:fade={{ duration: 100 }}>
					{#if previewLoading}
						<div class="flex items-center justify-center py-4">
							<svg
								class="h-5 w-5 animate-spin text-muted"
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								><circle
									class="opacity-25"
									cx="12"
									cy="12"
									r="10"
									stroke="currentColor"
									stroke-width="4"
								></circle><path
									class="opacity-75"
									fill="currentColor"
									d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
								></path></svg
							>
						</div>
					{:else if deletionPreview}
						<div
							class="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20"
						>
							<p class="mb-2 text-xs font-medium text-red-800 dark:text-red-300">
								This will permanently delete:
							</p>
							<ul class="space-y-1">
								{#each deletionPreview.will_delete as item}
									<li class="text-xs text-red-700 dark:text-red-400">- {item}</li>
								{/each}
							</ul>
							<div class="mt-2 grid grid-cols-3 gap-2 text-xs text-red-700 dark:text-red-400">
								<span>{deletionPreview.member_count} members</span>
								<span>{deletionPreview.conversation_count} conversations</span>
								<span>{deletionPreview.project_count} projects</span>
							</div>
							{#if deletionPreview.warning}
								<p class="mt-2 text-xs font-medium text-red-800 dark:text-red-300">
									{deletionPreview.warning}
								</p>
							{/if}
						</div>

						<div>
							<label
								for="ol-confirm"
								class="mb-1 block text-xs font-medium text-red-700 dark:text-red-400"
							>
								Type <span class="font-mono font-medium">{org.name}</span> to confirm
							</label>
							<input
								id="ol-confirm"
								type="text"
								bind:value={confirmName}
								placeholder={org.name}
								class="w-full max-w-sm rounded-lg border border-red-300 bg-background px-3 py-2 text-sm text-foreground outline-none dark:border-red-700"
							/>
						</div>

						<div class="flex items-center gap-2">
							<button
								onclick={handleDelete}
								disabled={deleting || confirmName !== org.name}
								class="rounded-lg bg-red-600 px-4 py-2 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
							>
								{deleting ? 'Deleting...' : 'Permanently Delete Organization'}
							</button>
							<button
								onclick={() => {
									showDeleteFlow = false;
									confirmName = '';
									deletionPreview = null;
								}}
								class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
							>
								Cancel
							</button>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{:else}
		<p class="text-xs text-muted">
			Only admins and owners can manage organization lifecycle settings.
		</p>
	{/if}
</div>
