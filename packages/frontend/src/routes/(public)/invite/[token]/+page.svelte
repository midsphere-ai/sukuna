<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import { isAuthenticated } from '$stores/auth';
	import { getInvitationInfo, acceptInvitation, type InvitationInfo } from '$api/organizations';

	const token = $derived((page.params as Record<string, string>).token ?? '');

	let info: InvitationInfo | null = $state(null);
	let loading = $state(true);
	let accepting = $state(false);
	let error: string | null = $state(null);
	let accepted = $state(false);
	let acceptResult: { organization_name: string; role: string } | null = $state(null);

	async function loadInfo(): Promise<void> {
		try {
			info = await getInvitationInfo(token);
		} catch (err: unknown) {
			const status = (err as { status?: number })?.status;
			if (status === 410) {
				error = 'This invitation is no longer valid. It may have expired or been revoked.';
			} else if (status === 404) {
				error = 'Invitation not found.';
			} else {
				error = 'Failed to load invitation details.';
			}
		} finally {
			loading = false;
		}
	}

	async function handleAccept(): Promise<void> {
		if (!$isAuthenticated) {
			// Redirect to login with a return URL
			goto(`/login?next=/invite/${token}`);
			return;
		}

		accepting = true;
		try {
			const result = await acceptInvitation(token);
			if (result.success) {
				accepted = true;
				acceptResult = { organization_name: result.organization_name, role: result.role };
				toasts.success(result.message);
			}
		} catch (err: unknown) {
			const status = (err as { status?: number })?.status;
			if (status === 410) {
				error = 'This invitation is no longer valid.';
			} else if (status === 429) {
				toasts.error('Too many attempts. Please try again later.');
			} else {
				toasts.error('Failed to accept invitation.');
			}
		} finally {
			accepting = false;
		}
	}

	function goToOrg(): void {
		goto('/');
	}

	onMount(loadInfo);
</script>

<div class="flex min-h-[80vh] items-center justify-center px-4">
	{#if loading}
		<div class="flex flex-col items-center gap-3">
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
			<p class="text-sm text-muted">Loading invitation...</p>
		</div>
	{:else if error}
		<div class="w-full max-w-md text-center" in:fade={{ duration: 150 }}>
			<div class="rounded-2xl border border-border bg-background p-8 shadow-sm">
				<div
					class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-50 dark:bg-red-900/20"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="24"
						height="24"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="text-red-500"
					>
						<circle cx="12" cy="12" r="10" />
						<line x1="15" y1="9" x2="9" y2="15" />
						<line x1="9" y1="9" x2="15" y2="15" />
					</svg>
				</div>
				<h2 class="text-lg font-medium text-foreground">Invitation Unavailable</h2>
				<p class="mt-2 text-sm text-muted">{error}</p>
				<button
					onclick={() => goto('/')}
					class="mt-6 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-all duration-200 hover:bg-foreground/90"
				>
					Go Home
				</button>
			</div>
		</div>
	{:else if accepted && acceptResult}
		<div class="w-full max-w-md text-center" in:fade={{ duration: 150 }}>
			<div class="rounded-2xl border border-border bg-background p-8 shadow-sm">
				<div
					class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-green-50 dark:bg-green-900/20"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="24"
						height="24"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="text-green-500"
					>
						<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
						<polyline points="22 4 12 14.01 9 11.01" />
					</svg>
				</div>
				<h2 class="text-lg font-medium text-foreground">You're In!</h2>
				<p class="mt-2 text-sm text-muted">
					You've joined <strong class="text-foreground">{acceptResult.organization_name}</strong> as
					<span class="capitalize">{acceptResult.role}</span>.
				</p>
				<button
					onclick={goToOrg}
					class="mt-6 rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-all duration-200 hover:bg-foreground/90"
				>
					Get Started
				</button>
			</div>
		</div>
	{:else if info}
		<div class="w-full max-w-md" in:fade={{ duration: 150 }}>
			<div class="rounded-2xl border border-border bg-background p-8 shadow-sm">
				<div class="text-center">
					<div
						class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-blue-50 dark:bg-blue-900/20"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="24"
							height="24"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-blue-500"
						>
							<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
							<circle cx="9" cy="7" r="4" />
							<line x1="19" y1="8" x2="19" y2="14" />
							<line x1="22" y1="11" x2="16" y2="11" />
						</svg>
					</div>
					<h2 class="text-lg font-medium text-foreground">You're Invited</h2>
					<p class="mt-2 text-sm text-muted">
						{#if info.invited_by_name}
							<strong class="text-foreground">{info.invited_by_name}</strong> invited you to join
						{:else}
							You've been invited to join
						{/if}
					</p>
				</div>

				<!-- Org details -->
				<div class="mt-6 rounded-xl border border-border-subtle bg-surface px-4 py-3">
					<p class="text-sm font-medium text-foreground">{info.organization_name}</p>
					<div class="mt-1 flex items-center gap-2">
						<span class="text-xs text-muted">Role:</span>
						<span
							class="rounded-lg px-2 py-0.5 text-xs font-medium capitalize
								{info.role === 'admin'
								? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400'
								: 'bg-surface text-muted'}"
						>
							{info.role}
						</span>
					</div>
					{#if info.expires_at}
						<p class="mt-1 text-xs text-muted">
							Expires: {new Date(info.expires_at).toLocaleDateString()}
						</p>
					{/if}
				</div>

				<!-- Actions -->
				<div class="mt-6 space-y-3">
					{#if $isAuthenticated}
						<button
							onclick={handleAccept}
							disabled={accepting}
							class="w-full rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
						>
							{accepting ? 'Joining...' : 'Accept Invitation'}
						</button>
					{:else}
						<button
							onclick={handleAccept}
							class="w-full rounded-lg bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-all duration-200 hover:bg-foreground/90"
						>
							Log In & Accept
						</button>
						<button
							onclick={() => goto(`/signup?next=/invite/${token}`)}
							class="w-full rounded-lg border border-border px-5 py-2.5 text-sm font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
						>
							Create Account & Join
						</button>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>
