<script lang="ts">
	import { onMount } from 'svelte';
	import { toasts } from '$stores/toast';
	import {
		getSecurityPolicy,
		updateSecurityPolicy,
		type Organization,
		type SecurityPolicy
	} from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	let policy: SecurityPolicy | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);

	// Form fields
	let mfaRequired = $state(false);
	let sessionTimeout = $state('');
	let maxSessions = $state('');

	async function load() {
		loading = true;
		try {
			policy = await getSecurityPolicy(orgId);
			mfaRequired = policy.mfa_required;
			sessionTimeout =
				policy.session_timeout_minutes != null ? String(policy.session_timeout_minutes) : '';
			maxSessions =
				policy.max_concurrent_sessions != null ? String(policy.max_concurrent_sessions) : '';
		} catch {
			policy = null;
			mfaRequired = false;
			sessionTimeout = '';
			maxSessions = '';
		} finally {
			loading = false;
		}
	}

	async function handleSave() {
		saving = true;
		try {
			const data: Partial<SecurityPolicy> = {
				mfa_required: mfaRequired,
				session_timeout_minutes: sessionTimeout.trim() ? parseInt(sessionTimeout) : null,
				max_concurrent_sessions: maxSessions.trim() ? parseInt(maxSessions) : null
			};
			policy = await updateSecurityPolicy(orgId, data);
			toasts.success('Security policy updated.');
		} catch {
			toasts.error('Failed to update security policy.');
		} finally {
			saving = false;
		}
	}

	onMount(load);
</script>

<div class="space-y-4">
	<div>
		<h3 class="text-sm font-medium text-foreground">Security Policy</h3>
		<p class="text-xs text-muted">
			Configure authentication and session security requirements for your organization.
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
		<div class="rounded-xl border border-border-subtle bg-surface p-4">
			<div class="space-y-4">
				<!-- MFA toggle -->
				<div class="flex items-center justify-between">
					<div>
						<p class="text-xs font-medium text-foreground">Require MFA</p>
						<p class="text-[10px] text-muted">
							All members must have multi-factor authentication enabled.
						</p>
					</div>
					{#if org.your_role === 'admin' || org.your_role === 'owner'}
						<label class="relative inline-flex cursor-pointer items-center">
							<input type="checkbox" class="peer sr-only" bind:checked={mfaRequired} />
							<div
								class="h-6 w-11 rounded-full bg-border-strong peer-checked:bg-accent peer-focus:outline-none after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-5"
							></div>
						</label>
					{:else}
						<span class="text-xs text-muted">{mfaRequired ? 'Enabled' : 'Disabled'}</span>
					{/if}
				</div>

				<!-- Session timeout -->
				<div>
					<label for="sp-timeout" class="mb-1 block text-xs font-medium text-muted"
						>Session Timeout (minutes)</label
					>
					<input
						id="sp-timeout"
						type="number"
						bind:value={sessionTimeout}
						placeholder="No timeout"
						min="1"
						disabled={org.your_role !== 'admin' && org.your_role !== 'owner'}
						class="w-full max-w-xs rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none disabled:opacity-50"
					/>
					<p class="mt-1 text-[10px] text-muted">
						Leave blank for no timeout. Recommended: 480 (8 hours).
					</p>
				</div>

				<!-- Max concurrent sessions -->
				<div>
					<label for="sp-max-sessions" class="mb-1 block text-xs font-medium text-muted"
						>Max Concurrent Sessions</label
					>
					<input
						id="sp-max-sessions"
						type="number"
						bind:value={maxSessions}
						placeholder="Unlimited"
						min="1"
						disabled={org.your_role !== 'admin' && org.your_role !== 'owner'}
						class="w-full max-w-xs rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none disabled:opacity-50"
					/>
					<p class="mt-1 text-[10px] text-muted">Leave blank for unlimited.</p>
				</div>

				{#if org.your_role === 'admin' || org.your_role === 'owner'}
					<button
						onclick={handleSave}
						disabled={saving}
						class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
					>
						{saving ? 'Saving...' : 'Save'}
					</button>
				{/if}
			</div>
		</div>
	{/if}
</div>
