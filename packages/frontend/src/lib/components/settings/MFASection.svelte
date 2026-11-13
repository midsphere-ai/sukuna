<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getMFAState,
		beginTOTPEnrollment,
		confirmTOTPEnrollment,
		generateRecoveryCodes,
		regenerateRecoveryCodes,
		removeAuthenticator,
		type MFAState,
		type TOTPBegin,
		type Authenticator
	} from '$lib/api/mfa';

	let mfaState: MFAState | null = $state(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// TOTP enrollment wizard
	let totpStep: 'idle' | 'show-secret' | 'verify' = $state('idle');
	let totpSetup: TOTPBegin | null = $state(null);
	let totpCode = $state('');
	let totpError = $state<string | null>(null);
	let totpBusy = $state(false);

	// Recovery codes modal
	let recoveryCodes: string[] | null = $state(null);
	let recoveryBusy = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			mfaState = await getMFAState();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function startTotp() {
		totpError = null;
		totpBusy = true;
		try {
			totpSetup = await beginTOTPEnrollment();
			totpStep = 'show-secret';
		} catch (e) {
			totpError = e instanceof Error ? e.message : String(e);
		} finally {
			totpBusy = false;
		}
	}

	async function confirmTotp() {
		if (!totpSetup || !totpCode) return;
		totpError = null;
		totpBusy = true;
		try {
			await confirmTOTPEnrollment(totpSetup.secret, totpCode.trim());
			totpStep = 'idle';
			totpSetup = null;
			totpCode = '';
			await load();
		} catch (e) {
			totpError = e instanceof Error ? e.message : 'Invalid code';
		} finally {
			totpBusy = false;
		}
	}

	function cancelTotp() {
		totpStep = 'idle';
		totpSetup = null;
		totpCode = '';
		totpError = null;
	}

	async function generateCodes() {
		recoveryBusy = true;
		try {
			const result = await generateRecoveryCodes();
			recoveryCodes = result.codes;
			await load();
		} finally {
			recoveryBusy = false;
		}
	}

	async function regenerateCodes() {
		if (!confirm('Regenerating will invalidate all existing recovery codes. Continue?')) return;
		recoveryBusy = true;
		try {
			const result = await regenerateRecoveryCodes();
			recoveryCodes = result.codes;
			await load();
		} finally {
			recoveryBusy = false;
		}
	}

	async function remove(a: Authenticator) {
		const label = a.type === 'totp' ? 'authenticator app' : a.type;
		if (!confirm(`Remove ${label}? You may lose access if this is your only MFA method.`)) return;
		await removeAuthenticator(a.id);
		await load();
	}

	function copyToClipboard(text: string) {
		navigator.clipboard?.writeText(text);
	}

	function formatDate(iso: string | null) {
		if (!iso) return '—';
		return new Date(iso).toLocaleString();
	}
</script>

<div class="space-y-6">
	<div>
		<h2 class="text-lg font-medium text-foreground">Two-factor authentication</h2>
		<p class="mt-1 text-sm text-muted">
			Add an extra layer of security by requiring a code from an authenticator app or a recovery
			code in addition to your password.
		</p>
	</div>

	{#if loading}
		<div class="text-sm text-muted">Loading…</div>
	{:else if error}
		<div class="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700">
			{error}
		</div>
	{:else if mfaState}
		<!-- Authenticator app section -->
		<section class="rounded-xl border border-divider p-5">
			<div class="flex items-start justify-between gap-4">
				<div>
					<h3 class="text-sm font-medium text-foreground">Authenticator app</h3>
					<p class="mt-1 text-xs text-muted">
						Use Google Authenticator, 1Password, Authy, or any TOTP-compatible app.
					</p>
				</div>
				<span
					class="rounded-full px-2.5 py-0.5 text-xs font-medium {mfaState.has_totp
						? 'bg-emerald-100 text-emerald-700'
						: 'bg-surface text-muted'}"
				>
					{mfaState.has_totp ? 'Active' : 'Not enrolled'}
				</span>
			</div>

			{#if mfaState.has_totp}
				<div class="mt-4 space-y-2">
					{#each mfaState.authenticators.filter((a) => a.type === 'totp') as a}
						<div class="flex items-center justify-between rounded-lg bg-surface px-3 py-2 text-sm">
							<div>
								<div class="font-medium text-foreground">Authenticator app</div>
								<div class="text-xs text-muted">
									Added {formatDate(a.created_at)} · Last used {formatDate(a.last_used_at)}
								</div>
							</div>
							<button
								type="button"
								onclick={() => remove(a)}
								class="rounded-md border border-divider px-2.5 py-1 text-xs text-muted hover:border-red-300 hover:text-red-600"
							>
								Remove
							</button>
						</div>
					{/each}
				</div>
			{:else if totpStep === 'idle'}
				<button
					type="button"
					disabled={totpBusy}
					onclick={startTotp}
					class="mt-4 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-light hover:bg-foreground/90 disabled:opacity-50"
				>
					{totpBusy ? 'Starting…' : 'Set up authenticator app'}
				</button>
			{:else if totpStep === 'show-secret' && totpSetup}
				<div class="mt-4 space-y-3 rounded-lg border border-divider p-4">
					<p class="text-sm text-foreground">
						Scan this QR code with your authenticator app, or enter the secret manually.
					</p>
					<div class="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
						<img
							src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(totpSetup.otpauth_uri)}`}
							alt="TOTP QR code"
							class="rounded border border-divider"
							width="180"
							height="180"
						/>
						<div class="text-xs">
							<div class="text-muted">Account</div>
							<div class="mb-2 font-medium text-foreground">{totpSetup.label}</div>
							<div class="text-muted">Secret</div>
							<div class="flex items-center gap-2">
								<code class="break-all rounded bg-surface px-1.5 py-0.5 font-mono"
									>{totpSetup.secret}</code
								>
								<button
									type="button"
									class="text-xs text-blue-600 hover:underline"
									onclick={() => copyToClipboard(totpSetup!.secret)}>Copy</button
								>
							</div>
						</div>
					</div>
					<button
						type="button"
						class="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-light hover:bg-foreground/90"
						onclick={() => (totpStep = 'verify')}
					>
						I have scanned the code
					</button>
					<button
						type="button"
						class="ml-2 rounded-lg border border-divider px-4 py-2 text-sm text-muted"
						onclick={cancelTotp}
					>
						Cancel
					</button>
				</div>
			{:else if totpStep === 'verify' && totpSetup}
				<div class="mt-4 space-y-3 rounded-lg border border-divider p-4">
					<p class="text-sm text-foreground">
						Enter the 6-digit code from your authenticator app to confirm.
					</p>
					<input
						type="text"
						inputmode="numeric"
						pattern="[0-9]*"
						maxlength="6"
						bind:value={totpCode}
						placeholder="123456"
						class="w-32 rounded-lg border border-divider px-3 py-2 text-center font-mono text-lg tracking-widest"
					/>
					{#if totpError}
						<div class="text-sm text-red-600">{totpError}</div>
					{/if}
					<div>
						<button
							type="button"
							disabled={totpBusy || totpCode.length < 6}
							onclick={confirmTotp}
							class="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-light hover:bg-foreground/90 disabled:opacity-50"
						>
							{totpBusy ? 'Verifying…' : 'Verify and enable'}
						</button>
						<button
							type="button"
							class="ml-2 rounded-lg border border-divider px-4 py-2 text-sm text-muted"
							onclick={cancelTotp}
						>
							Cancel
						</button>
					</div>
				</div>
			{/if}

			{#if totpError && totpStep === 'idle'}
				<div class="mt-3 text-sm text-red-600">{totpError}</div>
			{/if}
		</section>

		<!-- Recovery codes section -->
		<section class="rounded-xl border border-divider p-5">
			<div class="flex items-start justify-between gap-4">
				<div>
					<h3 class="text-sm font-medium text-foreground">Recovery codes</h3>
					<p class="mt-1 text-xs text-muted">
						One-time backup codes for when you don't have your authenticator app.
					</p>
				</div>
				<span
					class="rounded-full px-2.5 py-0.5 text-xs font-medium {mfaState.has_recovery_codes
						? 'bg-emerald-100 text-emerald-700'
						: 'bg-surface text-muted'}"
				>
					{mfaState.has_recovery_codes ? 'Generated' : 'Not generated'}
				</span>
			</div>

			<div class="mt-4 flex gap-2">
				{#if !mfaState.has_recovery_codes}
					<button
						type="button"
						disabled={recoveryBusy}
						onclick={generateCodes}
						class="rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-light hover:bg-foreground/90 disabled:opacity-50"
					>
						{recoveryBusy ? 'Generating…' : 'Generate recovery codes'}
					</button>
				{:else}
					<button
						type="button"
						disabled={recoveryBusy}
						onclick={regenerateCodes}
						class="rounded-lg border border-divider px-4 py-2 text-sm font-medium text-foreground hover:bg-surface disabled:opacity-50"
					>
						Regenerate
					</button>
				{/if}
			</div>

			{#if recoveryCodes}
				<div class="mt-4 space-y-2 rounded-lg border border-yellow-300 bg-yellow-50 p-4">
					<div class="flex items-start justify-between">
						<p class="text-sm font-medium text-yellow-900">
							Save these codes somewhere safe — they will not be shown again.
						</p>
						<button
							type="button"
							class="text-xs text-blue-700 hover:underline"
							onclick={() => copyToClipboard(recoveryCodes!.join('\n'))}>Copy all</button
						>
					</div>
					<ul class="grid grid-cols-2 gap-1 font-mono text-sm text-yellow-900">
						{#each recoveryCodes as c}
							<li>{c}</li>
						{/each}
					</ul>
					<button
						type="button"
						class="mt-2 text-xs text-yellow-900 underline"
						onclick={() => (recoveryCodes = null)}>I have saved them</button
					>
				</div>
			{/if}
		</section>
	{/if}
</div>
