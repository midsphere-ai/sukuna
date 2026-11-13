<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import Input from '$components/ui/Input.svelte';
	import Toggle from '$components/ui/Toggle.svelte';
	import Button from '$components/ui/Button.svelte';
	import LoadingSpinner from '$components/ui/LoadingSpinner.svelte';
	import { login, loginWithGoogle } from '$api/auth';
	import { isTauri } from '$utils/platform';

	let email = $state('');
	let password = $state('');
	let rememberMe = $state(false);
	let loading = $state(false);
	let googleLoading = $state(false);
	let errors = $state<{ email?: string; password?: string; form?: string }>({});

	function hasCompletedOnboarding(user: {
		name?: string;
		last_login?: string | null;
		onboarding_completed?: boolean;
	}): boolean {
		if (typeof user.onboarding_completed === 'boolean') {
			return user.onboarding_completed;
		}
		return Boolean(user.name) && user.last_login !== null;
	}

	// After login, redirect to ?next= URL if present (e.g. /?prompt=...), otherwise /
	function getPostLoginUrl(user: {
		name?: string;
		last_login?: string | null;
		onboarding_completed?: boolean;
	}): string {
		if (!hasCompletedOnboarding(user)) return '/onboarding';
		const next = page.url.searchParams.get('next');
		if (next && next.startsWith('/') && !next.startsWith('//')) return next;
		return '/';
	}
	let formShake = $state(false);

	function validate(): boolean {
		const newErrors: typeof errors = {};

		if (!email.trim()) {
			newErrors.email = 'Email is required';
		} else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
			newErrors.email = 'Please enter a valid email address';
		}

		if (!password) {
			newErrors.password = 'Password is required';
		} else if (password.length < 6) {
			newErrors.password = 'Password must be at least 6 characters';
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

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		if (loading || googleLoading) return;
		if (!validate()) {
			triggerShake();
			return;
		}

		loading = true;
		errors = {};

		try {
			const user = await login({ email: email.trim(), password }, rememberMe);
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto(getPostLoginUrl(user));
		} catch (err) {
			const apiErr = err as { status?: number };
			if (apiErr.status === 400 || apiErr.status === 401) {
				errors = { form: 'Invalid email or password. Please try again.' };
			} else if (apiErr.status && apiErr.status >= 500) {
				errors = { form: 'Server error. Please try again later.' };
			} else {
				errors = { form: 'Something went wrong. Please check your connection and try again.' };
			}
			triggerShake();
		} finally {
			loading = false;
		}
	}

	async function handleGoogleSignIn() {
		if (loading || googleLoading) return;
		googleLoading = true;
		errors = {};

		// Capture rememberMe value before the async callback
		const shouldRemember = rememberMe;

		// Native Tauri flow: open system browser for OAuth, receive id_token via deep link
		if (isTauri()) {
			try {
				const { startGoogleOAuthNative } = await import('$services/tauriAuth');
				const idToken = await startGoogleOAuthNative();
				if (idToken) {
					const user = await loginWithGoogle(idToken, shouldRemember);
					// eslint-disable-next-line svelte/no-navigation-without-resolve
					goto(getPostLoginUrl(user));
				} else {
					errors = { form: 'Google sign-in was cancelled or timed out.' };
				}
			} catch {
				errors = { form: 'Google sign-in failed. Please try again.' };
			} finally {
				googleLoading = false;
			}
			return;
		}

		try {
			// Initialize Google Sign-In
			const google = (window as unknown as Record<string, unknown>).google as
				| {
						accounts: {
							id: {
								initialize: (config: Record<string, unknown>) => void;
								prompt: (
									callback: (notification: { isNotDisplayed: () => boolean }) => void
								) => void;
							};
						};
				  }
				| undefined;

			if (!google) {
				errors = { form: 'Google Sign-In is not available. Please try email login.' };
				googleLoading = false;
				return;
			}

			google.accounts.id.initialize({
				client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID ?? '',
				callback: async (response: { credential?: string }) => {
					if (response.credential) {
						try {
							const user = await loginWithGoogle(response.credential, shouldRemember);
							// eslint-disable-next-line svelte/no-navigation-without-resolve
							goto(getPostLoginUrl(user));
						} catch {
							errors = { form: 'Google sign-in failed. Please try again.' };
						}
					}
					googleLoading = false;
				}
			});

			google.accounts.id.prompt((notification) => {
				if (notification.isNotDisplayed()) {
					errors = { form: 'Google Sign-In popup was blocked. Please allow popups and try again.' };
					googleLoading = false;
				}
			});
		} catch {
			errors = { form: 'Google Sign-In is not available. Please try email login.' };
			googleLoading = false;
		}
	}
</script>

<svelte:head>
	<title>Sign In — Jatayu AI</title>
	<meta name="description" content="Sign in to Jatayu AI to manage your AI agents and tasks." />
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
			<!-- Header -->
			<div class="mb-6 text-center">
				<h1 class="text-2xl font-normal tracking-tight text-foreground">Welcome back</h1>
				<p class="mt-1.5 text-sm text-subtle">Sign in to continue to Jatayu AI</p>
			</div>

			<!-- OAuth provider buttons -->
			<div class="flex flex-col gap-2.5">
				<!-- Google -->
				<button
					type="button"
					onclick={handleGoogleSignIn}
					disabled={googleLoading || loading}
					class="flex w-full cursor-pointer items-center justify-center gap-3 rounded-xl border border-border-subtle bg-surface-2 px-4 py-2.5 text-sm font-medium text-foreground transition-all duration-200 hover:border-border-strong hover:bg-surface-2 disabled:pointer-events-none disabled:opacity-50"
				>
					{#if googleLoading}
						<LoadingSpinner class="mr-2" />
						Signing in...
					{:else}
						<svg class="h-5 w-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
							<path
								d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"
								fill="#4285F4"
							/>
							<path
								d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
								fill="#34A853"
							/>
							<path
								d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
								fill="#FBBC05"
							/>
							<path
								d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
								fill="#EA4335"
							/>
						</svg>
						Continue with Google
					{/if}
				</button>

				<!-- GitHub -->
				<a
					href={resolve('/accounts/github/login/?process=login')}
					class="flex w-full items-center justify-center gap-3 rounded-xl border border-border-subtle bg-surface-2 px-4 py-2.5 text-sm font-medium text-foreground no-underline transition-all duration-200 hover:border-border-strong hover:bg-surface-2"
				>
					<svg class="h-5 w-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
						<path
							d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.865 8.17 6.839 9.49.5.092.682-.217.682-.482 0-.237-.008-.866-.013-1.7-2.782.604-3.369-1.34-3.369-1.34-.454-1.156-1.11-1.464-1.11-1.464-.908-.62.069-.607.069-.607 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0112 6.836a9.59 9.59 0 012.504.337c1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.203 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.167 22 16.418 22 12c0-5.523-4.477-10-10-10z"
							fill="currentColor"
						/>
					</svg>
					Continue with GitHub
				</a>

				<!-- Microsoft -->
				<a
					href={resolve('/accounts/microsoft/login/?process=login')}
					class="flex w-full items-center justify-center gap-3 rounded-xl border border-border-subtle bg-surface-2 px-4 py-2.5 text-sm font-medium text-foreground no-underline transition-all duration-200 hover:border-border-strong hover:bg-surface-2"
				>
					<svg class="h-5 w-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
						<rect x="2" y="2" width="9.5" height="9.5" fill="#F25022" />
						<rect x="12.5" y="2" width="9.5" height="9.5" fill="#7FBA00" />
						<rect x="2" y="12.5" width="9.5" height="9.5" fill="#00A4EF" />
						<rect x="12.5" y="12.5" width="9.5" height="9.5" fill="#FFB900" />
					</svg>
					Continue with Microsoft
				</a>

				<!-- Apple -->
				<a
					href={resolve('/accounts/apple/login/?process=login')}
					class="flex w-full items-center justify-center gap-3 rounded-xl border border-border-subtle bg-surface-2 px-4 py-2.5 text-sm font-medium text-foreground no-underline transition-all duration-200 hover:border-border-strong hover:bg-surface-2"
				>
					<svg class="h-5 w-5" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
						<path
							d="M17.05 20.28c-.98.95-2.05.88-3.08.4-1.09-.5-2.08-.48-3.24 0-1.44.62-2.2.44-3.06-.4C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"
							fill="currentColor"
						/>
					</svg>
					Continue with Apple
				</a>
			</div>

			<!-- Divider -->
			<div class="my-5 flex items-center gap-4">
				<div class="h-px flex-1 bg-surface-2"></div>
				<span class="text-xs text-muted">or</span>
				<div class="h-px flex-1 bg-surface-2"></div>
			</div>

			<!-- Login form -->
			<form
				onsubmit={handleSubmit}
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

				<Input
					label="Password"
					type="password"
					placeholder="Enter your password"
					bind:value={password}
					error={errors.password}
					required
					autocomplete="current-password"
				/>

				<div class="flex items-center justify-between">
					<Toggle label="Remember me" bind:checked={rememberMe} />
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a
						href="/forgot-password"
						class="text-xs font-medium text-subtle transition-colors hover:text-accent"
					>
						Forgot password?
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				</div>

				<Button
					type="submit"
					variant="primary"
					class="mt-1 w-full py-2.5"
					disabled={loading || googleLoading}
				>
					{#if loading}
						<LoadingSpinner class="mr-2" />
						Signing in...
					{:else}
						Sign In
					{/if}
				</Button>
			</form>
		</div>

		<!-- Sign up link -->
		<p class="mt-5 text-center text-sm text-subtle">
			Don't have an account?
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			<a href="/signup" class="font-medium text-foreground transition-colors hover:text-accent">
				Sign up
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
