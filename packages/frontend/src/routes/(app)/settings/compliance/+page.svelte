<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { goto } from '$app/navigation';
	import { get } from 'svelte/store';
	import { authToken } from '$stores/auth';
	import { toasts } from '$stores/toast';
	import {
		getDashboardSummary,
		getAuditLog,
		getMFAStatus,
		getEffectiveSecurityPolicy,
		exportAuditLogUrl,
		type DashboardSummary,
		type AuditLogPage,
		type AuditLogFilters,
		type MFAStatus,
		type EffectiveSecurityPolicy
	} from '$api/compliance';
	import RetentionTab from '$lib/components/compliance/RetentionTab.svelte';
	import ConsentTab from '$lib/components/compliance/ConsentTab.svelte';
	import ExportsTab from '$lib/components/compliance/ExportsTab.svelte';
	import ArchivesTab from '$lib/components/compliance/ArchivesTab.svelte';
	import SideNav from '$lib/components/ui/SideNav.svelte';

	type Tab = 'overview' | 'audit' | 'retention' | 'consent' | 'security' | 'exports' | 'archives';
	let activeTab: Tab = $state('overview');

	const navItems: { id: Tab; label: string }[] = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'audit', label: 'Audit Log' },
		{ id: 'retention', label: 'Data Retention' },
		{ id: 'consent', label: 'Consent' },
		{ id: 'security', label: 'Security' },
		{ id: 'exports', label: 'Exports' },
		{ id: 'archives', label: 'Archives' }
	];
	let loading = $state(true);
	let accessDenied = $state(false);

	// Overview state
	let summary: DashboardSummary | null = $state(null);

	// Audit log state
	let auditData: AuditLogPage | null = $state(null);
	let auditLoading = $state(false);
	let auditFilters: AuditLogFilters = $state({
		page: 1,
		page_size: 25
	});
	let searchQuery = $state('');
	let filterAction = $state('');
	let filterResourceType = $state('');
	let filterDateFrom = $state('');
	let filterDateTo = $state('');

	// Security state
	let mfaData: MFAStatus | null = $state(null);
	let effectivePolicy: EffectiveSecurityPolicy | null = $state(null);

	async function loadSummary(): Promise<void> {
		try {
			summary = await getDashboardSummary();
		} catch (err: unknown) {
			if (
				err &&
				typeof err === 'object' &&
				'status' in err &&
				(err as { status: number }).status === 403
			) {
				accessDenied = true;
			}
		}
	}

	async function loadAuditLog(): Promise<void> {
		auditLoading = true;
		try {
			const filters: AuditLogFilters = {
				page: auditFilters.page,
				page_size: auditFilters.page_size
			};
			if (searchQuery.trim()) filters.q = searchQuery.trim();
			if (filterAction) filters.action = filterAction;
			if (filterResourceType) filters.resource_type = filterResourceType;
			if (filterDateFrom) filters.date_from = filterDateFrom;
			if (filterDateTo) filters.date_to = filterDateTo;
			auditData = await getAuditLog(filters);
		} catch {
			// Error handled by API client
		} finally {
			auditLoading = false;
		}
	}

	async function loadMFA(): Promise<void> {
		try {
			mfaData = await getMFAStatus();
		} catch {
			// Error handled by API client
		}
	}

	async function loadEffectivePolicy(): Promise<void> {
		try {
			effectivePolicy = await getEffectiveSecurityPolicy();
		} catch {
			// silent — endpoint may be unavailable for non-org users
		}
	}

	function handleSearch(): void {
		auditFilters.page = 1;
		loadAuditLog();
	}

	function handleAuditPage(newPage: number): void {
		auditFilters.page = newPage;
		loadAuditLog();
	}

	function handleExportCSV(): void {
		const filters: AuditLogFilters = {};
		if (searchQuery.trim()) filters.q = searchQuery.trim();
		if (filterAction) filters.action = filterAction;
		if (filterResourceType) filters.resource_type = filterResourceType;
		if (filterDateFrom) filters.date_from = filterDateFrom;
		if (filterDateTo) filters.date_to = filterDateTo;

		const url = exportAuditLogUrl(filters);
		const token = get(authToken);
		// Download via hidden link with auth header workaround: fetch blob
		fetch(url, {
			headers: token ? { Authorization: `Bearer ${token}` } : {}
		})
			.then((res) => {
				if (!res.ok) throw new Error('Export failed');
				return res.blob();
			})
			.then((blob) => {
				const a = document.createElement('a');
				a.href = URL.createObjectURL(blob);
				a.download = 'audit_log_export.csv';
				a.click();
				URL.revokeObjectURL(a.href);
				toasts.success('Audit log exported.');
			})
			.catch(() => {
				toasts.error('Failed to export audit log.');
			});
	}

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

	function formatAction(action: string): string {
		return action.replace(/_/g, ' ');
	}

	onMount(async () => {
		await loadSummary();
		if (accessDenied) {
			loading = false;
			return;
		}
		loading = false;
		// Eagerly load tabs data (retention + consent now self-load in their components)
		loadAuditLog();
		loadMFA();
		loadEffectivePolicy();
	});
</script>

{#if loading}
	<div class="flex h-full items-center justify-center py-16">
		<svg
			class="h-6 w-6 animate-spin text-muted"
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
{:else if accessDenied}
	<div class="flex h-full flex-col items-center justify-center py-16">
		<p class="text-sm font-medium text-foreground">Access Denied</p>
		<p class="mt-1 text-xs text-muted">
			You don't have permission to view the compliance dashboard.
		</p>
		<button
			onclick={() => goto('/')}
			class="mt-4 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90"
		>
			Go Home
		</button>
	</div>
{:else}
	<div class="flex w-full">
		<SideNav
			bind:value={activeTab}
			items={navItems}
			title="Compliance"
			searchParamKey="section"
			class="px-4 py-8"
		/>

		<div class="min-w-0 flex-1 px-6 py-8">
			<!-- Tab content -->
			{#key activeTab}
				<div in:fade={{ duration: 100, delay: 30 }} out:fade={{ duration: 60 }}>
					{#if activeTab === 'overview'}
						<!-- Effective security policy panel -->
						{#if effectivePolicy}
							<div class="mb-4 rounded-xl border border-border p-4">
								<div class="mb-3 flex items-center justify-between">
									<div>
										<h3 class="text-sm font-medium text-foreground">Effective security policy</h3>
										<p class="text-xs text-muted">
											The most restrictive policy across all your organizations.
										</p>
									</div>
									<span
										class="rounded-full px-2.5 py-0.5 text-xs font-medium {effectivePolicy.mfa_enabled
											? 'bg-emerald-100 text-emerald-700'
											: effectivePolicy.mfa_required
												? 'bg-red-100 text-red-700'
												: 'bg-surface text-muted'}"
									>
										{effectivePolicy.mfa_enabled
											? 'MFA active'
											: effectivePolicy.mfa_required
												? 'MFA required (not enrolled)'
												: 'MFA optional'}
									</span>
								</div>
								<dl class="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
									<div>
										<dt class="text-xs text-muted">MFA</dt>
										<dd class="font-medium text-foreground">
											{effectivePolicy.mfa_required ? 'Required' : 'Optional'}
										</dd>
									</div>
									<div>
										<dt class="text-xs text-muted">Session timeout</dt>
										<dd class="font-medium text-foreground">
											{effectivePolicy.session_timeout_minutes
												? `${effectivePolicy.session_timeout_minutes} min`
												: 'No limit'}
										</dd>
									</div>
									<div>
										<dt class="text-xs text-muted">Max concurrent sessions</dt>
										<dd class="font-medium text-foreground">
											{effectivePolicy.max_concurrent_sessions ?? 'No limit'}
										</dd>
									</div>
								</dl>
							</div>
						{/if}
						<!-- Overview Tab -->
						{#if summary}
							<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
								<!-- Total Audit Entries -->
								<div class="rounded-xl border border-border p-4">
									<p class="text-xs font-medium text-muted">Audit Entries</p>
									<p class="mt-1 text-2xl font-medium text-foreground">
										{summary.total_audit_entries.toLocaleString()}
									</p>
								</div>

								<!-- Active Retention Policies -->
								<div class="rounded-xl border border-border p-4">
									<p class="text-xs font-medium text-muted">Active Retention Policies</p>
									<p class="mt-1 text-2xl font-medium text-foreground">
										{summary.active_retention_policies}
									</p>
								</div>

								<!-- Consent Coverage -->
								<div class="rounded-xl border border-border p-4">
									<p class="text-xs font-medium text-muted">Consent Coverage</p>
									<p class="mt-1 text-2xl font-medium text-foreground">
										{summary.consent_coverage_percentage}%
									</p>
									<div class="mt-2 h-1.5 w-full rounded-full bg-surface">
										<div
											class="h-1.5 rounded-full bg-green-500 transition-all duration-500"
											style="width: {Math.min(summary.consent_coverage_percentage, 100)}%"
										></div>
									</div>
								</div>

								<!-- MFA Adoption -->
								<div class="rounded-xl border border-border p-4">
									<p class="text-xs font-medium text-muted">MFA Adoption</p>
									<p class="mt-1 text-2xl font-medium text-foreground">
										{summary.mfa_enabled_percentage}%
									</p>
									<p class="mt-0.5 text-xs text-muted">
										{summary.mfa_enabled_count} of {summary.total_users} users
									</p>
								</div>
							</div>
						{:else}
							<p class="text-sm text-muted">Failed to load summary data.</p>
						{/if}
					{:else if activeTab === 'audit'}
						<!-- Audit Log Tab -->
						<div class="space-y-4">
							<!-- Filters -->
							<div class="flex flex-wrap items-end gap-3">
								<div class="flex-1 min-w-[200px]">
									<label for="audit-search" class="mb-1 block text-xs font-medium text-muted"
										>Search</label
									>
									<input
										id="audit-search"
										type="text"
										bind:value={searchQuery}
										onkeydown={(e) => {
											if (e.key === 'Enter') handleSearch();
										}}
										placeholder="Search audit logs..."
										class="w-full rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								</div>
								<div>
									<label for="audit-action" class="mb-1 block text-xs font-medium text-muted"
										>Action</label
									>
									<input
										id="audit-action"
										type="text"
										bind:value={filterAction}
										placeholder="e.g. export"
										class="w-32 rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								</div>
								<div>
									<label for="audit-resource" class="mb-1 block text-xs font-medium text-muted"
										>Resource</label
									>
									<input
										id="audit-resource"
										type="text"
										bind:value={filterResourceType}
										placeholder="e.g. user"
										class="w-32 rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								</div>
								<div>
									<label for="audit-from" class="mb-1 block text-xs font-medium text-muted"
										>From</label
									>
									<input
										id="audit-from"
										type="date"
										bind:value={filterDateFrom}
										class="rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								</div>
								<div>
									<label for="audit-to" class="mb-1 block text-xs font-medium text-muted">To</label>
									<input
										id="audit-to"
										type="date"
										bind:value={filterDateTo}
										class="rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								</div>
								<button
									onclick={handleSearch}
									class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90"
								>
									Search
								</button>
								<button
									onclick={handleExportCSV}
									class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:border-border-strong hover:bg-surface-2"
								>
									Export CSV
								</button>
							</div>

							<!-- Table -->
							{#if auditLoading}
								<div class="flex items-center justify-center py-12">
									<svg
										class="h-5 w-5 animate-spin text-muted"
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
									>
										<circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
										></circle>
										<path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path>
									</svg>
								</div>
							{:else if auditData && auditData.results.length > 0}
								<div class="overflow-x-auto rounded-xl border border-border">
									<table class="w-full text-left text-sm">
										<thead>
											<tr class="border-b border-border-subtle bg-surface">
												<th class="px-4 py-2.5 text-xs font-medium text-muted">Timestamp</th>
												<th class="px-4 py-2.5 text-xs font-medium text-muted">Actor</th>
												<th class="px-4 py-2.5 text-xs font-medium text-muted">Action</th>
												<th class="px-4 py-2.5 text-xs font-medium text-muted">Resource</th>
												<th class="px-4 py-2.5 text-xs font-medium text-muted">IP</th>
											</tr>
										</thead>
										<tbody>
											{#each auditData.results as entry (entry.id)}
												<tr class="border-b border-border-subtle last:border-0">
													<td class="whitespace-nowrap px-4 py-2.5 text-xs text-foreground"
														>{formatDate(entry.timestamp)}</td
													>
													<td class="px-4 py-2.5 text-xs text-foreground"
														>{entry.actor_email || '-'}</td
													>
													<td class="px-4 py-2.5">
														<span
															class="rounded-lg bg-surface px-2 py-0.5 text-xs font-medium text-foreground"
														>
															{formatAction(entry.action)}
														</span>
													</td>
													<td class="px-4 py-2.5 text-xs text-muted"
														>{entry.resource_type}{entry.resource_id
															? ` / ${entry.resource_id.slice(0, 8)}`
															: ''}</td
													>
													<td class="px-4 py-2.5 text-xs text-muted">{entry.actor_ip || '-'}</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>

								<!-- Pagination -->
								{#if auditData.total_pages > 1}
									<div class="flex items-center justify-between">
										<p class="text-xs text-muted">
											Page {auditData.page} of {auditData.total_pages} ({auditData.total} total)
										</p>
										<div class="flex gap-2">
											<button
												onclick={() => handleAuditPage(auditData!.page - 1)}
												disabled={auditData.page <= 1}
												class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-40"
											>
												Previous
											</button>
											<button
												onclick={() => handleAuditPage(auditData!.page + 1)}
												disabled={auditData.page >= auditData.total_pages}
												class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-40"
											>
												Next
											</button>
										</div>
									</div>
								{/if}
							{:else}
								<p class="py-8 text-center text-sm text-muted">No audit log entries found.</p>
							{/if}
						</div>
					{:else if activeTab === 'retention'}
						<RetentionTab />
					{:else if activeTab === 'consent'}
						<ConsentTab />
					{:else if activeTab === 'exports'}
						<ExportsTab />
					{:else if activeTab === 'archives'}
						<ArchivesTab />
					{:else if activeTab === 'security'}
						<!-- Security Tab -->
						<div class="space-y-6">
							<!-- MFA Stats -->
							{#if mfaData}
								<div>
									<h3 class="text-sm font-medium text-foreground">MFA Adoption</h3>
									<p class="text-xs text-muted">
										Multi-factor authentication enrollment across the platform.
									</p>

									<div class="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
										<div class="rounded-xl border border-border p-4">
											<p class="text-xs font-medium text-muted">Total Users</p>
											<p class="mt-1 text-2xl font-medium text-foreground">{mfaData.total_users}</p>
										</div>
										<div class="rounded-xl border border-border p-4">
											<p class="text-xs font-medium text-muted">MFA Enabled</p>
											<p class="mt-1 text-2xl font-medium text-foreground">
												{mfaData.mfa_enabled_count}
											</p>
										</div>
										<div class="rounded-xl border border-border p-4">
											<p class="text-xs font-medium text-muted">MFA Adoption Rate</p>
											<p class="mt-1 text-2xl font-medium text-foreground">
												{mfaData.mfa_enabled_percentage}%
											</p>
											<div class="mt-2 h-1.5 w-full rounded-full bg-surface">
												<div
													class="h-1.5 rounded-full bg-green-500 transition-all duration-500"
													style="width: {Math.min(mfaData.mfa_enabled_percentage, 100)}%"
												></div>
											</div>
										</div>
									</div>
								</div>

								<!-- Per-Org Enforcement -->
								{#if mfaData.organizations.length > 0}
									<div>
										<h3 class="text-sm font-medium text-foreground">
											Organization MFA Enforcement
										</h3>
										<p class="text-xs text-muted">Per-organization MFA policy status.</p>

										<div class="mt-3 rounded-xl border border-border">
											{#each mfaData.organizations as org, i (org.id)}
												<div
													class="flex items-center justify-between px-4 py-3 {i <
													mfaData.organizations.length - 1
														? 'border-b border-border-subtle'
														: ''}"
												>
													<div class="min-w-0 flex-1">
														<p class="truncate text-sm font-medium text-foreground">{org.name}</p>
														<p class="text-xs text-muted">
															{org.member_count} member{org.member_count !== 1 ? 's' : ''}
														</p>
													</div>
													<span
														class="ml-3 shrink-0 rounded-lg px-2.5 py-1 text-xs font-medium {org.mfa_required
															? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
															: 'bg-surface text-muted'}"
													>
														{org.mfa_required ? 'Enforced' : 'Optional'}
													</span>
												</div>
											{/each}
										</div>
									</div>
								{/if}
							{:else}
								<p class="py-8 text-center text-sm text-muted">No security data available.</p>
							{/if}
						</div>
					{/if}
				</div>
			{/key}
		</div>
	</div>
{/if}
