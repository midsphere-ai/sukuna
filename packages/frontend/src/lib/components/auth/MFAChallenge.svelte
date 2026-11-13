<script lang="ts">
	import { verifyMFA } from '$lib/api/mfa';
	import { currentUser, clearAuth } from '$stores/auth';
	import { get } from 'svelte/store';
	import { initAuth } from '$api/auth';

	let code = $state('');
	let busy = $state(false);
	let error = $state<string | null>(null);

	async function submit(e: Event) {
		e.preventDefault();
		if (!code.trim()) return;
		busy = true;
		error = null;
		try {
			await verifyMFA(code.trim());
			// Refresh /users/me so the layout sees mfa_pending = false
			await initAuth();
			const u = get(currentUser);
			if (u?.mfa_pending) {
				error = 'Verification did not promote your session. Please try again.';
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Invalid code';
		} finally {
			busy = false;
		}
	}

	function logout() {
		clearAuth();
		location.href = '/login';
	}
</script>

<div class="flex h-dvh items-center justify-center bg-background px-4">
	<form
		onsubmit={submit}
		class="w-full max-w-sm space-y-5 rounded-2xl border border-divider bg-light p-8 shadow-sm"
	>
		<div>
			<h1 class="text-xl font-medium text-foreground">Two-factor authentication</h1>
			<p class="mt-1 text-sm text-muted">
				Enter the 6-digit code from your authenticator app, or a recovery code.
			</p>
		</div>
		<input
			type="text"
			inputmode="numeric"
			autocomplete="one-time-code"
			autofocus
			bind:value={code}
			placeholder="123456"
			class="w-full rounded-lg border border-divider px-4 py-3 text-center font-mono text-2xl tracking-widest focus:border-foreground focus:outline-none"
		/>
		{#if error}
			<div class="text-sm text-red-600">{error}</div>
		{/if}
		<button
			type="submit"
			disabled={busy || !code.trim()}
			class="w-full rounded-lg bg-foreground py-2.5 text-sm font-medium text-light hover:bg-foreground/90 disabled:opacity-50"
		>
			{busy ? 'Verifying…' : 'Verify'}
		</button>
		<button type="button" onclick={logout} class="w-full text-xs text-muted hover:text-foreground">
			Sign out instead
		</button>
	</form>
</div>
