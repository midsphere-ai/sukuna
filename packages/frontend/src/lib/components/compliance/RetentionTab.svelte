<script lang="ts">
	import { onMount } from 'svelte';
	import { toasts } from '$stores/toast';
	import { getRetentionStatus, updateRetentionPolicy, type RetentionStatus } from '$api/compliance';

	let policies: RetentionStatus[] = $state([]);
	let loading = $state(true);
	let editingId: string | null = $state(null);
	let saving = $state(false);

	// Edit form state
	let editDays = $state(0);
	let editAction = $state('');
	let editActive = $state(false);

	function formatDate(iso: string): string {
		try {
			const d = new Date(iso);
			return d.toLocaleString(undefined, {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}

	async function loadPolicies(): Promise<void> {
		loading = true;
		try {
			policies = await getRetentionStatus();
		} catch {
			// Error handled by API client
		} finally {
			loading = false;
		}
	}

	function startEdit(policy: RetentionStatus): void {
		editingId = policy.id;
		editDays = policy.retention_days;
		editAction = policy.action;
		editActive = policy.is_active;
	}

	function cancelEdit(): void {
		editingId = null;
	}

	async function saveEdit(): Promise<void> {
		if (!editingId) return;
		saving = true;
		try {
			await updateRetentionPolicy(editingId, {
				retention_days: editDays,
				action: editAction,
				is_active: editActive
			});
			toasts.success('Retention policy updated.');
			editingId = null;
			await loadPolicies();
		} catch {
			toasts.error('Failed to update retention policy.');
		} finally {
			saving = false;
		}
	}

	onMount(() => {
		loadPolicies();
	});
</script>

<div class="space-y-4">
	<div>
		<h3 class="text-sm font-medium text-foreground">Retention Policies</h3>
		<p class="text-xs text-muted">Data retention schedule and execution status.</p>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-12">
			<svg
				class="h-5 w-5 animate-spin text-muted"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
			>
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
				></circle>
				<path
					class="opacity-75"
					fill="currentColor"
					d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
				></path>
			</svg>
		</div>
	{:else if policies.length > 0}
		<div class="overflow-x-auto rounded-xl border border-border">
			<table class="w-full text-left text-sm">
				<thead>
					<tr class="border-b border-border-subtle bg-surface">
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Resource Type</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Retention</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Action</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Status</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Last Run</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Records</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Next Run</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each policies as policy (policy.id)}
						{#if editingId === policy.id}
							<tr class="border-b border-border-subtle bg-surface/50 last:border-0">
								<td class="px-4 py-2.5 text-xs text-foreground capitalize">
									{policy.resource_type.replace(/_/g, ' ')}
								</td>
								<td class="px-4 py-2.5">
									<input
										type="number"
										min="1"
										bind:value={editDays}
										class="w-20 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
									/>
								</td>
								<td class="px-4 py-2.5">
									<select
										bind:value={editAction}
										class="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
									>
										<option value="delete">delete</option>
										<option value="anonymize">anonymize</option>
										<option value="keep">keep</option>
									</select>
								</td>
								<td class="px-4 py-2.5">
									<button
										onclick={() => (editActive = !editActive)}
										class="rounded-lg px-2.5 py-1 text-xs font-medium {editActive
											? 'bg-green-100 text-green-800'
											: 'bg-gray-100 text-gray-600'}"
									>
										{editActive ? 'Active' : 'Inactive'}
									</button>
								</td>
								<td class="px-4 py-2.5 text-xs text-muted" colspan="2">
									<!-- read-only while editing -->
								</td>
								<td class="px-4 py-2.5" colspan="2">
									<div class="flex gap-2">
										<button
											onclick={saveEdit}
											disabled={saving}
											class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background disabled:opacity-50"
										>
											{saving ? 'Saving...' : 'Save'}
										</button>
										<button
											onclick={cancelEdit}
											disabled={saving}
											class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
										>
											Cancel
										</button>
									</div>
								</td>
							</tr>
						{:else}
							<tr class="border-b border-border-subtle last:border-0">
								<td class="px-4 py-2.5 text-xs text-foreground capitalize">
									{policy.resource_type.replace(/_/g, ' ')}
								</td>
								<td class="px-4 py-2.5 text-xs text-foreground">{policy.retention_days} days</td>
								<td class="px-4 py-2.5">
									<span
										class="rounded-lg bg-surface px-2 py-0.5 text-xs font-medium text-muted capitalize"
									>
										{policy.action}
									</span>
								</td>
								<td class="px-4 py-2.5">
									<span
										class="rounded-lg px-2.5 py-1 text-xs font-medium {policy.is_active
											? 'bg-green-100 text-green-800'
											: 'bg-gray-100 text-gray-600'}"
									>
										{policy.is_active ? 'Active' : 'Inactive'}
									</span>
								</td>
								<td class="whitespace-nowrap px-4 py-2.5 text-xs text-muted">
									{policy.last_run_at ? formatDate(policy.last_run_at) : 'Never'}
								</td>
								<td class="px-4 py-2.5 text-xs text-muted">
									{policy.records_affected_last_run}
								</td>
								<td class="whitespace-nowrap px-4 py-2.5 text-xs text-muted">
									{policy.next_scheduled_run ? formatDate(policy.next_scheduled_run) : '-'}
								</td>
								<td class="px-4 py-2.5">
									<button
										onclick={() => startEdit(policy)}
										class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
									>
										Edit
									</button>
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<p class="py-8 text-center text-sm text-muted">No retention policies configured.</p>
	{/if}
</div>
