<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Toggle } from '$components/ui';
	import { fetchCurrentUser } from '$api/auth';
	import { getEnterpriseMode, updateEnterpriseMode } from '$api/enterprise';
	import { toasts } from '$stores/toast';
	import { usageLimitModal } from '$stores/usageLimit';
	import type { EnterpriseModeStatus } from '$api/enterprise';

	let status: EnterpriseModeStatus | null = $state(null);
	let loading = $state(true);
	let toggling = $state(false);
	let loadError = $state('');
	let showPasswordPrompt = $state(false);
	let password = $state('');
	let passwordError = $state('');
	let disableError: {
		detail: string;
		organizations?: { id: string; name: string; role: string }[];
	} | null = $state(null);

	onMount(async () => {
		try {
			status = await getEnterpriseMode();
			loadError = '';
		} catch {
			loadError = 'Unable to load enterprise mode status right now.';
		} finally {
			loading = false;
		}
	});

	function promptToggle(): void {
		if (!status) return;
		password = '';
		passwordError = '';
		disableError = null;
		showPasswordPrompt = true;
	}

	function promptUpgrade(): void {
		usageLimitModal.show({
			limitType: 'enterprise_mode',
			message: 'Enterprise mode requires a paid subscription.'
		});
	}

	function handleToggleAttempt(): void {
		if (!status) return;

		const nextEnabled = !status.enabled;

		if (nextEnabled && !status.available) {
			promptUpgrade();
			return;
		}

		promptToggle();
	}

	async function confirmToggle(): Promise<void> {
		if (!status || !password) {
			passwordError = 'Please enter your password.';
			return;
		}
		toggling = true;
		passwordError = '';
		disableError = null;

		const newEnabled = !status.enabled;

		try {
			status = await updateEnterpriseMode(newEnabled, password);
			showPasswordPrompt = false;
			password = '';
			// Refresh user to update enterprise_mode in store
			await fetchCurrentUser();
			toasts.success(newEnabled ? 'Enterprise mode enabled.' : 'Enterprise mode disabled.');
			if (newEnabled) {
				// Navigate to onboarding if first time
				goto(resolve('/onboarding/enterprise/'));
			}
		} catch (err: unknown) {
			const error = err as { status?: number; body?: unknown; message?: string };
			if (error.status === 402) {
				showPasswordPrompt = false;
				promptUpgrade();
			} else if (error.status === 403) {
				passwordError = 'Incorrect password. Please try again.';
			} else if (error.status === 409) {
				showPasswordPrompt = false;
				disableError = error.body as typeof disableError;
			} else {
				showPasswordPrompt = false;
				toasts.error(error.message || 'Failed to update enterprise mode.');
			}
		} finally {
			toggling = false;
		}
	}
</script>

<div class="space-y-6">
	<div>
		<h3 class="text-lg font-medium text-foreground">Enterprise Features</h3>
		<p class="mt-1 text-sm text-muted">
			Enable enterprise mode to unlock organizations, team management, SSO, SCIM provisioning, and
			advanced security controls.
		</p>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-8">
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
		<div class="rounded-xl border border-border-subtle p-4">
			<div class="flex items-center justify-between">
				<div>
					<p class="text-sm font-medium text-foreground">Enterprise Mode</p>
					<p class="mt-0.5 text-xs text-muted">
						{#if loadError}
							{loadError}
						{:else if status?.enabled}
							Enterprise features are active
						{:else if status && !status.available}
							Requires a paid plan. Toggle on to view upgrade options.
						{:else}
							Enable to access team and org features
						{/if}
					</p>
				</div>
				<Toggle
					id="enterprise-mode-toggle"
					aria-label="Enterprise Mode"
					checked={status?.enabled ?? false}
					disabled={toggling || !status}
					onchange={handleToggleAttempt}
				/>
			</div>

			{#if toggling}
				<div class="mt-3 flex items-center gap-2 text-xs text-muted">
					<svg
						class="h-4 w-4 animate-spin text-muted"
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
					<span>Updating enterprise mode…</span>
				</div>
			{/if}

			{#if showPasswordPrompt}
				<div class="mt-3 rounded-lg border border-border-subtle bg-surface p-4">
					<p class="text-sm font-medium text-foreground">Confirm your password</p>
					<p class="mt-1 text-xs text-muted">
						Enter your current password to {status?.enabled ? 'disable' : 'enable'} enterprise mode.
					</p>
					<div class="mt-3 flex items-end gap-2">
						<div class="flex-1">
							<input
								type="password"
								bind:value={password}
								placeholder="Current password"
								onkeydown={(e: KeyboardEvent) => e.key === 'Enter' && confirmToggle()}
								class="w-full rounded-lg border border-border bg-white px-3 py-2 text-sm text-foreground placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
							/>
							{#if passwordError}
								<p class="mt-1 text-xs text-red-600">{passwordError}</p>
							{/if}
						</div>
						<button
							onclick={confirmToggle}
							disabled={toggling}
							class="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
						>
							{toggling ? 'Confirming…' : 'Confirm'}
						</button>
						<button
							onclick={() => {
								showPasswordPrompt = false;
								password = '';
							}}
							disabled={toggling}
							class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface-2 disabled:opacity-50"
						>
							Cancel
						</button>
					</div>
				</div>
			{/if}

			{#if disableError}
				<div class="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
					<p class="font-medium">{disableError.detail}</p>
					{#if disableError.organizations?.length}
						<p class="mt-1 text-xs">You must leave these organizations first:</p>
						<ul class="mt-1 list-inside list-disc text-xs">
							{#each disableError.organizations as org (org.id)}
								<li>{org.name} ({org.role})</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/if}
		</div>

		{#if status?.enabled}
			<div class="space-y-2">
				<h4 class="text-sm font-medium text-foreground">Quick Links</h4>
				<div class="grid gap-2 sm:grid-cols-2">
					<a
						href={resolve('/settings/compliance/')}
						class="rounded-lg border border-border-subtle p-3 text-sm text-foreground transition-colors duration-150 hover:bg-surface"
					>
						<span class="font-medium">Compliance Dashboard</span>
						<span class="mt-0.5 block text-xs text-muted"
							>Audit logs, retention, consent, exports</span
						>
					</a>
					<a
						href={resolve('/claw')}
						class="rounded-lg border border-border-subtle p-3 text-sm text-foreground transition-colors duration-150 hover:bg-surface"
					>
						<span class="font-medium">Claw Mode</span>
						<span class="mt-0.5 block text-xs text-muted">Persistent sandbox, Telegram, Slack</span>
					</a>
				</div>
			</div>
		{/if}
	{/if}
</div>
