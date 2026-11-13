<script lang="ts">
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import { forceLogout, type Organization } from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	let showConfirm = $state(false);
	let processing = $state(false);

	async function handleForceLogout() {
		processing = true;
		try {
			const result = await forceLogout(orgId);
			toasts.success(result.message || 'All members have been logged out.');
			showConfirm = false;
		} catch {
			toasts.error('Failed to force logout.');
		} finally {
			processing = false;
		}
	}
</script>

<div class="space-y-4">
	<div>
		<h3 class="text-sm font-medium text-foreground">Force Logout</h3>
		<p class="text-xs text-muted">
			Immediately terminate all active sessions for every member in this organization.
		</p>
	</div>

	{#if org.your_role === 'admin' || org.your_role === 'owner'}
		<div class="rounded-xl border border-border-subtle bg-surface p-4">
			<p class="mb-3 text-xs text-muted">
				This will invalidate all active sessions for all members. Everyone will need to sign in
				again. Use this in case of a security incident or compromised credentials.
			</p>
			{#if showConfirm}
				<div class="flex items-center gap-3" transition:fade={{ duration: 100 }}>
					<span class="text-xs font-medium text-red-600">Are you sure? This cannot be undone.</span>
					<button
						onclick={handleForceLogout}
						disabled={processing}
						class="rounded-lg bg-red-600 px-4 py-2 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
					>
						{processing ? 'Logging out...' : 'Yes, Force Logout All'}
					</button>
					<button
						onclick={() => (showConfirm = false)}
						class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
					>
						Cancel
					</button>
				</div>
			{:else}
				<button
					onclick={() => (showConfirm = true)}
					class="rounded-lg bg-red-600 px-4 py-2 text-xs font-medium text-white hover:bg-red-700"
				>
					Force Logout All Members
				</button>
			{/if}
		</div>
	{:else}
		<p class="text-xs text-muted">Only admins and owners can force logout members.</p>
	{/if}
</div>
