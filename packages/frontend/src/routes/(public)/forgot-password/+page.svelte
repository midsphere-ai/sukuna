<script lang="ts">
	import { goto } from '$app/navigation';
	import Input from '$components/ui/Input.svelte';
	import Button from '$components/ui/Button.svelte';
	import LoadingSpinner from '$components/ui/LoadingSpinner.svelte';
	import { requestPasswordOTP, verifyPasswordOTPOnly, verifyPasswordOTP } from '$api/auth';
	import { toasts } from '$stores/toast';
	import type { ApiError } from '$api/types';

	type Step = 'email' | 'otp' | 'password';

	let step = $state<Step>('email');
	let email = $state('');
	let otpDigits = $state<string[]>(['', '', '', '', '', '']);
	let newPassword = $state('');
	let confirmPassword = $state('');
	let loading = $state(false);
	let errors = $state<{
		email?: string;
		otp?: string;
		password?: string;
		confirmPassword?: string;
		form?: string;
	}>({});
	let resendCooldown = $state(0);
	let cooldownInterval: ReturnType<typeof setInterval> | null = null;
	let otpInputRefs: (HTMLInputElement | null)[] = $state([null, null, null, null, null, null]);
	let formShake = $state(false);

	let otpCode = $derived(otpDigits.join(''));

	// Password strength: 0 = empty, 1 = weak, 2 = fair, 3 = strong
	let passwordStrength = $derived.by(() => {
		if (!newPassword) return 0;
		let score = 1;
		if (newPassword.length >= 8) score++;
		if (/[A-Z]/.test(newPassword) && /[a-z]/.test(newPassword) && /[0-9]/.test(newPassword))
			score++;
		if (/[^A-Za-z0-9]/.test(newPassword) && newPassword.length >= 12) score++;
		return Math.min(score, 3);
	});

	let strengthLabel = $derived(
		passwordStrength === 0
			? ''
			: passwordStrength === 1
				? 'Weak'
				: passwordStrength === 2
					? 'Fair'
					: 'Strong'
	);

	let strengthBarColor = $derived(
		passwordStrength === 1
			? 'bg-accent/60'
			: passwordStrength === 2
				? 'bg-amber-500/70'
				: passwordStrength === 3
					? 'bg-green/70'
					: 'bg-surface-2'
	);

	let strengthTextColor = $derived(
		passwordStrength === 1
			? 'text-accent/70'
			: passwordStrength === 2
				? 'text-amber-600/70'
				: passwordStrength === 3
					? 'text-green/70'
					: 'text-muted'
	);

	function startResendCooldown() {
		resendCooldown = 60;
		if (cooldownInterval) clearInterval(cooldownInterval);
		cooldownInterval = setInterval(() => {
			resendCooldown--;
			if (resendCooldown <= 0) {
				if (cooldownInterval) clearInterval(cooldownInterval);
				cooldownInterval = null;
			}
		}, 1000);
	}

	function validateEmail(): boolean {
		const newErrors: typeof errors = {};
		if (!email.trim()) {
			newErrors.email = 'Email is required';
		} else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
			newErrors.email = 'Please enter a valid email address';
		}
		errors = newErrors;
		return Object.keys(newErrors).length === 0;
	}

	function validatePassword(): boolean {
		const newErrors: typeof errors = {};
		if (!newPassword) {
			newErrors.password = 'Password is required';
		} else if (newPassword.length < 8) {
			newErrors.password = 'Password must be at least 8 characters';
		}
		if (!confirmPassword) {
			newErrors.confirmPassword = 'Please confirm your password';
		} else if (newPassword !== confirmPassword) {
			newErrors.confirmPassword = 'Passwords do not match';
		}
		errors = newErrors;
		return Object.keys(newErrors).length === 0;
	}

	function triggerShake() {
		formShake = false;
		requestAnimationFrame(() => {
			formShake = true;
		});
	}

	async function handleEmailSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (!validateEmail()) {
			triggerShake();
			return;
		}

		loading = true;
		errors = {};

		try {
			const result = await requestPasswordOTP(email.trim());
			if (result.success === false) {
				errors = { form: result.message || 'Unable to send verification code. Please try again.' };
				triggerShake();
				return;
			}
			otpDigits = ['', '', '', '', '', ''];
			step = 'otp';
			startResendCooldown();
			// Focus first OTP input after step transition
			setTimeout(() => otpInputRefs[0]?.focus(), 50);
		} catch (err) {
			const apiErr = err as ApiError;
			if (apiErr.status === 404 || apiErr.status === 400) {
				errors = { form: 'No account found with this email address.' };
			} else if (apiErr.status === 429) {
				errors = { form: 'Too many attempts. Please try again later.' };
			} else {
				errors = { form: 'Something went wrong. Please try again later.' };
			}
			triggerShake();
		} finally {
			loading = false;
		}
	}

	function handleOtpInput(index: number, e: Event) {
		const input = e.target as HTMLInputElement;
		const value = input.value;

		// Handle paste of full OTP code
		if (value.length > 1) {
			const digits = value.replace(/\D/g, '').slice(0, 6);
			const newDigits = [...otpDigits];
			for (let i = 0; i < digits.length && i + index < 6; i++) {
				newDigits[i + index] = digits[i];
			}
			otpDigits = newDigits;
			const nextIndex = Math.min(index + digits.length, 5);
			otpInputRefs[nextIndex]?.focus();
			return;
		}

		// Single digit input
		const digit = value.replace(/\D/g, '').slice(-1);
		const newDigits = [...otpDigits];
		newDigits[index] = digit;
		otpDigits = newDigits;

		if (digit && index < 5) {
			otpInputRefs[index + 1]?.focus();
		}
	}

	function handleOtpKeydown(index: number, e: KeyboardEvent) {
		if (e.key === 'Backspace' && !otpDigits[index] && index > 0) {
			const newDigits = [...otpDigits];
			newDigits[index - 1] = '';
			otpDigits = newDigits;
			otpInputRefs[index - 1]?.focus();
		}
	}

	async function handleOtpSubmit(e: SubmitEvent) {
		e.preventDefault();
		errors = {};

		if (otpCode.length !== 6) {
			errors = { otp: 'Please enter the complete 6-digit code' };
			triggerShake();
			return;
		}

		loading = true;

		try {
			const result = await verifyPasswordOTPOnly({
				email: email.trim(),
				otp: otpCode
			});
			if (!result.success) {
				errors = { otp: result.message || 'Invalid verification code.' };
				triggerShake();
				return;
			}
			step = 'password';
			// Focus the new password field after step transition
			setTimeout(() => {
				const pwInput = document.querySelector<HTMLInputElement>(
					'input[autocomplete="new-password"]'
				);
				pwInput?.focus();
			}, 50);
		} catch (err) {
			const apiErr = err as ApiError;
			if (apiErr.status === 400) {
				const message = apiErr.message?.toLowerCase() ?? '';
				if (message.includes('expired')) {
					errors = { form: 'OTP has expired. Please request a new code.' };
				} else {
					errors = { otp: 'Invalid verification code. Please try again.' };
				}
			} else if (apiErr.status === 429) {
				errors = { form: 'Too many attempts. Please try again later.' };
			} else {
				errors = { form: 'Something went wrong. Please try again.' };
			}
			triggerShake();
		} finally {
			loading = false;
		}
	}

	async function handlePasswordSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (!validatePassword()) {
			triggerShake();
			return;
		}

		loading = true;
		errors = {};

		try {
			await verifyPasswordOTP({
				email: email.trim(),
				otp: otpCode,
				new_password: newPassword
			});
			toasts.success('Password reset successfully! Please sign in with your new password.');
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto('/login');
		} catch (err) {
			const apiErr = err as ApiError;
			if (apiErr.status === 400) {
				const message = apiErr.message?.toLowerCase() ?? '';
				if (message.includes('expired')) {
					errors = { form: 'OTP has expired. Please request a new code.' };
				} else if (message.includes('invalid') || message.includes('otp')) {
					errors = { form: 'Invalid OTP code. Please check and try again.' };
				} else {
					errors = { form: 'Invalid request. Please try again.' };
				}
			} else if (apiErr.status === 429) {
				errors = { form: 'Too many attempts. Please try again later.' };
			} else {
				errors = { form: 'Something went wrong. Please try again later.' };
			}
			triggerShake();
		} finally {
			loading = false;
		}
	}

	async function handleResendOTP() {
		if (resendCooldown > 0) return;

		loading = true;
		errors = {};

		try {
			const result = await requestPasswordOTP(email.trim());
			if (result.success === false) {
				errors = { form: result.message || 'Failed to resend code. Please try again.' };
				return;
			}
			toasts.info('A new verification code has been sent to your email.');
			startResendCooldown();
			// Clear existing OTP input
			otpDigits = ['', '', '', '', '', ''];
			otpInputRefs[0]?.focus();
		} catch (err) {
			const apiErr = err as ApiError;
			if (apiErr.status === 429) {
				errors = { form: 'Too many attempts. Please try again later.' };
			} else {
				errors = { form: 'Failed to resend code. Please try again.' };
			}
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Reset Password — Jatayu AI</title>
	<meta name="description" content="Reset your Jatayu AI account password." />
</svelte:head>

<div class="flex min-h-screen w-full items-center justify-center bg-background px-4 py-12">
	<div class="w-full max-w-[420px]">
		<!-- Logo -->
		<div class="mb-8 flex justify-center">
			<img
				src="/logos/logo-black.png"
				alt="Jatayu AI"
				class="logo-light h-7 w-auto"
				style="filter: drop-shadow(0 0 0.8px rgba(0,0,0,0.8))"
			/>
			<img
				src="/logos/logo-white.png"
				alt="Jatayu AI"
				class="logo-dark h-7 w-auto"
				style="filter: drop-shadow(0 0 0.8px rgba(255,255,255,0.8))"
			/>
		</div>

		<!-- Card -->
		<div class="rounded-2xl border border-border-subtle bg-surface p-8">
			<!-- Step indicator -->
			<div class="mb-6 flex items-center gap-2">
				{#each ['email', 'otp', 'password'] as s, i (s)}
					<div
						class="h-0.5 flex-1 rounded-full transition-colors duration-300 {s === step
							? 'bg-accent'
							: ['email', 'otp', 'password'].indexOf(step) > i
								? 'bg-accent/40'
								: 'bg-surface-2'}"
					></div>
				{/each}
			</div>

			{#if step === 'email'}
				<!-- Step 1: Enter email -->
				<div class="mb-6 text-center">
					<h1 class="text-2xl font-normal tracking-tight text-foreground">Reset your password</h1>
					<p class="mt-1.5 text-sm text-subtle">
						Enter your email and we'll send you a verification code.
					</p>
				</div>

				<form
					onsubmit={handleEmailSubmit}
					class="flex flex-col gap-4 {formShake ? 'auth-shake' : ''}"
					novalidate
				>
					{#if errors.form}
						<div
							class="auth-error-fade rounded-lg border border-accent/15 bg-accent/[0.04] px-4 py-3 text-sm text-accent/85"
							role="alert"
						>
							{errors.form}
						</div>
					{/if}

					<Input
						label="Email"
						type="email"
						placeholder="you@example.com"
						bind:value={email}
						error={errors.email}
						required
						autocomplete="email"
					/>

					<Button type="submit" variant="primary" class="mt-1 w-full py-2.5" disabled={loading}>
						{#if loading}
							<LoadingSpinner class="mr-2" />
							Sending code...
						{:else}
							Send Verification Code
						{/if}
					</Button>
				</form>
			{:else if step === 'otp'}
				<!-- Step 2: Enter OTP -->
				<div class="mb-6 text-center">
					<h1 class="text-2xl font-normal tracking-tight text-foreground">Check your email</h1>
					<p class="mt-1.5 text-sm text-subtle">
						We sent a 6-digit code to <span class="font-medium text-foreground">{email}</span>
					</p>
				</div>

				<form
					onsubmit={handleOtpSubmit}
					class="flex flex-col gap-4 {formShake ? 'auth-shake' : ''}"
					novalidate
				>
					{#if errors.form}
						<div
							class="auth-error-fade rounded-lg border border-accent/15 bg-accent/[0.04] px-4 py-3 text-sm text-accent/85"
							role="alert"
						>
							{errors.form}
						</div>
					{/if}

					<!-- OTP digit inputs -->
					<div class="flex justify-center gap-3" role="group" aria-label="Verification code">
						{#each otpDigits as digit, i (i)}
							<input
								bind:this={otpInputRefs[i]}
								type="text"
								inputmode="numeric"
								maxlength="6"
								value={digit}
								oninput={(e) => handleOtpInput(i, e)}
								onkeydown={(e) => handleOtpKeydown(i, e)}
								aria-label="Digit {i + 1}"
								class="h-12 w-11 rounded-xl border text-center text-lg font-medium transition-all duration-200
									{digit
									? 'border-accent/40 bg-accent/[0.04] text-foreground'
									: 'border-border-subtle bg-surface-2 text-foreground'}
									focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
							/>
						{/each}
					</div>

					{#if errors.otp}
						<p class="auth-error-fade text-center text-sm text-accent/85">{errors.otp}</p>
					{/if}

					<Button
						type="submit"
						variant="primary"
						class="mt-1 w-full py-2.5"
						disabled={loading || otpCode.length !== 6}
					>
						Verify Code
					</Button>
				</form>

				<!-- Resend OTP -->
				<div class="mt-5 text-center">
					<p class="text-sm text-subtle">
						Didn't receive the code?
						{#if resendCooldown > 0}
							<span class="font-medium text-muted">
								Resend in {resendCooldown}s
							</span>
						{:else}
							<button
								type="button"
								onclick={handleResendOTP}
								disabled={loading}
								class="cursor-pointer font-medium text-foreground transition-colors hover:text-accent disabled:opacity-50"
							>
								Resend code
							</button>
						{/if}
					</p>
				</div>

				<!-- Back button -->
				<button
					type="button"
					onclick={() => {
						loading = false;
						step = 'email';
						errors = {};
					}}
					class="mt-3 flex w-full cursor-pointer items-center justify-center gap-1 text-xs text-muted transition-colors hover:text-foreground"
				>
					<svg
						class="h-3.5 w-3.5"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
						xmlns="http://www.w3.org/2000/svg"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M15 19l-7-7 7-7"
						></path>
					</svg>
					Back to email
				</button>
			{:else}
				<!-- Step 3: New password -->
				<div class="mb-6 text-center">
					<h1 class="text-2xl font-normal tracking-tight text-foreground">Set new password</h1>
					<p class="mt-1.5 text-sm text-subtle">Choose a strong password for your account.</p>
				</div>

				<form
					onsubmit={handlePasswordSubmit}
					class="flex flex-col gap-4 {formShake ? 'auth-shake' : ''}"
					novalidate
				>
					{#if errors.form}
						<div
							class="auth-error-fade rounded-lg border border-accent/15 bg-accent/[0.04] px-4 py-3 text-sm text-accent/85"
							role="alert"
						>
							{errors.form}
						</div>
					{/if}

					<div>
						<Input
							label="New password"
							type="password"
							placeholder="Enter new password"
							bind:value={newPassword}
							error={errors.password}
							required
							autocomplete="new-password"
						/>
						{#if newPassword}
							<div class="mt-2.5 flex items-center gap-2.5">
								<div class="flex flex-1 gap-1">
									{#each [1, 2, 3] as level (level)}
										<div
											class="h-0.5 flex-1 rounded-full transition-colors duration-300 {passwordStrength >=
											level
												? strengthBarColor
												: 'bg-surface-2'}"
										></div>
									{/each}
								</div>
								<span class="text-[11px] font-medium {strengthTextColor}">
									{strengthLabel}
								</span>
							</div>
						{/if}
					</div>

					<Input
						label="Confirm password"
						type="password"
						placeholder="Confirm new password"
						bind:value={confirmPassword}
						error={errors.confirmPassword}
						required
						autocomplete="new-password"
					/>

					<Button type="submit" variant="primary" class="mt-1 w-full py-2.5" disabled={loading}>
						{#if loading}
							<LoadingSpinner class="mr-2" />
							Resetting password...
						{:else}
							Reset Password
						{/if}
					</Button>
				</form>

				<!-- Back button -->
				<button
					type="button"
					onclick={() => {
						loading = false;
						step = 'otp';
						errors = {};
					}}
					class="mt-4 flex w-full cursor-pointer items-center justify-center gap-1 text-xs text-muted transition-colors hover:text-foreground"
				>
					<svg
						class="h-3.5 w-3.5"
						fill="none"
						stroke="currentColor"
						viewBox="0 0 24 24"
						xmlns="http://www.w3.org/2000/svg"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M15 19l-7-7 7-7"
						></path>
					</svg>
					Back to verification
				</button>
			{/if}
		</div>

		<!-- Login link -->
		<p class="mt-5 text-center text-sm text-subtle">
			Remember your password?
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			<a href="/login" class="font-medium text-foreground transition-colors hover:text-accent">
				Sign in
			</a>
			<!-- eslint-enable svelte/no-navigation-without-resolve -->
		</p>

		<!-- Footer links -->
		<!-- eslint-disable svelte/no-navigation-without-resolve -->
		<div class="mt-8 border-t border-border-subtle pt-5">
			<div class="flex flex-wrap justify-center gap-x-5 gap-y-2 text-xs text-muted">
				<a href="/tutorials" class="transition-colors duration-200 hover:text-accent">Tutorials</a>
				<a href="/changelog" class="transition-colors duration-200 hover:text-accent">Changelog</a>
				<a href="/contact" class="transition-colors duration-200 hover:text-accent">Support</a>
				<a href="/terms" class="transition-colors duration-200 hover:text-accent">Terms</a>
				<a href="/privacy" class="transition-colors duration-200 hover:text-accent">Privacy</a>
			</div>
			<p class="mt-3 text-center text-[11px] text-muted">
				&copy; {new Date().getFullYear()} Jatayu AI
			</p>
		</div>
		<!-- eslint-enable svelte/no-navigation-without-resolve -->
	</div>
</div>
