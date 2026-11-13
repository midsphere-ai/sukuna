<script lang="ts">
	import { currentUser } from '$stores/auth';
	import { toasts } from '$stores/toast';
	import {
		updateUser,
		changePassword,
		deleteAccount,
		requestPasswordOTP,
		verifyPasswordOTP
	} from '$api/auth';
	import { closeSettings } from '$stores/settings';
	import { goto } from '$app/navigation';
	import type { User } from '$api/types';

	let user: User | null = $state(null);
	currentUser.subscribe((u) => (user = u));

	// Account info fields
	let fullName = $state('');
	let email = $state('');
	let accountSaving = $state(false);

	// Password change fields
	let currentPassword = $state('');
	let newPassword = $state('');
	let confirmPassword = $state('');
	let passwordSaving = $state(false);

	// OTP reset fields
	let otpMode = $state(false);
	let otpSent = $state(false);
	let otpCode = $state('');
	let otpNewPassword = $state('');
	let otpSending = $state(false);
	let otpVerifying = $state(false);

	// Delete account state
	let deleteStep: 'idle' | 'confirm' | 'final' = $state('idle');
	let deleteConfirmText = $state('');
	let deleting = $state(false);

	// Sync user data
	$effect(() => {
		if (user) {
			fullName = user.name || '';
			email = user.email || '';
		}
	});

	async function saveAccountInfo(): Promise<void> {
		if (!user) return;
		accountSaving = true;
		try {
			await updateUser(user.id, {
				user_name: fullName,
				user_email: email
			});
			toasts.success('Account updated successfully.');
		} catch {
			// Error handled by API client
		} finally {
			accountSaving = false;
		}
	}

	async function handleChangePassword(): Promise<void> {
		if (!newPassword.trim()) {
			toasts.error('New password is required.');
			return;
		}
		if (newPassword !== confirmPassword) {
			toasts.error('Passwords do not match.');
			return;
		}
		if (newPassword.length < 8) {
			toasts.error('Password must be at least 8 characters.');
			return;
		}
		passwordSaving = true;
		try {
			await changePassword({
				old_password: currentPassword,
				new_password1: newPassword,
				new_password2: confirmPassword
			});
			currentPassword = '';
			newPassword = '';
			confirmPassword = '';
		} catch {
			// Error handled by API client
		} finally {
			passwordSaving = false;
		}
	}

	async function handleRequestOTP(): Promise<void> {
		if (!email.trim()) {
			toasts.error('Email is required.');
			return;
		}
		otpSending = true;
		try {
			const result = await requestPasswordOTP(email);
			if (result.success) {
				otpSent = true;
				toasts.success('OTP sent to your email.');
			} else {
				toasts.error(result.message || 'Failed to send OTP.');
			}
		} catch {
			// Error handled by API client
		} finally {
			otpSending = false;
		}
	}

	async function handleVerifyOTP(): Promise<void> {
		if (!otpCode.trim()) {
			toasts.error('OTP code is required.');
			return;
		}
		if (!otpNewPassword.trim() || otpNewPassword.length < 8) {
			toasts.error('New password must be at least 8 characters.');
			return;
		}
		otpVerifying = true;
		try {
			const result = await verifyPasswordOTP({
				email,
				otp: otpCode,
				new_password: otpNewPassword
			});
			if (result.success) {
				toasts.success('Password reset successfully.');
				otpMode = false;
				otpSent = false;
				otpCode = '';
				otpNewPassword = '';
			} else {
				toasts.error(result.message || 'Invalid OTP.');
			}
		} catch {
			// Error handled by API client
		} finally {
			otpVerifying = false;
		}
	}

	function cancelOTP(): void {
		otpMode = false;
		otpSent = false;
		otpCode = '';
		otpNewPassword = '';
	}

	async function handleDeleteAccount(): Promise<void> {
		if (!user) return;
		deleting = true;
		try {
			closeSettings();
			await deleteAccount(user.id);
			toasts.success('Account deleted.');
		} catch {
			// Error handled by API client
		} finally {
			deleting = false;
			deleteStep = 'idle';
			deleteConfirmText = '';
		}
	}

	function cancelDelete(): void {
		deleteStep = 'idle';
		deleteConfirmText = '';
	}

	function navigateTo(path: string): void {
		closeSettings();
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto(path);
	}
</script>

<div class="space-y-5">
	<!-- Account Information -->
	<section>
		<div>
			<h3 class="text-sm font-medium text-foreground">Account</h3>
			<p class="text-xs text-muted">Manage your account details.</p>
		</div>

		<div class="mt-3 space-y-4">
			<div class="flex flex-col gap-1.5">
				<label for="account-name" class="text-sm font-medium text-foreground">Full Name</label>
				<input
					id="account-name"
					type="text"
					bind:value={fullName}
					placeholder="Your full name"
					class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				/>
			</div>

			<div class="flex flex-col gap-1.5">
				<label for="account-email" class="text-sm font-medium text-foreground">Email</label>
				<input
					id="account-email"
					type="email"
					bind:value={email}
					placeholder="your@email.com"
					class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				/>
			</div>

			<button
				onclick={saveAccountInfo}
				disabled={accountSaving}
				class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
			>
				{accountSaving ? 'Saving...' : 'Save Changes'}
			</button>
		</div>
	</section>

	<!-- Security — Password Change -->
	<section class="border-t border-border-subtle pt-4">
		<div>
			<h3 class="text-sm font-medium text-foreground">Security</h3>
			<p class="text-xs text-muted">Change your password or reset it via OTP.</p>
		</div>

		{#if otpMode}
			<!-- OTP Reset Flow -->
			<div class="mt-3 space-y-4">
				{#if !otpSent}
					<p class="text-xs text-subtle">
						We'll send a one-time code to <span class="font-medium text-foreground">{email}</span>.
					</p>
					<div class="flex gap-2">
						<button
							onclick={handleRequestOTP}
							disabled={otpSending}
							class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
						>
							{otpSending ? 'Sending...' : 'Send OTP'}
						</button>
						<button
							onclick={cancelOTP}
							class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
						>
							Cancel
						</button>
					</div>
				{:else}
					<div class="flex flex-col gap-1.5">
						<label for="account-otp" class="text-sm font-medium text-foreground">OTP Code</label>
						<input
							id="account-otp"
							type="text"
							bind:value={otpCode}
							placeholder="Enter the code sent to your email"
							class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
						/>
					</div>

					<div class="flex flex-col gap-1.5">
						<label for="account-otp-password" class="text-sm font-medium text-foreground"
							>New Password</label
						>
						<input
							id="account-otp-password"
							type="password"
							bind:value={otpNewPassword}
							placeholder="Enter your new password"
							class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
						/>
					</div>

					<div class="flex gap-2">
						<button
							onclick={handleVerifyOTP}
							disabled={otpVerifying}
							class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
						>
							{otpVerifying ? 'Verifying...' : 'Reset Password'}
						</button>
						<button
							onclick={cancelOTP}
							class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
						>
							Cancel
						</button>
					</div>
				{/if}
			</div>
		{:else}
			<!-- Regular Password Change -->
			<div class="mt-3 space-y-4">
				<div class="flex flex-col gap-1.5">
					<label for="account-current-password" class="text-sm font-medium text-foreground"
						>Current Password</label
					>
					<input
						id="account-current-password"
						type="password"
						bind:value={currentPassword}
						placeholder="Enter current password"
						class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
					/>
				</div>

				<div class="flex flex-col gap-1.5">
					<label for="account-new-password" class="text-sm font-medium text-foreground"
						>New Password</label
					>
					<input
						id="account-new-password"
						type="password"
						bind:value={newPassword}
						placeholder="Enter new password"
						class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
					/>
				</div>

				<div class="flex flex-col gap-1.5">
					<label for="account-confirm-password" class="text-sm font-medium text-foreground"
						>Confirm New Password</label
					>
					<input
						id="account-confirm-password"
						type="password"
						bind:value={confirmPassword}
						placeholder="Confirm new password"
						class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
					/>
				</div>

				<div class="flex items-center gap-3">
					<button
						onclick={handleChangePassword}
						disabled={passwordSaving}
						class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
					>
						{passwordSaving ? 'Changing...' : 'Change Password'}
					</button>
					<button
						onclick={() => (otpMode = true)}
						class="text-xs font-medium text-subtle transition-colors hover:text-foreground"
					>
						Forgot password? Reset via OTP
					</button>
				</div>
			</div>
		{/if}
	</section>

	<!-- Quick Actions -->
	<section class="border-t border-border-subtle pt-4">
		<div>
			<h3 class="text-sm font-medium text-foreground">Quick Actions</h3>
			<p class="text-xs text-muted">Navigate to related sections.</p>
		</div>

		<div class="mt-3 flex flex-wrap gap-3">
			<button
				onclick={() => navigateTo('/billing')}
				class="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground transition-all duration-200 hover:border-border-strong hover:bg-surface-2"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="shrink-0"
				>
					<rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
					<line x1="1" y1="10" x2="23" y2="10" />
				</svg>
				Billing & Usage
			</button>
			<button
				onclick={() => navigateTo('/support')}
				class="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground transition-all duration-200 hover:border-border-strong hover:bg-surface-2"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="shrink-0"
				>
					<circle cx="12" cy="12" r="10" />
					<path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
					<line x1="12" y1="17" x2="12.01" y2="17" />
				</svg>
				Customer Support
			</button>
		</div>
	</section>

	<!-- Danger Zone — Delete Account -->
	<section class="border-t border-border-subtle pt-4">
		<div>
			<h3 class="text-sm font-medium text-red-600 dark:text-red-400">Danger Zone</h3>
			<p class="text-xs text-muted">
				Permanently delete your account and all associated data. This action cannot be undone.
			</p>
		</div>

		<div class="mt-3">
			{#if deleteStep === 'idle'}
				<button
					onclick={() => (deleteStep = 'confirm')}
					class="rounded-lg border border-red-200 px-4 py-2 text-xs font-medium text-red-600 transition-all duration-200 hover:border-red-300 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:border-red-700 dark:hover:bg-red-900/20"
				>
					Delete Account
				</button>
			{:else if deleteStep === 'confirm'}
				<div
					class="rounded-xl border border-red-200 bg-red-50/50 p-4 dark:border-red-800/50 dark:bg-red-900/10"
				>
					<p class="text-sm font-medium text-red-700 dark:text-red-400">
						Are you sure you want to delete your account?
					</p>
					<p class="mt-1 text-xs text-red-600/70 dark:text-red-400/70">
						All your conversations, files, settings, and data will be permanently removed.
					</p>
					<div class="mt-3 flex gap-2">
						<button
							onclick={() => (deleteStep = 'final')}
							class="rounded-lg bg-red-600 px-4 py-2 text-xs font-medium text-white transition-all duration-200 hover:bg-red-700"
						>
							Yes, I want to delete
						</button>
						<button
							onclick={cancelDelete}
							class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
						>
							Cancel
						</button>
					</div>
				</div>
			{:else if deleteStep === 'final'}
				<div
					class="rounded-xl border border-red-300 bg-red-50/80 p-4 dark:border-red-700 dark:bg-red-900/20"
				>
					<p class="text-sm font-medium text-red-700 dark:text-red-400">Final confirmation</p>
					<p class="mt-1 text-xs text-red-600/70 dark:text-red-400/70">
						Type <span class="font-mono font-medium">delete my account</span> to confirm.
					</p>
					<div class="mt-3 flex flex-col gap-3">
						<input
							type="text"
							bind:value={deleteConfirmText}
							placeholder="delete my account"
							class="w-full rounded-xl border border-red-200 bg-white px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-red-400 focus:ring-1 focus:ring-red-200 dark:border-red-800 dark:bg-foreground/20 dark:focus:border-red-600 dark:focus:ring-red-800"
						/>
						<div class="flex gap-2">
							<button
								onclick={handleDeleteAccount}
								disabled={deleteConfirmText !== 'delete my account' || deleting}
								class="rounded-lg bg-red-600 px-4 py-2 text-xs font-medium text-white transition-all duration-200 hover:bg-red-700 disabled:opacity-50 disabled:hover:bg-red-600"
							>
								{deleting ? 'Deleting...' : 'Permanently Delete Account'}
							</button>
							<button
								onclick={cancelDelete}
								class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
							>
								Cancel
							</button>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</section>
</div>
