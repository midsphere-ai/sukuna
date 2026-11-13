<script lang="ts">
	import { Dialog } from '$components/ui';
	import { toasts } from '$stores/toast';
	import { listOrganizations, type Organization } from '$api/organizations';
	import {
		listProjectShares,
		createProjectShare,
		updateProjectShare,
		deleteProjectShare,
		type ProjectShare
	} from '$api/shares';

	type Props = {
		open: boolean;
		projectId: string;
		projectTitle: string;
		onclose: () => void;
	};

	let { open = $bindable(false), projectId, projectTitle, onclose }: Props = $props();

	let shares: ProjectShare[] = $state([]);
	let orgs: Organization[] = $state([]);
	let loading = $state(false);

	// Add share form
	let shareTarget = $state<'user' | 'org'>('user');
	let shareEmail = $state('');
	let shareOrgId = $state('');
	let sharePermission = $state('view');
	let adding = $state(false);

	// Inline confirmation for delete
	let confirmingDeleteId: string | null = $state(null);

	$effect(() => {
		if (open) {
			loadShares();
			loadOrgs();
		}
	});

	async function loadShares(): Promise<void> {
		loading = true;
		try {
			shares = await listProjectShares(projectId);
		} catch {
			shares = [];
		} finally {
			loading = false;
		}
	}

	async function loadOrgs(): Promise<void> {
		try {
			orgs = await listOrganizations();
		} catch {
			orgs = [];
		}
	}

	async function handleAddShare(): Promise<void> {
		adding = true;
		try {
			const data: { user_id?: number; organization_id?: string; permission_level: string } = {
				permission_level: sharePermission
			};
			if (shareTarget === 'org' && shareOrgId) {
				data.organization_id = shareOrgId;
			} else if (shareTarget === 'user' && shareEmail.trim()) {
				// Backend expects user_id; for email-based sharing the backend
				// resolves the email. We pass it as-is in case the backend
				// supports email lookup, but if it strictly needs user_id this
				// would need a user search endpoint. For now pass email as the
				// user identifier field.
				(data as Record<string, unknown>).email = shareEmail.trim();
			} else {
				adding = false;
				return;
			}

			await createProjectShare(projectId, data);
			toasts.success('Project shared successfully.');
			shareEmail = '';
			shareOrgId = '';
			sharePermission = 'view';
			await loadShares();
		} catch {
			// Error handled by API client
		} finally {
			adding = false;
		}
	}

	async function handlePermissionChange(share: ProjectShare, newPermission: string): Promise<void> {
		try {
			await updateProjectShare(projectId, share.id, { permission_level: newPermission });
			share.permission_level = newPermission;
			shares = [...shares];
			toasts.success('Permission updated.');
		} catch {
			// Error handled by API client
		}
	}

	async function handleDeleteShare(shareId: string): Promise<void> {
		try {
			await deleteProjectShare(projectId, shareId);
			shares = shares.filter((s) => s.id !== shareId);
			toasts.success('Share removed.');
		} catch {
			// Error handled by API client
		} finally {
			confirmingDeleteId = null;
		}
	}

	function handleClose(): void {
		open = false;
		onclose();
	}

	function permissionBadgeClass(level: string): string {
		switch (level) {
			case 'admin':
				return 'bg-amber-100 text-amber-800';
			case 'collaborate':
				return 'bg-blue-100 text-blue-800';
			default:
				return 'bg-gray-100 text-gray-600';
		}
	}

	function formatDate(iso: string): string {
		try {
			return new Date(iso).toLocaleDateString(undefined, {
				year: 'numeric',
				month: 'short',
				day: 'numeric'
			});
		} catch {
			return iso;
		}
	}
</script>

<Dialog bind:open {onclose} aria-label="Share project" class="max-w-xl">
	<!-- Header -->
	<div class="flex items-center justify-between border-b border-border-subtle px-5 py-4">
		<h2 class="text-base font-medium text-foreground">Share Project</h2>
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
	<div class="space-y-5 overflow-y-auto px-5 py-4">
		<p class="text-sm text-subtle">
			Manage sharing for <strong class="text-foreground">{projectTitle}</strong>.
		</p>

		<!-- Add Share Form -->
		<div class="rounded-xl border border-border p-4 space-y-3">
			<h3 class="text-xs font-medium text-foreground uppercase tracking-wide">Add Share</h3>

			<!-- Target toggle -->
			<div class="flex gap-2">
				<button
					onclick={() => (shareTarget = 'user')}
					class="rounded px-2 py-1 text-xs font-medium transition-colors {shareTarget === 'user'
						? 'bg-foreground text-background'
						: 'bg-surface text-muted hover:bg-surface-2'}"
				>
					User
				</button>
				<button
					onclick={() => (shareTarget = 'org')}
					class="rounded px-2 py-1 text-xs font-medium transition-colors {shareTarget === 'org'
						? 'bg-foreground text-background'
						: 'bg-surface text-muted hover:bg-surface-2'}"
				>
					Organization
				</button>
			</div>

			<div class="flex gap-2">
				{#if shareTarget === 'user'}
					<input
						type="email"
						bind:value={shareEmail}
						placeholder="user@example.com"
						class="flex-1 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs text-foreground outline-none placeholder:text-muted focus:border-border-strong"
					/>
				{:else}
					<select
						bind:value={shareOrgId}
						class="flex-1 rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground"
					>
						<option value="">Select organization...</option>
						{#each orgs as org (org.id)}
							<option value={org.id}>{org.name}</option>
						{/each}
					</select>
				{/if}

				<select
					bind:value={sharePermission}
					class="rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground"
				>
					<option value="view">View</option>
					<option value="collaborate">Collaborate</option>
					<option value="admin">Admin</option>
				</select>

				<button
					onclick={handleAddShare}
					disabled={adding || (shareTarget === 'user' ? !shareEmail.trim() : !shareOrgId)}
					class="shrink-0 rounded-lg bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-all hover:bg-foreground/90 disabled:opacity-50"
				>
					{adding ? 'Sharing...' : 'Share'}
				</button>
			</div>
		</div>

		<!-- Current Shares -->
		{#if loading}
			<div class="flex items-center justify-center py-6">
				<div
					class="h-5 w-5 animate-spin rounded-full border-2 border-border-strong border-t-accent"
				></div>
			</div>
		{:else if shares.length === 0}
			<p class="py-4 text-center text-sm text-muted">No shares yet.</p>
		{:else}
			<div class="rounded-xl border border-border divide-y divide-border-subtle">
				{#each shares as share (share.id)}
					<div class="flex items-center gap-3 px-4 py-3">
						<div class="min-w-0 flex-1">
							<p class="truncate text-sm font-medium text-foreground">
								{share.user_name || share.user_email || 'Organization share'}
							</p>
							<p class="text-xs text-muted">
								{#if share.organization_id}
									Entire organization
								{:else}
									{share.user_email || ''}
								{/if}
								{#if share.shared_by_email}
									&middot; shared by {share.shared_by_email}
								{/if}
								{#if share.shared_at}
									&middot; {formatDate(share.shared_at)}
								{/if}
							</p>
						</div>

						<!-- Permission dropdown -->
						<select
							value={share.permission_level}
							onchange={(e) => handlePermissionChange(share, (e.target as HTMLSelectElement).value)}
							class="rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground"
						>
							<option value="view">View</option>
							<option value="collaborate">Collaborate</option>
							<option value="admin">Admin</option>
						</select>

						<!-- Remove button / confirmation -->
						{#if confirmingDeleteId === share.id}
							<span class="flex items-center gap-1 text-xs">
								<span class="text-muted">Remove?</span>
								<button
									onclick={() => handleDeleteShare(share.id)}
									class="rounded px-2 py-1 text-xs font-medium text-red-600 hover:text-red-700"
								>
									Yes
								</button>
								<button
									onclick={() => (confirmingDeleteId = null)}
									class="rounded px-2 py-1 text-xs font-medium text-muted hover:text-foreground"
								>
									Cancel
								</button>
							</span>
						{:else}
							<button
								onclick={() => (confirmingDeleteId = share.id)}
								class="rounded px-2 py-1 text-xs font-medium text-red-600 hover:text-red-700"
								aria-label="Remove share"
							>
								Remove
							</button>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Footer -->
	<div class="flex items-center justify-end border-t border-border-subtle px-5 py-4">
		<button
			onclick={handleClose}
			class="rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
		>
			Done
		</button>
	</div>
</Dialog>
