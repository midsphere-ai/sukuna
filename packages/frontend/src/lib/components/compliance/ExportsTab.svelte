<script lang="ts">
	import { onMount } from 'svelte';
	import { toasts } from '$stores/toast';
	import {
		getExportConfigs,
		createExportConfig,
		updateExportConfig,
		deleteExportConfig,
		runExportNow,
		type ExportConfig,
		type ExportConfigCreate
	} from '$api/compliance';

	let configs: ExportConfig[] = $state([]);
	let loading = $state(true);

	// Create/Edit form state
	let showForm = $state(false);
	let editingId: string | null = $state(null);
	let formSaving = $state(false);
	let formExportType = $state('audit_log');
	let formFormat = $state('csv');
	let formSchedule = $state('daily');
	let formDestType = $state('s3');
	let formActive = $state(true);
	// S3 fields
	let formS3Bucket = $state('');
	let formS3Prefix = $state('');
	let formS3Region = $state('');
	// Email field
	let formEmail = $state('');

	// Per-row action state
	let runningId: string | null = $state(null);
	let deleteState: Record<string, 'idle' | 'confirm' | 'deleting'> = $state({});

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

	async function loadConfigs(): Promise<void> {
		loading = true;
		try {
			configs = await getExportConfigs();
		} catch {
			// Error handled by API client
		} finally {
			loading = false;
		}
	}

	function resetForm(): void {
		formExportType = 'audit_log';
		formFormat = 'csv';
		formSchedule = 'daily';
		formDestType = 's3';
		formActive = true;
		formS3Bucket = '';
		formS3Prefix = '';
		formS3Region = '';
		formEmail = '';
		editingId = null;
	}

	function openCreateForm(): void {
		resetForm();
		showForm = true;
	}

	function openEditForm(config: ExportConfig): void {
		editingId = config.id;
		formExportType = config.export_type;
		formFormat = config.format;
		formSchedule = config.schedule;
		formDestType = config.destination_type;
		formActive = config.is_active;
		if (config.destination_type === 's3') {
			formS3Bucket = config.destination_config.bucket || '';
			formS3Prefix = config.destination_config.prefix || '';
			formS3Region = config.destination_config.region || '';
			formEmail = '';
		} else {
			formEmail = config.destination_config.email || '';
			formS3Bucket = '';
			formS3Prefix = '';
			formS3Region = '';
		}
		showForm = true;
	}

	function cancelForm(): void {
		showForm = false;
		resetForm();
	}

	function buildDestConfig(): Record<string, string> {
		if (formDestType === 's3') {
			return { bucket: formS3Bucket, prefix: formS3Prefix, region: formS3Region };
		}
		return { email: formEmail };
	}

	async function submitForm(): Promise<void> {
		formSaving = true;
		const data: ExportConfigCreate = {
			export_type: formExportType,
			format: formFormat,
			schedule: formSchedule,
			destination_type: formDestType,
			destination_config: buildDestConfig(),
			is_active: formActive
		};

		try {
			if (editingId) {
				await updateExportConfig(editingId, data);
				toasts.success('Export config updated.');
			} else {
				await createExportConfig(data);
				toasts.success('Export config created.');
			}
			showForm = false;
			resetForm();
			await loadConfigs();
		} catch {
			toasts.error('Failed to save export config.');
		} finally {
			formSaving = false;
		}
	}

	async function handleRunNow(id: string): Promise<void> {
		runningId = id;
		try {
			await runExportNow(id);
			toasts.success('Export started.');
			await loadConfigs();
		} catch {
			toasts.error('Failed to run export.');
		} finally {
			runningId = null;
		}
	}

	function handleDeleteClick(id: string): void {
		const current = deleteState[id];
		if (!current || current === 'idle') {
			deleteState[id] = 'confirm';
		}
	}

	function cancelDelete(id: string): void {
		deleteState[id] = 'idle';
	}

	async function confirmDelete(id: string): Promise<void> {
		deleteState[id] = 'deleting';
		try {
			await deleteExportConfig(id);
			toasts.success('Export config deleted.');
			deleteState[id] = 'idle';
			await loadConfigs();
		} catch {
			toasts.error('Failed to delete export config.');
			deleteState[id] = 'idle';
		}
	}

	onMount(() => {
		loadConfigs();
	});
</script>

<div class="space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h3 class="text-sm font-medium text-foreground">Export Configurations</h3>
			<p class="text-xs text-muted">Configure automated compliance data exports.</p>
		</div>
		{#if !showForm}
			<button
				onclick={openCreateForm}
				class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background"
			>
				New Export Config
			</button>
		{/if}
	</div>

	<!-- Create/Edit Form -->
	{#if showForm}
		<div class="rounded-xl border border-border-subtle bg-surface p-4">
			<h4 class="mb-3 text-sm font-medium text-foreground">
				{editingId ? 'Edit Export Config' : 'New Export Config'}
			</h4>
			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
				<div>
					<label for="export-type" class="mb-1 block text-xs font-medium text-muted"
						>Export Type</label
					>
					<select
						id="export-type"
						bind:value={formExportType}
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					>
						<option value="audit_log">Audit Log</option>
						<option value="consent">Consent</option>
						<option value="retention">Retention</option>
					</select>
				</div>
				<div>
					<label for="export-format" class="mb-1 block text-xs font-medium text-muted">Format</label
					>
					<select
						id="export-format"
						bind:value={formFormat}
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					>
						<option value="csv">CSV</option>
						<option value="json">JSON</option>
					</select>
				</div>
				<div>
					<label for="export-schedule" class="mb-1 block text-xs font-medium text-muted"
						>Schedule</label
					>
					<select
						id="export-schedule"
						bind:value={formSchedule}
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					>
						<option value="daily">Daily</option>
						<option value="weekly">Weekly</option>
						<option value="monthly">Monthly</option>
					</select>
				</div>
				<div>
					<label for="export-dest" class="mb-1 block text-xs font-medium text-muted"
						>Destination Type</label
					>
					<select
						id="export-dest"
						bind:value={formDestType}
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					>
						<option value="s3">S3</option>
						<option value="email">Email</option>
					</select>
				</div>
			</div>

			<!-- Conditional destination fields -->
			<div class="mt-4">
				{#if formDestType === 's3'}
					<div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
						<div>
							<label for="s3-bucket" class="mb-1 block text-xs font-medium text-muted"
								>S3 Bucket</label
							>
							<input
								id="s3-bucket"
								type="text"
								bind:value={formS3Bucket}
								placeholder="my-compliance-bucket"
								class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
							/>
						</div>
						<div>
							<label for="s3-prefix" class="mb-1 block text-xs font-medium text-muted">Prefix</label
							>
							<input
								id="s3-prefix"
								type="text"
								bind:value={formS3Prefix}
								placeholder="exports/"
								class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
							/>
						</div>
						<div>
							<label for="s3-region" class="mb-1 block text-xs font-medium text-muted">Region</label
							>
							<input
								id="s3-region"
								type="text"
								bind:value={formS3Region}
								placeholder="us-east-1"
								class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
							/>
						</div>
					</div>
				{:else}
					<div>
						<label for="dest-email" class="mb-1 block text-xs font-medium text-muted"
							>Email Address</label
						>
						<input
							id="dest-email"
							type="email"
							bind:value={formEmail}
							placeholder="compliance@example.com"
							class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
						/>
					</div>
				{/if}
			</div>

			<!-- Active toggle -->
			<div class="mt-4 flex items-center gap-3">
				<label for="export-active" class="text-xs font-medium text-muted">Active</label>
				<button
					id="export-active"
					onclick={() => (formActive = !formActive)}
					class="relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200 {formActive
						? 'bg-green-500'
						: 'bg-gray-300 dark:bg-gray-600'}"
				>
					<span
						class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 {formActive
							? 'translate-x-5'
							: 'translate-x-0'}"
					></span>
				</button>
			</div>

			<!-- Form actions -->
			<div class="mt-4 flex gap-2">
				<button
					onclick={submitForm}
					disabled={formSaving}
					class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background disabled:opacity-50"
				>
					{formSaving ? 'Saving...' : editingId ? 'Update' : 'Create'}
				</button>
				<button
					onclick={cancelForm}
					disabled={formSaving}
					class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground hover:bg-surface"
				>
					Cancel
				</button>
			</div>
		</div>
	{/if}

	<!-- Table -->
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
	{:else if configs.length > 0}
		<div class="overflow-x-auto rounded-xl border border-border">
			<table class="w-full text-left text-sm">
				<thead>
					<tr class="border-b border-border-subtle bg-surface">
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Type</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Format</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Schedule</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Destination</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Status</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Last Export</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Records</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each configs as config (config.id)}
						<tr class="border-b border-border-subtle last:border-0">
							<td class="px-4 py-2.5 text-xs text-foreground capitalize">
								{config.export_type.replace(/_/g, ' ')}
							</td>
							<td class="px-4 py-2.5 text-xs text-foreground uppercase">{config.format}</td>
							<td class="px-4 py-2.5 text-xs text-foreground capitalize">{config.schedule}</td>
							<td class="px-4 py-2.5 text-xs text-muted uppercase">{config.destination_type}</td>
							<td class="px-4 py-2.5">
								<span
									class="rounded-lg px-2.5 py-1 text-xs font-medium {config.is_active
										? 'bg-green-100 text-green-800'
										: 'bg-gray-100 text-gray-600'}"
								>
									{config.is_active ? 'Active' : 'Inactive'}
								</span>
							</td>
							<td class="whitespace-nowrap px-4 py-2.5 text-xs text-muted">
								{config.last_export_at ? formatDate(config.last_export_at) : 'Never'}
							</td>
							<td class="px-4 py-2.5 text-xs text-muted">
								{config.last_export_record_count}
							</td>
							<td class="px-4 py-2.5">
								<div class="flex gap-2">
									<button
										onclick={() => openEditForm(config)}
										class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface"
									>
										Edit
									</button>
									<button
										onclick={() => handleRunNow(config.id)}
										disabled={runningId === config.id}
										class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface disabled:opacity-50"
									>
										{runningId === config.id ? 'Running...' : 'Run Now'}
									</button>
									{#if deleteState[config.id] === 'confirm'}
										<button
											onclick={() => confirmDelete(config.id)}
											class="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white"
										>
											Confirm
										</button>
										<button
											onclick={() => cancelDelete(config.id)}
											class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface"
										>
											Cancel
										</button>
									{:else if deleteState[config.id] === 'deleting'}
										<span class="px-3 py-1.5 text-xs text-muted">Deleting...</span>
									{:else}
										<button
											onclick={() => handleDeleteClick(config.id)}
											class="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
										>
											Delete
										</button>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<p class="py-8 text-center text-sm text-muted">No export configurations found.</p>
	{/if}
</div>
