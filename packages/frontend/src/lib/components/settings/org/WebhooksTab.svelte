<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import {
		listWebhooks,
		createWebhook,
		updateWebhook,
		deleteWebhook,
		testWebhook,
		listWebhookDeliveries,
		type Organization,
		type OrgWebhook,
		type OrgWebhookCreate,
		type OrgWebhookUpdate,
		type WebhookDelivery
	} from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	const EVENT_TYPES = [
		'agent_run.completed',
		'agent_run.failed',
		'member.joined',
		'member.removed',
		'project.created',
		'project.shared',
		'audit.security_event',
		'dlp.violation'
	];

	let webhooks: OrgWebhook[] = $state([]);
	let loading = $state(true);

	// Form state
	let showForm = $state(false);
	let editingId: string | null = $state(null);
	let formUrl = $state('');
	let formSecret = $state('');
	let formEvents: string[] = $state([]);
	let formDestType = $state('generic');
	let formSaving = $state(false);

	// Action states
	let testingId: string | null = $state(null);
	let confirmDeleteId: string | null = $state(null);
	let deletingId: string | null = $state(null);

	// Delivery log
	let expandedWebhookId: string | null = $state(null);
	let deliveries: Record<string, WebhookDelivery[]> = $state({});
	let deliveriesLoading: string | null = $state(null);

	async function load() {
		loading = true;
		try {
			webhooks = await listWebhooks(orgId);
		} catch {
			toasts.error('Failed to load webhooks.');
		} finally {
			loading = false;
		}
	}

	function openCreateForm() {
		editingId = null;
		formUrl = '';
		formSecret = '';
		formEvents = [];
		formDestType = 'generic';
		showForm = true;
	}

	function openEditForm(wh: OrgWebhook) {
		editingId = wh.id;
		formUrl = wh.url;
		formSecret = '';
		formEvents = [...wh.events];
		formDestType = wh.destination_type;
		showForm = true;
	}

	function closeForm() {
		showForm = false;
		editingId = null;
	}

	function toggleEvent(evt: string) {
		if (formEvents.includes(evt)) {
			formEvents = formEvents.filter((e) => e !== evt);
		} else {
			formEvents = [...formEvents, evt];
		}
	}

	async function handleSave() {
		if (!formUrl.trim() || formEvents.length === 0) return;
		formSaving = true;
		try {
			if (editingId) {
				const data: OrgWebhookUpdate = {
					url: formUrl.trim(),
					events: formEvents,
					destination_type: formDestType
				};
				if (formSecret.trim()) data.secret = formSecret.trim();
				await updateWebhook(orgId, editingId, data);
				toasts.success('Webhook updated.');
			} else {
				const data: OrgWebhookCreate = {
					url: formUrl.trim(),
					secret: formSecret.trim(),
					events: formEvents,
					destination_type: formDestType
				};
				await createWebhook(orgId, data);
				toasts.success('Webhook created.');
			}
			closeForm();
			await load();
		} catch {
			toasts.error('Failed to save webhook.');
		} finally {
			formSaving = false;
		}
	}

	async function handleTest(whId: string) {
		testingId = whId;
		try {
			const result = await testWebhook(orgId, whId);
			if (result.success) {
				toasts.success('Test delivery sent.');
			} else {
				toasts.error(result.message || 'Test delivery failed.');
			}
		} catch {
			toasts.error('Failed to send test delivery.');
		} finally {
			testingId = null;
		}
	}

	async function handleDelete(whId: string) {
		deletingId = whId;
		try {
			await deleteWebhook(orgId, whId);
			toasts.success('Webhook deleted.');
			confirmDeleteId = null;
			await load();
		} catch {
			toasts.error('Failed to delete webhook.');
		} finally {
			deletingId = null;
		}
	}

	async function toggleDeliveries(whId: string) {
		if (expandedWebhookId === whId) {
			expandedWebhookId = null;
			return;
		}
		expandedWebhookId = whId;
		if (!deliveries[whId]) {
			deliveriesLoading = whId;
			try {
				deliveries[whId] = await listWebhookDeliveries(orgId, whId);
			} catch {
				toasts.error('Failed to load deliveries.');
			} finally {
				deliveriesLoading = null;
			}
		}
	}

	function truncateUrl(url: string, max = 50): string {
		return url.length > max ? url.slice(0, max) + '...' : url;
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	onMount(load);
</script>

<div class="space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h3 class="text-sm font-medium text-foreground">Outbound Webhooks</h3>
			<p class="text-xs text-muted">
				Send event notifications to external services when actions occur in your organization.
			</p>
		</div>
		{#if !showForm}
			<button
				onclick={openCreateForm}
				class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70"
			>
				Add Webhook
			</button>
		{/if}
	</div>

	<!-- Create/Edit form -->
	{#if showForm}
		<div
			class="rounded-xl border border-border-subtle bg-surface p-4"
			transition:fade={{ duration: 100 }}
		>
			<h4 class="mb-3 text-xs font-medium text-foreground">
				{editingId ? 'Edit Webhook' : 'New Webhook'}
			</h4>
			<div class="space-y-3">
				<div>
					<label for="wh-url" class="mb-1 block text-xs font-medium text-muted">URL</label>
					<input
						id="wh-url"
						type="url"
						bind:value={formUrl}
						placeholder="https://example.com/webhook"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					/>
				</div>
				<div>
					<label for="wh-secret" class="mb-1 block text-xs font-medium text-muted"
						>Secret {editingId ? '(leave blank to keep existing)' : ''}</label
					>
					<input
						id="wh-secret"
						type="password"
						bind:value={formSecret}
						placeholder="webhook signing secret"
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					/>
				</div>
				<div>
					<label for="wh-dest" class="mb-1 block text-xs font-medium text-muted"
						>Destination Type</label
					>
					<select
						id="wh-dest"
						bind:value={formDestType}
						class="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					>
						<option value="generic">Generic</option>
						<option value="slack">Slack</option>
						<option value="discord">Discord</option>
					</select>
				</div>
				<div>
					<p class="mb-2 text-xs font-medium text-muted">Events</p>
					<div class="flex flex-wrap gap-2">
						{#each EVENT_TYPES as evt}
							<label
								class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs {formEvents.includes(
									evt
								)
									? 'border-accent bg-accent/10 text-foreground'
									: 'text-muted hover:bg-surface'}"
							>
								<input
									type="checkbox"
									class="sr-only"
									checked={formEvents.includes(evt)}
									onchange={() => toggleEvent(evt)}
								/>
								{evt}
							</label>
						{/each}
					</div>
				</div>
				<div class="flex items-center gap-2 pt-1">
					<button
						onclick={handleSave}
						disabled={formSaving || !formUrl.trim() || formEvents.length === 0}
						class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
					>
						{formSaving ? 'Saving...' : editingId ? 'Update' : 'Create'}
					</button>
					<button
						onclick={closeForm}
						class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
					>
						Cancel
					</button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Webhook list -->
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
	{:else if webhooks.length === 0 && !showForm}
		<p class="py-4 text-center text-xs text-muted">No webhooks configured.</p>
	{:else}
		<div class="space-y-3">
			{#each webhooks as wh (wh.id)}
				<div class="rounded-xl border border-border p-4">
					<div class="flex flex-wrap items-center gap-3">
						<div class="min-w-0 flex-1">
							<p class="truncate font-mono text-xs text-foreground" title={wh.url}>
								{truncateUrl(wh.url)}
							</p>
							<div class="mt-1 flex flex-wrap gap-1">
								{#each wh.events as evt}
									<span
										class="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
										>{evt}</span
									>
								{/each}
							</div>
						</div>
						<div class="flex items-center gap-2">
							<span class="text-[10px] text-muted">{wh.destination_type}</span>
							{#if wh.is_active}
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
							{#if wh.failure_count > 0}
								<span
									class="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400"
									>{wh.failure_count} failures</span
								>
							{/if}
						</div>
						<div class="flex items-center gap-1">
							<button
								onclick={() => handleTest(wh.id)}
								disabled={testingId === wh.id}
								class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface disabled:opacity-50"
							>
								{testingId === wh.id ? 'Testing...' : 'Test'}
							</button>
							<button
								onclick={() => toggleDeliveries(wh.id)}
								class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface {expandedWebhookId ===
								wh.id
									? 'bg-surface'
									: ''}"
							>
								Deliveries
							</button>
							<button
								onclick={() => openEditForm(wh)}
								class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface"
							>
								Edit
							</button>
							{#if confirmDeleteId === wh.id}
								<span class="text-xs text-muted">Sure?</span>
								<button
									onclick={() => handleDelete(wh.id)}
									disabled={deletingId === wh.id}
									class="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
								>
									{deletingId === wh.id ? '...' : 'Yes'}
								</button>
								<button
									onclick={() => (confirmDeleteId = null)}
									class="text-xs font-medium text-muted hover:text-foreground">No</button
								>
							{:else}
								<button
									onclick={() => (confirmDeleteId = wh.id)}
									class="rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
								>
									Delete
								</button>
							{/if}
						</div>
					</div>

					<!-- Deliveries panel -->
					{#if expandedWebhookId === wh.id}
						<div class="mt-3 border-t border-border pt-3" transition:fade={{ duration: 100 }}>
							{#if deliveriesLoading === wh.id}
								<div class="flex items-center justify-center py-4">
									<svg
										class="h-4 w-4 animate-spin text-muted"
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
							{:else if deliveries[wh.id]?.length}
								<div class="overflow-x-auto rounded-lg border border-border">
									<table class="w-full text-left">
										<thead class="bg-surface">
											<tr>
												<th class="px-3 py-2 text-[10px] font-medium text-muted">Event</th>
												<th class="px-3 py-2 text-[10px] font-medium text-muted">Status</th>
												<th class="px-3 py-2 text-[10px] font-medium text-muted">Time (ms)</th>
												<th class="px-3 py-2 text-[10px] font-medium text-muted">Result</th>
												<th class="px-3 py-2 text-[10px] font-medium text-muted">Error</th>
												<th class="px-3 py-2 text-[10px] font-medium text-muted">Date</th>
											</tr>
										</thead>
										<tbody class="divide-y divide-border">
											{#each deliveries[wh.id] as d (d.id)}
												<tr>
													<td class="px-3 py-2 text-[10px] text-foreground">{d.event_type}</td>
													<td class="px-3 py-2 text-[10px] text-foreground"
														>{d.status_code ?? '—'}</td
													>
													<td class="px-3 py-2 text-[10px] text-foreground"
														>{d.response_time_ms ?? '—'}</td
													>
													<td class="px-3 py-2">
														{#if d.success}
															<span
																class="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400"
																>OK</span
															>
														{:else}
															<span
																class="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400"
																>Failed</span
															>
														{/if}
													</td>
													<td
														class="max-w-[200px] truncate px-3 py-2 text-[10px] text-muted"
														title={d.error_message}>{d.error_message || '—'}</td
													>
													<td class="px-3 py-2 text-[10px] text-muted"
														>{formatDate(d.created_at)}</td
													>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{:else}
								<p class="py-2 text-center text-[10px] text-muted">No deliveries yet.</p>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
