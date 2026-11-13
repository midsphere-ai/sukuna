<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getIPAllowlist,
		addIPAllowlistEntry,
		removeIPAllowlistEntry,
		type IPAllowlistEntry
	} from '$lib/api/organizations';

	let { orgId }: { orgId: string } = $props();

	let entries: IPAllowlistEntry[] = $state([]);
	let yourIp: string | null = $state(null);
	let loading = $state(true);
	let error: string | null = $state(null);

	let newCidr = $state('');
	let newDescription = $state('');
	let busy = $state(false);
	let formError: string | null = $state(null);

	const CIDR_RE =
		/^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\/(?:[0-9]|[12]\d|3[0-2]))?$/;

	async function load() {
		loading = true;
		error = null;
		try {
			const data = await getIPAllowlist(orgId);
			entries = data.entries;
			yourIp = data.your_ip;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load IP allowlist';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function add(e: Event) {
		e.preventDefault();
		formError = null;
		const cidr = newCidr.trim();
		if (!CIDR_RE.test(cidr)) {
			formError = 'Enter a valid IPv4 address or CIDR (e.g. 203.0.113.0/24)';
			return;
		}
		busy = true;
		try {
			const entry = await addIPAllowlistEntry(orgId, {
				cidr_range: cidr,
				description: newDescription.trim() || undefined,
				is_active: true
			});
			entries = [...entries, entry];
			newCidr = '';
			newDescription = '';
		} catch (e) {
			formError = e instanceof Error ? e.message : 'Failed to add entry';
		} finally {
			busy = false;
		}
	}

	async function remove(entry: IPAllowlistEntry) {
		if (!confirm(`Remove ${entry.cidr_range} from the allowlist?`)) return;
		await removeIPAllowlistEntry(orgId, entry.id);
		entries = entries.filter((e) => e.id !== entry.id);
	}

	function formatDate(iso: string) {
		try {
			return new Date(iso).toLocaleDateString();
		} catch {
			return iso;
		}
	}
</script>

<div class="space-y-6">
	<div>
		<h2 class="text-lg font-medium text-foreground">IP Allowlist</h2>
		<p class="mt-1 text-sm text-muted">
			Restrict SCIM provisioning and API access to specific IP addresses or CIDR ranges. When the
			allowlist contains any active entries, all other source IPs are blocked.
		</p>
		{#if yourIp}
			<p class="mt-2 text-xs text-muted">
				Your current IP: <code class="rounded bg-surface px-1.5 py-0.5">{yourIp}</code>
			</p>
		{/if}
	</div>

	{#if loading}
		<div class="text-sm text-muted">Loading…</div>
	{:else if error}
		<div class="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700">
			{error}
		</div>
	{:else}
		<form
			onsubmit={add}
			class="grid gap-3 rounded-xl border border-divider p-4 sm:grid-cols-[1fr_1fr_auto]"
		>
			<div>
				<label for="cidr" class="block text-xs font-medium text-muted">CIDR / IP</label>
				<input
					id="cidr"
					bind:value={newCidr}
					placeholder="203.0.113.0/24"
					class="mt-1 w-full rounded-lg border border-divider px-3 py-2 text-sm"
				/>
			</div>
			<div>
				<label for="desc" class="block text-xs font-medium text-muted">Description</label>
				<input
					id="desc"
					bind:value={newDescription}
					placeholder="Office VPN"
					class="mt-1 w-full rounded-lg border border-divider px-3 py-2 text-sm"
				/>
			</div>
			<div class="flex items-end">
				<button
					type="submit"
					disabled={busy}
					class="w-full rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-light hover:bg-foreground/90 disabled:opacity-50"
				>
					{busy ? 'Adding…' : 'Add entry'}
				</button>
			</div>
			{#if formError}
				<div class="text-sm text-red-600 sm:col-span-3">{formError}</div>
			{/if}
		</form>

		<div class="overflow-hidden rounded-xl border border-divider">
			<table class="w-full text-sm">
				<thead class="bg-surface text-left text-xs uppercase tracking-wide text-muted">
					<tr>
						<th class="px-4 py-2.5">CIDR / IP</th>
						<th class="px-4 py-2.5">Description</th>
						<th class="px-4 py-2.5">Status</th>
						<th class="px-4 py-2.5">Added</th>
						<th class="px-4 py-2.5"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-divider">
					{#each entries as entry (entry.id)}
						<tr>
							<td class="px-4 py-2.5 font-mono">{entry.cidr_range}</td>
							<td class="px-4 py-2.5 text-muted">{entry.description || '—'}</td>
							<td class="px-4 py-2.5">
								<span
									class="rounded-full px-2 py-0.5 text-xs {entry.is_active
										? 'bg-emerald-100 text-emerald-700'
										: 'bg-surface text-muted'}"
								>
									{entry.is_active ? 'Active' : 'Inactive'}
								</span>
							</td>
							<td class="px-4 py-2.5 text-muted">{formatDate(entry.created_at)}</td>
							<td class="px-4 py-2.5 text-right">
								<button
									type="button"
									onclick={() => remove(entry)}
									class="rounded-md border border-divider px-2.5 py-1 text-xs text-muted hover:border-red-300 hover:text-red-600"
								>
									Remove
								</button>
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan="5" class="px-4 py-6 text-center text-muted">
								No allowlist entries. Add one above to start restricting access.
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
