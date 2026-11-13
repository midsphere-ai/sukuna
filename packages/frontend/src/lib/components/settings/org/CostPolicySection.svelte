<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import {
		updateCostPolicy,
		getCostStatus,
		type Organization,
		type CostPolicy,
		type CostStatus
	} from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	let status: CostStatus | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);

	// Policy form
	let memberLimit = $state('');
	let alertThreshold = $state('80');

	async function load() {
		loading = true;
		try {
			status = await getCostStatus(orgId);
			// Infer current policy from first member's limit if available
			if (status.members.length > 0 && status.members[0].monthly_limit != null) {
				memberLimit = String(status.members[0].monthly_limit);
			}
		} catch {
			toasts.error('Failed to load cost status.');
		} finally {
			loading = false;
		}
	}

	async function handleSave() {
		saving = true;
		try {
			const data: Partial<CostPolicy> = {
				alert_threshold_percent: parseInt(alertThreshold) || 80
			};
			if (memberLimit.trim() && parseInt(memberLimit) > 0) {
				data.member_monthly_credit_limit = parseInt(memberLimit);
			} else {
				data.member_monthly_credit_limit = null;
			}
			await updateCostPolicy(orgId, data);
			toasts.success('Cost policy updated.');
			await load();
		} catch {
			toasts.error('Failed to update cost policy.');
		} finally {
			saving = false;
		}
	}

	function progressPercent(spent: number, limit: number | null): number {
		if (!limit || limit <= 0) return 0;
		return Math.min(100, (spent / limit) * 100);
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

<div class="space-y-6">
	<div>
		<h3 class="text-sm font-medium text-foreground">Cost Controls</h3>
		<p class="text-xs text-muted">
			Set spending limits and monitor credit usage across your organization.
		</p>
	</div>

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
	{:else}
		<!-- Policy form -->
		{#if org.your_role === 'admin' || org.your_role === 'owner'}
			<div class="rounded-xl border border-border-subtle bg-surface p-4">
				<h4 class="mb-3 text-xs font-medium text-foreground">Spending Policy</h4>
				<div class="flex flex-col gap-3 sm:flex-row sm:items-end">
					<div class="flex-1">
						<label for="cp-limit" class="mb-1 block text-xs font-medium text-muted"
							>Member Monthly Credit Limit</label
						>
						<input
							id="cp-limit"
							type="number"
							bind:value={memberLimit}
							placeholder="Unlimited"
							min="0"
							class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
						/>
						<p class="mt-1 text-[10px] text-muted">Leave blank for unlimited.</p>
					</div>
					<div class="w-48">
						<label for="cp-alert" class="mb-1 block text-xs font-medium text-muted"
							>Alert Threshold (%)</label
						>
						<input
							id="cp-alert"
							type="number"
							bind:value={alertThreshold}
							min="0"
							max="100"
							class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
						/>
					</div>
					<button
						onclick={handleSave}
						disabled={saving}
						class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
					>
						{saving ? 'Saving...' : 'Save'}
					</button>
				</div>
			</div>
		{/if}

		{#if status}
			<div class="text-xs text-muted">
				Billing cycle: {formatDate(status.current_cycle_start)} &mdash; {formatDate(
					status.current_cycle_end
				)}
			</div>

			<!-- Member usage -->
			<div>
				<h4 class="mb-2 text-xs font-medium text-foreground">Member Usage</h4>
				{#if status.members.length > 0}
					<div class="overflow-x-auto rounded-xl border border-border">
						<table class="w-full text-left">
							<thead class="bg-surface">
								<tr>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Name</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Email</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Spent</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Limit</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted min-w-[120px]">Usage</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-border">
								{#each status.members as m}
									<tr>
										<td class="px-4 py-2.5 text-xs text-foreground">{m.name}</td>
										<td class="px-4 py-2.5 text-xs text-muted">{m.email}</td>
										<td class="px-4 py-2.5 text-xs text-foreground"
											>{m.spent_this_month.toLocaleString()}</td
										>
										<td class="px-4 py-2.5 text-xs text-muted"
											>{m.monthly_limit != null
												? m.monthly_limit.toLocaleString()
												: 'Unlimited'}</td
										>
										<td class="px-4 py-2.5">
											{#if m.monthly_limit != null && m.monthly_limit > 0}
												<div class="h-2 w-full rounded-full bg-border">
													<div
														class="h-2 rounded-full transition-all duration-300 {progressPercent(
															m.spent_this_month,
															m.monthly_limit
														) > 90
															? 'bg-red-500'
															: progressPercent(m.spent_this_month, m.monthly_limit) > 70
																? 'bg-amber-500'
																: 'bg-green-500'}"
														style="width: {progressPercent(m.spent_this_month, m.monthly_limit)}%"
													></div>
												</div>
												<p class="mt-0.5 text-[10px] text-muted">
													{Math.round(progressPercent(m.spent_this_month, m.monthly_limit))}%
												</p>
											{:else}
												<span class="text-[10px] text-muted">—</span>
											{/if}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="py-4 text-center text-xs text-muted">No member usage data.</p>
				{/if}
			</div>

			<!-- Project usage -->
			<div>
				<h4 class="mb-2 text-xs font-medium text-foreground">Project Usage</h4>
				{#if status.projects.length > 0}
					<div class="overflow-x-auto rounded-xl border border-border">
						<table class="w-full text-left">
							<thead class="bg-surface">
								<tr>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Project</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Spent This Month</th>
								</tr>
							</thead>
							<tbody class="divide-y divide-border">
								{#each status.projects as p}
									<tr>
										<td class="px-4 py-2.5 text-xs text-foreground">{p.name}</td>
										<td class="px-4 py-2.5 text-xs text-foreground"
											>{p.spent_this_month.toLocaleString()}</td
										>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="py-4 text-center text-xs text-muted">No project usage data.</p>
				{/if}
			</div>
		{/if}
	{/if}
</div>
