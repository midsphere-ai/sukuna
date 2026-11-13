<script lang="ts">
	import { userSettings, saveSettings } from '$stores/settings';
	import { consentPreferences, updateConsent } from '$stores/consent';
	import { deleteAllConversations } from '$api/conversations';
	import { getUserAddons, unregisterAddon } from '$api/addons';
	import { exportUserData, deleteUserAccount } from '$api/compliance';
	import { ApiClientError } from '$api/client';
	import { conversations } from '$stores/conversations';
	import { clearAuth } from '$stores/auth';
	import { goto } from '$app/navigation';
	import { toasts } from '$stores/toast';

	let dataShareAnalytics = $state(true);
	let dataShareTraining = $state(false);
	let analyticsConsent = $state(false);
	let errorTrackingConsent = $state(false);

	userSettings.subscribe((s) => {
		dataShareAnalytics = s.data_share_analytics;
		dataShareTraining = s.data_share_training;
	});

	consentPreferences.subscribe((p) => {
		analyticsConsent = p.analytics;
		errorTrackingConsent = p.errorTracking;
	});

	// Delete all conversations
	type DeleteConvState = 'idle' | 'confirm' | 'deleting';
	let deleteConvState: DeleteConvState = $state('idle');

	async function handleDeleteAllConversations(): Promise<void> {
		if (deleteConvState === 'idle') {
			deleteConvState = 'confirm';
			return;
		}
		deleteConvState = 'deleting';
		try {
			await deleteAllConversations();
			conversations.set([]);
			toasts.success('All conversations deleted.');
			deleteConvState = 'idle';
		} catch {
			toasts.error('Failed to delete conversations.');
			deleteConvState = 'confirm';
		}
	}

	function cancelDeleteConversations(): void {
		deleteConvState = 'idle';
	}

	// Delete all addons
	type DeleteAddonsState = 'idle' | 'confirm' | 'deleting';
	let deleteAddonsState: DeleteAddonsState = $state('idle');

	async function handleDeleteAllAddons(): Promise<void> {
		if (deleteAddonsState === 'idle') {
			deleteAddonsState = 'confirm';
			return;
		}
		deleteAddonsState = 'deleting';
		try {
			// Fetch all user addons and unregister each one
			const result = await getUserAddons(1);
			const allAddons = result.items;

			for (const addon of allAddons) {
				await unregisterAddon(addon.id);
			}

			toasts.success(`Removed ${allAddons.length} addon${allAddons.length !== 1 ? 's' : ''}.`);
			deleteAddonsState = 'idle';
		} catch {
			toasts.error('Failed to remove addons.');
			deleteAddonsState = 'confirm';
		}
	}

	function cancelDeleteAddons(): void {
		deleteAddonsState = 'idle';
	}

	// Toggle handlers
	function handleAnalyticsToggle(checked: boolean): void {
		dataShareAnalytics = checked;
		saveSettings({ data_share_analytics: checked });
		updateConsent({ analytics: checked });
	}

	function handleErrorTrackingToggle(checked: boolean): void {
		updateConsent({ errorTracking: checked });
	}

	function handleTrainingToggle(checked: boolean): void {
		dataShareTraining = checked;
		saveSettings({ data_share_training: checked });
	}

	// ── Data Export (GDPR) ──────────────────────────────────────────────────
	type ExportState = 'idle' | 'exporting';
	let exportState: ExportState = $state('idle');

	async function handleExportData(): Promise<void> {
		exportState = 'exporting';
		try {
			const data = await exportUserData();
			const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = 'midsphere-data-export.json';
			a.click();
			URL.revokeObjectURL(url);
			toasts.success('Data export downloaded.');
		} catch {
			toasts.error('Failed to export data.');
		} finally {
			exportState = 'idle';
		}
	}

	// ── Delete Account (GDPR) ──────────────────────────────────────────────
	type GdprDeleteStep = 'idle' | 'warning' | 'reason' | 'confirm' | 'deleting';
	let gdprDeleteStep: GdprDeleteStep = $state('idle');
	let deleteReason: string = $state('');
	let deleteConfirmText: string = $state('');
	let ownedOrgs: { id: string; name: string }[] = $state([]);

	function startAccountDeletion(): void {
		gdprDeleteStep = 'warning';
		ownedOrgs = [];
	}

	function cancelAccountDeletion(): void {
		gdprDeleteStep = 'idle';
		deleteReason = '';
		deleteConfirmText = '';
		ownedOrgs = [];
	}

	async function handleDeleteAccount(): Promise<void> {
		gdprDeleteStep = 'deleting';
		try {
			await deleteUserAccount({ confirm: true, reason: deleteReason || undefined });
			toasts.success('Your account has been deleted.');
			clearAuth();
			goto('/login');
		} catch (error) {
			if (error instanceof ApiClientError && error.status === 409) {
				const detail = error.detail as
					{ detail?: string; owned_orgs?: { id: string; name: string }[] } | undefined;
				ownedOrgs = detail?.owned_orgs ?? [];
				gdprDeleteStep = 'warning';
			} else {
				toasts.error('Failed to delete account.');
				gdprDeleteStep = 'confirm';
			}
		}
	}
</script>

<div class="space-y-5">
	<!-- Data Sharing -->
	<section>
		<div>
			<h3 class="text-sm font-medium text-foreground">Data Sharing</h3>
			<p class="text-xs text-muted">
				Control how your data is used. These settings apply immediately.
			</p>
		</div>

		<div class="mt-3 space-y-1">
			<!-- Analytics (PostHog) -->
			<label
				for="settings-data-analytics"
				class="flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 transition-colors hover:bg-surface-2"
			>
				<div class="mr-4">
					<span class="text-sm font-medium text-foreground">Product Usage Analytics</span>
					<p class="mt-0.5 text-xs text-muted">
						Help us improve Jatayu AI by sending anonymous usage data via PostHog
					</p>
				</div>
				<div class="relative shrink-0">
					<input
						id="settings-data-analytics"
						type="checkbox"
						role="switch"
						checked={dataShareAnalytics && analyticsConsent}
						onchange={(e: Event) => handleAnalyticsToggle((e.target as HTMLInputElement).checked)}
						aria-checked={dataShareAnalytics && analyticsConsent}
						class="peer sr-only"
					/>
					<div
						class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
					></div>
					<div
						class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
					></div>
				</div>
			</label>

			<!-- Error Tracking (Sentry) -->
			<label
				for="settings-data-error-tracking"
				class="flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 transition-colors hover:bg-surface-2"
			>
				<div class="mr-4">
					<span class="text-sm font-medium text-foreground">Error Reports</span>
					<p class="mt-0.5 text-xs text-muted">
						Send error reports via Sentry to help us fix bugs faster
					</p>
				</div>
				<div class="relative shrink-0">
					<input
						id="settings-data-error-tracking"
						type="checkbox"
						role="switch"
						checked={errorTrackingConsent}
						onchange={(e: Event) =>
							handleErrorTrackingToggle((e.target as HTMLInputElement).checked)}
						aria-checked={errorTrackingConsent}
						class="peer sr-only"
					/>
					<div
						class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
					></div>
					<div
						class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
					></div>
				</div>
			</label>

			<!-- System-wide Memory / Training -->
			<label
				for="settings-data-training"
				class="flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 transition-colors hover:bg-surface-2"
			>
				<div class="mr-4">
					<span class="text-sm font-medium text-foreground">System-wide Memory</span>
					<p class="mt-0.5 text-xs text-muted">
						Allow your conversations to improve Jatayu AI's memory and responses across sessions
					</p>
				</div>
				<div class="relative shrink-0">
					<input
						id="settings-data-training"
						type="checkbox"
						role="switch"
						checked={dataShareTraining}
						onchange={(e: Event) => handleTrainingToggle((e.target as HTMLInputElement).checked)}
						aria-checked={dataShareTraining}
						class="peer sr-only"
					/>
					<div
						class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
					></div>
					<div
						class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
					></div>
				</div>
			</label>
		</div>
	</section>

	<!-- Danger Zone -->
	<section class="border-t border-border-subtle pt-4">
		<div>
			<h3 class="text-sm font-medium text-foreground">Data Management</h3>
			<p class="text-xs text-muted">
				Permanently delete your data. These actions cannot be undone.
			</p>
		</div>

		<div class="mt-3 space-y-3">
			<!-- Delete all conversations -->
			<div
				class="flex items-center justify-between rounded-xl border border-border-subtle px-4 py-3.5"
			>
				<div>
					<p class="text-sm font-medium text-foreground">Delete All Conversations</p>
					<p class="mt-0.5 text-xs text-muted">
						Permanently remove all your conversations and messages
					</p>
				</div>
				<div class="flex shrink-0 items-center gap-2">
					{#if deleteConvState === 'confirm'}
						<button
							onclick={cancelDeleteConversations}
							class="rounded-lg px-3 py-1.5 text-xs font-medium text-subtle transition-colors hover:bg-surface-2"
						>
							Cancel
						</button>
						<button
							onclick={handleDeleteAllConversations}
							class="rounded-lg bg-red-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-600"
						>
							Confirm Delete
						</button>
					{:else if deleteConvState === 'deleting'}
						<div class="flex items-center gap-2 text-xs text-muted">
							<svg
								class="h-4 w-4 animate-spin"
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
							Deleting...
						</div>
					{:else}
						<button
							onclick={handleDeleteAllConversations}
							class="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50"
						>
							Delete All
						</button>
					{/if}
				</div>
			</div>

			<!-- Delete all addons -->
			<div
				class="flex items-center justify-between rounded-xl border border-border-subtle px-4 py-3.5"
			>
				<div>
					<p class="text-sm font-medium text-foreground">Remove All Addons</p>
					<p class="mt-0.5 text-xs text-muted">
						Unregister all connected addons and revoke their access
					</p>
				</div>
				<div class="flex shrink-0 items-center gap-2">
					{#if deleteAddonsState === 'confirm'}
						<button
							onclick={cancelDeleteAddons}
							class="rounded-lg px-3 py-1.5 text-xs font-medium text-subtle transition-colors hover:bg-surface-2"
						>
							Cancel
						</button>
						<button
							onclick={handleDeleteAllAddons}
							class="rounded-lg bg-red-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-600"
						>
							Confirm Remove
						</button>
					{:else if deleteAddonsState === 'deleting'}
						<div class="flex items-center gap-2 text-xs text-muted">
							<svg
								class="h-4 w-4 animate-spin"
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
							Removing...
						</div>
					{:else}
						<button
							onclick={handleDeleteAllAddons}
							class="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50"
						>
							Remove All
						</button>
					{/if}
				</div>
			</div>
		</div>
	</section>

	<!-- Data Export (GDPR) -->
	<section class="border-t border-border-subtle pt-4">
		<div class="space-y-4">
			<div>
				<h3 class="text-sm font-medium text-foreground">Export Your Data</h3>
				<p class="mt-1 text-xs text-muted">
					Download a copy of all your personal data (GDPR Article 20)
				</p>
			</div>

			<div>
				<button
					onclick={handleExportData}
					disabled={exportState === 'exporting'}
					class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface disabled:opacity-50"
				>
					{#if exportState === 'exporting'}
						<span class="inline-flex items-center gap-2">
							<svg
								class="h-4 w-4 animate-spin"
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
							Exporting...
						</span>
					{:else}
						Export My Data
					{/if}
				</button>
			</div>
		</div>
	</section>

	<!-- Delete Account (GDPR) -->
	<section class="border-t border-border-subtle pt-4">
		<div class="space-y-4">
			<div>
				<h3 class="text-sm font-medium text-foreground">Delete Your Account</h3>
				<p class="mt-1 text-xs text-muted">
					Permanently delete your account and all associated data. This action is irreversible.
				</p>
			</div>

			<div class="rounded-xl border border-red-200 bg-red-50 p-4">
				{#if gdprDeleteStep === 'idle'}
					<button
						onclick={startAccountDeletion}
						class="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
					>
						Delete My Account
					</button>
				{:else if gdprDeleteStep === 'warning'}
					{#if ownedOrgs.length > 0}
						<div class="space-y-3">
							<div
								class="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
							>
								<p class="font-medium">
									You own the following organizations. Transfer ownership before deleting your
									account:
								</p>
								<ul class="mt-2 list-disc pl-5">
									{#each ownedOrgs as org}
										<li>{org.name}</li>
									{/each}
								</ul>
							</div>
							<div class="flex items-center gap-2">
								<button
									onclick={cancelAccountDeletion}
									class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface"
								>
									Back
								</button>
							</div>
						</div>
					{:else}
						<div class="space-y-3">
							<div
								class="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
							>
								<p class="font-medium">
									This will permanently delete your account. Please read carefully:
								</p>
								<ul class="mt-2 list-disc pl-5 space-y-1">
									<li>All conversations, projects, and files will be permanently deleted</li>
									<li>
										All organization memberships will be removed (your messages will be anonymized
										to "[Deleted User]")
									</li>
									<li>This action cannot be undone</li>
								</ul>
							</div>
							<div class="flex items-center gap-2">
								<button
									onclick={cancelAccountDeletion}
									class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface"
								>
									Cancel
								</button>
								<button
									onclick={() => (gdprDeleteStep = 'reason')}
									class="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
								>
									Continue
								</button>
							</div>
						</div>
					{/if}
				{:else if gdprDeleteStep === 'reason'}
					<div class="space-y-3">
						<div>
							<label for="delete-reason" class="block text-sm font-medium text-foreground">
								Reason for leaving (optional)
							</label>
							<textarea
								id="delete-reason"
								bind:value={deleteReason}
								rows={3}
								placeholder="Help us improve by sharing why you're deleting your account..."
								class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground resize-y"
							></textarea>
						</div>
						<div class="flex items-center gap-2">
							<button
								onclick={() => (gdprDeleteStep = 'warning')}
								class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface"
							>
								Back
							</button>
							<button
								onclick={() => (gdprDeleteStep = 'confirm')}
								class="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
							>
								Continue
							</button>
						</div>
					</div>
				{:else if gdprDeleteStep === 'confirm'}
					<div class="space-y-3">
						<div>
							<label for="delete-confirm" class="block text-sm font-medium text-foreground">
								Type <strong>delete my account</strong> to confirm
							</label>
							<input
								id="delete-confirm"
								type="text"
								bind:value={deleteConfirmText}
								placeholder="delete my account"
								class="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground"
							/>
						</div>
						<div class="flex items-center gap-2">
							<button
								onclick={cancelAccountDeletion}
								class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface"
							>
								Cancel
							</button>
							<button
								onclick={handleDeleteAccount}
								disabled={deleteConfirmText !== 'delete my account'}
								class="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
							>
								Delete Permanently
							</button>
						</div>
					</div>
				{:else if gdprDeleteStep === 'deleting'}
					<div class="flex items-center gap-2 text-sm text-muted">
						<svg
							class="h-4 w-4 animate-spin"
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
						Deleting your account...
					</div>
				{/if}
			</div>
		</div>
	</section>
</div>
