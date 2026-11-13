<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import {
		listOrgApiKeys,
		createOrgApiKey,
		deleteOrgApiKey,
		type Organization,
		type OrgApiKey,
		type OrgApiKeyCreateResult
	} from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	const SCOPES = ['org:read', 'org:write', 'org:admin'];

	let keys: OrgApiKey[] = $state([]);
	let loading = $state(true);

	// Create form
	let showForm = $state(false);
	let newName = $state('');
	let newScopes: string[] = $state([]);
	let newRateLimit = $state('120');
	let creating = $state(false);
	let createdKey: OrgApiKeyCreateResult | null = $state(null);
	let copied = $state(false);

	// Revoke
	let confirmRevokeId: string | null = $state(null);
	let revokingId: string | null = $state(null);

	async function load() {
		loading = true;
		try {
			keys = await listOrgApiKeys(orgId);
		} catch {
			toasts.error('Failed to load API keys.');
		} finally {
			loading = false;
		}
	}

	function toggleScope(scope: string) {
		if (newScopes.includes(scope)) {
			newScopes = newScopes.filter((s) => s !== scope);
		} else {
			newScopes = [...newScopes, scope];
		}
	}

	async function handleCreate() {
		if (!newName.trim() || newScopes.length === 0) return;
		creating = true;
		try {
			const data: { name: string; scopes: string[]; rate_limit_per_minute?: number } = {
				name: newName.trim(),
				scopes: newScopes
			};
			const limit = parseInt(newRateLimit);
			if (limit > 0) data.rate_limit_per_minute = limit;
			createdKey = await createOrgApiKey(orgId, data);
			toasts.success('API key created.');
			newName = '';
			newScopes = [];
			newRateLimit = '120';
			showForm = false;
			await load();
		} catch {
			toasts.error('Failed to create API key.');
		} finally {
			creating = false;
		}
	}

	async function handleRevoke(keyId: string) {
		revokingId = keyId;
		try {
			await deleteOrgApiKey(orgId, keyId);
			toasts.success('API key revoked.');
			confirmRevokeId = null;
			await load();
		} catch {
			toasts.error('Failed to revoke API key.');
		} finally {
			revokingId = null;
		}
	}

	async function copyKey() {
		if (!createdKey) return;
		await navigator.clipboard.writeText(createdKey.key);
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
	<div class="flex items-center justify-between">
		<div>
			<h3 class="text-sm font-medium text-foreground">API Keys</h3>
			<p class="text-xs text-muted">Manage organization-level API keys for programmatic access.</p>
		</div>
		{#if !showForm}
			<button
				onclick={() => (showForm = true)}
				class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70"
			>
				Create Key
			</button>
		{/if}
	</div>

	<!-- New key display -->
	{#if createdKey}
		<div
			class="rounded-xl border border-green-300 bg-green-50 p-4 dark:border-green-700 dark:bg-green-900/20"
			transition:fade={{ duration: 100 }}
		>
			<p class="mb-2 text-xs font-medium text-green-800 dark:text-green-300">
				API key created successfully
			</p>
			<p class="mb-2 text-xs text-green-700 dark:text-green-400">
				This key won't be shown again. Copy it now.
			</p>
			<div class="flex items-center gap-2">
				<code
					class="flex-1 overflow-x-auto rounded-lg bg-green-100 px-3 py-2 text-xs text-green-900 dark:bg-green-900/40 dark:text-green-200"
					>{createdKey.key}</code
				>
				<button
					onclick={copyKey}
					class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70"
				>
					{copied ? 'Copied!' : 'Copy'}
				</button>
			</div>
			<button
				onclick={() => (createdKey = null)}
				class="mt-2 text-xs text-green-600 underline hover:text-green-800 dark:text-green-400"
				>Dismiss</button
			>
		</div>
	{/if}

	<!-- Create form -->
	{#if showForm}
		<div
			class="rounded-xl border border-border-subtle bg-surface p-4"
			transition:fade={{ duration: 100 }}
		>
			<h4 class="mb-3 text-xs font-medium text-foreground">Create API Key</h4>
			<div class="space-y-3">
				<div>
					<label for="ak-name" class="mb-1 block text-xs font-medium text-muted">Name</label>
					<input
						id="ak-name"
						type="text"
						bind:value={newName}
						placeholder="e.g. CI/CD Pipeline"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					/>
				</div>
				<div>
					<p class="mb-2 text-xs font-medium text-muted">Scopes</p>
					<div class="flex flex-wrap gap-2">
						{#each SCOPES as scope}
							<label
								class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs {newScopes.includes(
									scope
								)
									? 'border-accent bg-accent/10 text-foreground'
									: 'text-muted hover:bg-surface'}"
							>
								<input
									type="checkbox"
									class="sr-only"
									checked={newScopes.includes(scope)}
									onchange={() => toggleScope(scope)}
								/>
								{scope}
							</label>
						{/each}
					</div>
				</div>
				<div class="w-48">
					<label for="ak-rate" class="mb-1 block text-xs font-medium text-muted"
						>Rate limit (per minute)</label
					>
					<input
						id="ak-rate"
						type="number"
						bind:value={newRateLimit}
						min="1"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					/>
				</div>
				<div class="flex items-center gap-2 pt-1">
					<button
						onclick={handleCreate}
						disabled={creating || !newName.trim() || newScopes.length === 0}
						class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
					>
						{creating ? 'Creating...' : 'Create'}
					</button>
					<button
						onclick={() => (showForm = false)}
						class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
					>
						Cancel
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Key list -->
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
	{:else if keys.length === 0 && !showForm}
		<p class="py-4 text-center text-xs text-muted">No API keys configured.</p>
	{:else}
		<div class="overflow-x-auto rounded-xl border border-border">
			<table class="w-full text-left">
				<thead class="bg-surface">
					<tr>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Prefix</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Name</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Scopes</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Rate Limit</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Created By</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Last Used</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-border">
					{#each keys as key (key.id)}
						<tr>
							<td class="px-4 py-2.5 font-mono text-xs text-foreground">{key.key_prefix}...</td>
							<td class="px-4 py-2.5 text-xs text-foreground">{key.name}</td>
							<td class="px-4 py-2.5">
								<div class="flex flex-wrap gap-1">
									{#each key.scopes as scope}
										<span
											class="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
											>{scope}</span
										>
									{/each}
								</div>
							</td>
							<td class="px-4 py-2.5 text-xs text-muted">{key.rate_limit_per_minute}/min</td>
							<td class="px-4 py-2.5 text-xs text-muted">{key.created_by_email}</td>
							<td class="px-4 py-2.5 text-xs text-muted"
								>{key.last_used_at ? formatDate(key.last_used_at) : 'Never'}</td
							>
							<td class="px-4 py-2.5 text-right">
								{#if key.is_active}
									{#if confirmRevokeId === key.id}
										<span class="text-xs text-muted">Are you sure?</span>
										<button
											onclick={() => handleRevoke(key.id)}
											disabled={revokingId === key.id}
											class="ml-1 text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
										>
											{revokingId === key.id ? 'Revoking...' : 'Yes'}
										</button>
										<button
											onclick={() => (confirmRevokeId = null)}
											class="ml-1 text-xs font-medium text-muted hover:text-foreground"
										>
											Cancel
										</button>
									{:else}
										<button
											onclick={() => (confirmRevokeId = key.id)}
											class="text-xs font-medium text-red-600 hover:text-red-700"
										>
											Revoke
										</button>
									{/if}
								{:else}
									<span class="text-xs text-muted">Revoked</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
