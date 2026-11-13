<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import {
		listScimTokens,
		createScimToken,
		deleteScimToken,
		type Organization,
		type ScimToken,
		type ScimTokenCreateResult
	} from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	let tokens: ScimToken[] = $state([]);
	let loading = $state(true);
	let creating = $state(false);
	let newName = $state('');
	let newExpiresInDays = $state('');
	let newToken: ScimTokenCreateResult | null = $state(null);
	let copied = $state(false);
	let revokingId: string | null = $state(null);
	let confirmRevokeId: string | null = $state(null);

	async function load() {
		loading = true;
		try {
			tokens = await listScimTokens(orgId);
		} catch {
			toasts.error('Failed to load SCIM tokens.');
		} finally {
			loading = false;
		}
	}

	async function handleCreate() {
		if (!newName.trim()) return;
		creating = true;
		try {
			const data: { name: string; expires_in_days?: number } = { name: newName.trim() };
			if (newExpiresInDays && parseInt(newExpiresInDays) > 0) {
				data.expires_in_days = parseInt(newExpiresInDays);
			}
			newToken = await createScimToken(orgId, data);
			toasts.success('SCIM token created.');
			newName = '';
			newExpiresInDays = '';
			await load();
		} catch {
			toasts.error('Failed to create SCIM token.');
		} finally {
			creating = false;
		}
	}

	async function handleRevoke(tokenId: string) {
		revokingId = tokenId;
		try {
			await deleteScimToken(orgId, tokenId);
			toasts.success('SCIM token revoked.');
			confirmRevokeId = null;
			await load();
		} catch {
			toasts.error('Failed to revoke token.');
		} finally {
			revokingId = null;
		}
	}

	async function copyToken() {
		if (!newToken) return;
		await navigator.clipboard.writeText(newToken.token);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}

	onMount(load);
</script>

<div class="space-y-4">
	<div>
		<h3 class="text-sm font-medium text-foreground">SCIM Tokens</h3>
		<p class="text-xs text-muted">
			Manage SCIM tokens for identity provider integration (user provisioning).
		</p>
	</div>

	{#if newToken}
		<div
			class="rounded-xl border border-green-300 bg-green-50 p-4 dark:border-green-700 dark:bg-green-900/20"
			transition:fade={{ duration: 100 }}
		>
			<p class="mb-2 text-xs font-medium text-green-800 dark:text-green-300">
				Token created successfully
			</p>
			<p class="mb-2 text-xs text-green-700 dark:text-green-400">
				This token won't be shown again. Copy it now.
			</p>
			<div class="flex items-center gap-2">
				<code
					class="flex-1 overflow-x-auto rounded-lg bg-green-100 px-3 py-2 text-xs text-green-900 dark:bg-green-900/40 dark:text-green-200"
					>{newToken.token}</code
				>
				<button
					onclick={copyToken}
					class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70"
				>
					{copied ? 'Copied!' : 'Copy'}
				</button>
			</div>
			<button
				onclick={() => (newToken = null)}
				class="mt-2 text-xs text-green-600 underline hover:text-green-800 dark:text-green-400"
				>Dismiss</button
			>
		</div>
	{/if}

	<!-- Create form -->
	{#if org.your_role === 'admin' || org.your_role === 'owner'}
		<div class="rounded-xl border border-border-subtle bg-surface p-4">
			<h4 class="mb-3 text-xs font-medium text-foreground">Create Token</h4>
			<div class="flex flex-col gap-3 sm:flex-row sm:items-end">
				<div class="flex-1">
					<label for="scim-name" class="mb-1 block text-xs font-medium text-muted">Name</label>
					<input
						id="scim-name"
						type="text"
						bind:value={newName}
						placeholder="e.g. Okta SCIM"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					/>
				</div>
				<div class="w-40">
					<label for="scim-expires" class="mb-1 block text-xs font-medium text-muted"
						>Expires in (days)</label
					>
					<input
						id="scim-expires"
						type="number"
						bind:value={newExpiresInDays}
						placeholder="Optional"
						min="1"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					/>
				</div>
				<button
					onclick={handleCreate}
					disabled={creating || !newName.trim()}
					class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
				>
					{creating ? 'Creating...' : 'Create Token'}
				</button>
			</div>
		</div>
	{/if}

	<!-- Token list -->
	{#if loading}
		<div class="flex items-center justify-center py-6">
			<svg
				class="h-5 w-5 animate-spin text-muted"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
				></circle><path
					class="opacity-75"
					fill="currentColor"
					d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
				></path></svg
			>
		</div>
	{:else if tokens.length === 0}
		<p class="py-4 text-center text-xs text-muted">No SCIM tokens configured.</p>
	{:else}
		<div class="overflow-x-auto rounded-xl border border-border">
			<table class="w-full text-left">
				<thead class="bg-surface">
					<tr>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Prefix</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Name</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Status</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Expires</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Created</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Last Used</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-border">
					{#each tokens as token (token.id)}
						<tr>
							<td class="px-4 py-2.5 font-mono text-xs text-foreground">{token.token_prefix}...</td>
							<td class="px-4 py-2.5 text-xs text-foreground">{token.name}</td>
							<td class="px-4 py-2.5">
								{#if token.is_active}
									<span
										class="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400"
										>Active</span
									>
								{:else}
									<span
										class="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-800 dark:text-gray-400"
										>Inactive</span
									>
								{/if}
							</td>
							<td class="px-4 py-2.5 text-xs text-muted"
								>{token.expires_at ? formatDate(token.expires_at) : 'Never'}</td
							>
							<td class="px-4 py-2.5 text-xs text-muted">{formatDate(token.created_at)}</td>
							<td class="px-4 py-2.5 text-xs text-muted"
								>{token.last_used_at ? formatDate(token.last_used_at) : 'Never'}</td
							>
							<td class="px-4 py-2.5 text-right">
								{#if (org.your_role === 'admin' || org.your_role === 'owner') && token.is_active}
									{#if confirmRevokeId === token.id}
										<span class="text-xs text-muted">Are you sure?</span>
										<button
											onclick={() => handleRevoke(token.id)}
											disabled={revokingId === token.id}
											class="ml-1 text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
										>
											{revokingId === token.id ? 'Revoking...' : 'Yes'}
										</button>
										<button
											onclick={() => (confirmRevokeId = null)}
											class="ml-1 text-xs font-medium text-muted hover:text-foreground"
										>
											Cancel
										</button>
									{:else}
										<button
											onclick={() => (confirmRevokeId = token.id)}
											class="text-xs font-medium text-red-600 hover:text-red-700"
										>
											Revoke
										</button>
									{/if}
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
