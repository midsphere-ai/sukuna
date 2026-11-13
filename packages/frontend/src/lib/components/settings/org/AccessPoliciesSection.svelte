<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getAccessPolicies,
		createAccessPolicy,
		updateAccessPolicy,
		deleteAccessPolicy,
		type AccessPolicy,
		type AccessPolicyCondition
	} from '$lib/api/organizations';

	let { orgId }: { orgId: string } = $props();

	let policies: AccessPolicy[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);

	let editing: AccessPolicy | null = $state(null);
	let creating = $state(false);
	let modalOpen = $state(false);

	// Form state
	let fName = $state('');
	let fAction: 'allow' | 'block' | 'require_mfa' = $state('block');
	let fActive = $state(true);
	let fPriority = $state(100);
	let fConditions: AccessPolicyCondition[] = $state([]);
	let saving = $state(false);
	let formError: string | null = $state(null);

	const CONDITION_TYPES = [
		{ id: 'ip_range', label: 'IP range' },
		{ id: 'time_of_day', label: 'Time of day' },
		{ id: 'day_of_week', label: 'Day of week' },
		{ id: 'user_agent_pattern', label: 'User agent regex' }
	];

	const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

	async function load() {
		loading = true;
		error = null;
		try {
			const data = await getAccessPolicies(orgId);
			policies = data.policies;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load access policies';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	function openCreate() {
		creating = true;
		editing = null;
		fName = '';
		fAction = 'block';
		fActive = true;
		fPriority = 100;
		fConditions = [];
		formError = null;
		modalOpen = true;
	}

	function openEdit(p: AccessPolicy) {
		creating = false;
		editing = p;
		fName = p.name;
		fAction = (p.action as 'allow' | 'block' | 'require_mfa') || 'block';
		fActive = p.is_active;
		fPriority = p.priority;
		fConditions = JSON.parse(JSON.stringify(p.conditions));
		formError = null;
		modalOpen = true;
	}

	function closeModal() {
		modalOpen = false;
	}

	function addCondition(type: string) {
		const cond: AccessPolicyCondition = { type };
		if (type === 'ip_range') cond.cidr = '';
		else if (type === 'time_of_day') {
			cond.start_hour = 9;
			cond.end_hour = 17;
			cond.timezone = 'UTC';
		} else if (type === 'day_of_week') cond.days = [1, 2, 3, 4, 5];
		else if (type === 'user_agent_pattern') cond.pattern = '';
		fConditions = [...fConditions, cond];
	}

	function removeCondition(idx: number) {
		fConditions = fConditions.filter((_, i) => i !== idx);
	}

	function toggleDay(idx: number, day: number) {
		const cond = fConditions[idx];
		if (!cond.days) cond.days = [];
		if (cond.days.includes(day)) {
			cond.days = cond.days.filter((d) => d !== day);
		} else {
			cond.days = [...cond.days, day].sort();
		}
		fConditions = [...fConditions];
	}

	async function save() {
		if (!fName.trim()) {
			formError = 'Name is required';
			return;
		}
		if (fConditions.length === 0) {
			formError = 'Add at least one condition';
			return;
		}
		formError = null;
		saving = true;
		try {
			if (creating) {
				const created = await createAccessPolicy(orgId, {
					name: fName.trim(),
					action: fAction,
					is_active: fActive,
					priority: fPriority,
					conditions: fConditions
				});
				policies = [...policies, created];
			} else if (editing) {
				const updated = await updateAccessPolicy(orgId, editing.id, {
					name: fName.trim(),
					action: fAction,
					is_active: fActive,
					priority: fPriority,
					conditions: fConditions
				});
				policies = policies.map((p) => (p.id === updated.id ? updated : p));
			}
			closeModal();
		} catch (e) {
			formError = e instanceof Error ? e.message : 'Failed to save policy';
		} finally {
			saving = false;
		}
	}

	async function toggleActive(p: AccessPolicy) {
		const updated = await updateAccessPolicy(orgId, p.id, { is_active: !p.is_active });
		policies = policies.map((q) => (q.id === updated.id ? updated : q));
	}

	async function remove(p: AccessPolicy) {
		if (!confirm(`Delete policy "${p.name}"?`)) return;
		await deleteAccessPolicy(orgId, p.id);
		policies = policies.filter((q) => q.id !== p.id);
	}

	function summarizeConditions(conds: AccessPolicyCondition[]): string {
		return conds
			.map((c) => {
				if (c.type === 'ip_range') return `IP ${c.cidr}`;
				if (c.type === 'time_of_day')
					return `${c.start_hour}:00–${c.end_hour}:00 ${c.timezone || ''}`;
				if (c.type === 'day_of_week') return (c.days || []).map((d) => DAYS[d]).join(',');
				if (c.type === 'user_agent_pattern') return `UA /${c.pattern}/`;
				return c.type;
			})
			.join(' · ');
	}
</script>

<div class="space-y-6">
	<div class="flex items-start justify-between gap-4">
		<div>
			<h2 class="text-lg font-medium text-foreground">Conditional Access Policies</h2>
			<p class="mt-1 text-sm text-muted">
				Define rules that allow, block, or require MFA based on IP, time, day, or user agent.
				Policies evaluate in priority order; lower numbers run first.
			</p>
		</div>
		<button
			type="button"
			onclick={openCreate}
			class="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-light hover:bg-foreground/90"
		>
			New policy
		</button>
	</div>

	{#if loading}
		<div class="text-sm text-muted">Loading…</div>
	{:else if error}
		<div class="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700">{error}</div>
	{:else if policies.length === 0}
		<div class="rounded-xl border border-dashed border-divider p-8 text-center text-sm text-muted">
			No policies defined yet.
		</div>
	{:else}
		<div class="space-y-2">
			{#each policies.sort((a, b) => a.priority - b.priority) as p (p.id)}
				<div class="flex items-center justify-between gap-4 rounded-xl border border-divider p-4">
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="font-medium text-foreground">{p.name}</span>
							<span class="text-xs text-muted">priority {p.priority}</span>
							<span
								class="rounded-full px-2 py-0.5 text-xs font-medium {p.action === 'block'
									? 'bg-red-100 text-red-700'
									: p.action === 'allow'
										? 'bg-emerald-100 text-emerald-700'
										: 'bg-amber-100 text-amber-700'}"
							>
								{p.action}
							</span>
							<span
								class="rounded-full px-2 py-0.5 text-xs {p.is_active
									? 'bg-emerald-100 text-emerald-700'
									: 'bg-surface text-muted'}"
							>
								{p.is_active ? 'Active' : 'Inactive'}
							</span>
						</div>
						<div class="mt-1 truncate text-xs text-muted">{summarizeConditions(p.conditions)}</div>
					</div>
					<div class="flex shrink-0 gap-2">
						<button
							type="button"
							onclick={() => toggleActive(p)}
							class="rounded-md border border-divider px-2.5 py-1 text-xs text-muted hover:text-foreground"
						>
							{p.is_active ? 'Disable' : 'Enable'}
						</button>
						<button
							type="button"
							onclick={() => openEdit(p)}
							class="rounded-md border border-divider px-2.5 py-1 text-xs text-muted hover:text-foreground"
						>
							Edit
						</button>
						<button
							type="button"
							onclick={() => remove(p)}
							class="rounded-md border border-divider px-2.5 py-1 text-xs text-muted hover:border-red-300 hover:text-red-600"
						>
							Delete
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

{#if modalOpen}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
		role="dialog"
		aria-modal="true"
	>
		<div class="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-light p-6">
			<h3 class="mb-4 text-lg font-medium text-foreground">
				{creating ? 'New access policy' : 'Edit access policy'}
			</h3>
			<div class="space-y-4">
				<div>
					<label for="ap-name" class="block text-xs font-medium text-muted">Name</label>
					<input
						id="ap-name"
						bind:value={fName}
						class="mt-1 w-full rounded-lg border border-divider px-3 py-2 text-sm"
					/>
				</div>
				<div class="grid grid-cols-2 gap-3">
					<div>
						<label for="ap-action" class="block text-xs font-medium text-muted">Action</label>
						<select
							id="ap-action"
							bind:value={fAction}
							class="mt-1 w-full rounded-lg border border-divider px-3 py-2 text-sm"
						>
							<option value="allow">Allow</option>
							<option value="block">Block</option>
							<option value="require_mfa">Require MFA</option>
						</select>
					</div>
					<div>
						<label for="ap-priority" class="block text-xs font-medium text-muted">Priority</label>
						<input
							id="ap-priority"
							type="number"
							bind:value={fPriority}
							class="mt-1 w-full rounded-lg border border-divider px-3 py-2 text-sm"
						/>
					</div>
				</div>
				<label class="flex items-center gap-2 text-sm">
					<input type="checkbox" bind:checked={fActive} />
					Active
				</label>

				<div>
					<div class="mb-2 flex items-center justify-between">
						<span class="text-xs font-medium text-muted">Conditions</span>
						<div class="flex gap-1">
							{#each CONDITION_TYPES as t}
								<button
									type="button"
									onclick={() => addCondition(t.id)}
									class="rounded-md border border-divider px-2 py-0.5 text-xs text-muted hover:text-foreground"
								>
									+ {t.label}
								</button>
							{/each}
						</div>
					</div>
					<div class="space-y-2">
						{#each fConditions as cond, i}
							<div class="rounded-lg border border-divider p-3">
								<div class="mb-2 flex items-center justify-between">
									<span class="text-xs font-medium text-foreground">
										{CONDITION_TYPES.find((t) => t.id === cond.type)?.label || cond.type}
									</span>
									<button
										type="button"
										onclick={() => removeCondition(i)}
										class="text-xs text-red-600 hover:underline">Remove</button
									>
								</div>
								{#if cond.type === 'ip_range'}
									<input
										bind:value={cond.cidr}
										placeholder="203.0.113.0/24"
										class="w-full rounded-lg border border-divider px-3 py-2 text-sm"
									/>
								{:else if cond.type === 'time_of_day'}
									<div class="grid grid-cols-3 gap-2">
										<input
											type="number"
											min="0"
											max="23"
											bind:value={cond.start_hour}
											placeholder="Start hour"
											class="rounded-lg border border-divider px-3 py-2 text-sm"
										/>
										<input
											type="number"
											min="0"
											max="23"
											bind:value={cond.end_hour}
											placeholder="End hour"
											class="rounded-lg border border-divider px-3 py-2 text-sm"
										/>
										<input
											bind:value={cond.timezone}
											placeholder="UTC"
											class="rounded-lg border border-divider px-3 py-2 text-sm"
										/>
									</div>
								{:else if cond.type === 'day_of_week'}
									<div class="flex flex-wrap gap-1">
										{#each DAYS as day, dIdx}
											<button
												type="button"
												onclick={() => toggleDay(i, dIdx)}
												class="rounded-md px-2.5 py-1 text-xs {cond.days?.includes(dIdx)
													? 'bg-foreground text-light'
													: 'border border-divider text-muted'}"
											>
												{day}
											</button>
										{/each}
									</div>
								{:else if cond.type === 'user_agent_pattern'}
									<input
										bind:value={cond.pattern}
										placeholder="^Mozilla.*Firefox"
										class="w-full rounded-lg border border-divider px-3 py-2 font-mono text-sm"
									/>
								{/if}
							</div>
						{/each}
					</div>
				</div>

				{#if formError}
					<div class="text-sm text-red-600">{formError}</div>
				{/if}

				<div class="flex justify-end gap-2 pt-2">
					<button
						type="button"
						onclick={closeModal}
						class="rounded-lg border border-divider px-4 py-2 text-sm text-muted"
					>
						Cancel
					</button>
					<button
						type="button"
						onclick={save}
						disabled={saving}
						class="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-light hover:bg-foreground/90 disabled:opacity-50"
					>
						{saving ? 'Saving…' : 'Save policy'}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
