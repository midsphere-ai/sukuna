<script lang="ts">
	import { onMount } from 'svelte';
	import { toasts } from '$stores/toast';
	import {
		getConsentOverview,
		getUserConsent,
		updateUserConsent,
		getConsentHistory,
		type ConsentOverview,
		type UserConsentStatus,
		type ConsentRecord
	} from '$api/compliance';

	let consentData: ConsentOverview | null = $state(null);
	let userConsent: UserConsentStatus | null = $state(null);
	let consentHistory: ConsentRecord[] = $state([]);
	let loading = $state(true);
	let historyExpanded = $state(false);
	let historyLoading = $state(false);
	let togglingType: string | null = $state(null);

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

	async function loadOverview(): Promise<void> {
		try {
			consentData = await getConsentOverview();
		} catch {
			// Error handled by API client
		}
	}

	async function loadUserConsent(): Promise<void> {
		try {
			userConsent = await getUserConsent();
		} catch {
			// Error handled by API client
		}
	}

	async function loadHistory(): Promise<void> {
		historyLoading = true;
		try {
			consentHistory = await getConsentHistory();
		} catch {
			// Error handled by API client
		} finally {
			historyLoading = false;
		}
	}

	async function toggleConsent(consentType: string, currentAction: string | null): Promise<void> {
		togglingType = consentType;
		const newAction = currentAction === 'granted' ? 'revoked' : 'granted';
		try {
			await updateUserConsent({
				consent_type: consentType,
				action: newAction as 'granted' | 'revoked',
				version: '1.0'
			});
			toasts.success(`Consent ${newAction} for ${consentType.replace(/_/g, ' ')}.`);
			await loadUserConsent();
			// Refresh overview too so counts update
			await loadOverview();
			// Refresh history if expanded
			if (historyExpanded) {
				await loadHistory();
			}
		} catch {
			toasts.error('Failed to update consent preference.');
		} finally {
			togglingType = null;
		}
	}

	function toggleHistory(): void {
		historyExpanded = !historyExpanded;
		if (historyExpanded && consentHistory.length === 0) {
			loadHistory();
		}
	}

	onMount(async () => {
		await Promise.all([loadOverview(), loadUserConsent()]);
		loading = false;
	});
</script>

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
{:else}
	<div class="space-y-6">
		<!-- Org Overview Section -->
		<div class="space-y-4">
			<div>
				<h3 class="text-sm font-medium text-foreground">Consent Overview</h3>
				<p class="text-xs text-muted">
					Per-type consent status across {consentData?.total_users ?? 0} active users.
				</p>
			</div>

			{#if consentData}
				<div class="space-y-3">
					{#each Object.entries(consentData.consent_types) as [key, info] (key)}
						<div class="rounded-xl border border-border p-4">
							<div class="flex items-center justify-between">
								<p class="text-sm font-medium text-foreground capitalize">{info.label}</p>
								<span class="text-sm font-medium text-foreground">{info.coverage_percentage}%</span>
							</div>
							<div class="mt-2 h-1.5 w-full rounded-full bg-surface">
								<div
									class="h-1.5 rounded-full bg-green-500 transition-all duration-500"
									style="width: {Math.min(info.coverage_percentage, 100)}%"
								></div>
							</div>
							<div class="mt-2 flex gap-4 text-xs text-muted">
								<span>
									<span class="font-medium text-green-600 dark:text-green-400"
										>{info.granted_count}</span
									> granted
								</span>
								<span>
									<span class="font-medium text-red-600 dark:text-red-400"
										>{info.revoked_count}</span
									>
									revoked
								</span>
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<p class="py-8 text-center text-sm text-muted">No consent data available.</p>
			{/if}
		</div>

		<!-- Your Consent Preferences Section -->
		<div class="space-y-4">
			<div>
				<h3 class="text-sm font-medium text-foreground">Your Consent Preferences</h3>
				<p class="text-xs text-muted">Manage your personal consent settings.</p>
			</div>

			{#if userConsent}
				<div class="space-y-3">
					{#each Object.entries(userConsent) as [consentType, status] (consentType)}
						<div class="flex items-center justify-between rounded-xl border border-border p-4">
							<div>
								<p class="text-sm font-medium text-foreground capitalize">
									{consentType.replace(/_/g, ' ')}
								</p>
								<p class="text-xs text-muted">
									{#if status.recorded_at}
										Last updated: {formatDate(status.recorded_at)}
										{#if status.version}
											&middot; v{status.version}
										{/if}
									{:else}
										No action recorded
									{/if}
								</p>
							</div>
							<button
								onclick={() => toggleConsent(consentType, status.action)}
								disabled={togglingType === consentType}
								class="relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200 {status.action ===
								'granted'
									? 'bg-green-500'
									: 'bg-gray-300 dark:bg-gray-600'} disabled:opacity-50"
							>
								<span
									class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 {status.action ===
									'granted'
										? 'translate-x-5'
										: 'translate-x-0'}"
								></span>
							</button>
						</div>
					{/each}
				</div>
			{:else}
				<p class="py-4 text-center text-sm text-muted">No consent preferences found.</p>
			{/if}
		</div>

		<!-- Consent History Section -->
		<div class="space-y-4">
			<button onclick={toggleHistory} class="flex w-full items-center gap-2 text-left">
				<svg
					class="h-4 w-4 text-muted transition-transform duration-200 {historyExpanded
						? 'rotate-90'
						: ''}"
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
				</svg>
				<div>
					<h3 class="text-sm font-medium text-foreground">Consent History</h3>
					<p class="text-xs text-muted">Timeline of all consent changes.</p>
				</div>
			</button>

			{#if historyExpanded}
				{#if historyLoading}
					<div class="flex items-center justify-center py-8">
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
				{:else if consentHistory.length > 0}
					<div class="overflow-x-auto rounded-xl border border-border">
						<table class="w-full text-left text-sm">
							<thead>
								<tr class="border-b border-border-subtle bg-surface">
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Consent Type</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Action</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Version</th>
									<th class="px-4 py-2.5 text-xs font-medium text-muted">Recorded At</th>
								</tr>
							</thead>
							<tbody>
								{#each consentHistory as record (record.id)}
									<tr class="border-b border-border-subtle last:border-0">
										<td class="px-4 py-2.5 text-xs text-foreground capitalize">
											{record.consent_type.replace(/_/g, ' ')}
										</td>
										<td class="px-4 py-2.5">
											<span
												class="rounded-lg px-2 py-0.5 text-xs font-medium {record.action ===
												'granted'
													? 'bg-green-100 text-green-800'
													: 'bg-red-100 text-red-800'}"
											>
												{record.action}
											</span>
										</td>
										<td class="px-4 py-2.5 text-xs text-muted">v{record.version}</td>
										<td class="whitespace-nowrap px-4 py-2.5 text-xs text-muted">
											{formatDate(record.recorded_at)}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="py-4 text-center text-sm text-muted">No consent history recorded.</p>
				{/if}
			{/if}
		</div>
	</div>
{/if}
