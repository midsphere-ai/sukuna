<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { setAuth, authToken } from '$stores/auth';
	import { fetchCurrentUser } from '$api/auth';
	import LoadingSpinner from '$components/ui/LoadingSpinner.svelte';

	let error = $state('');

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

	onMount(async () => {
		const token = page.url.searchParams.get('token');
		if (!token) {
			error = 'No authentication token received.';
			return;
		}

		try {
			authToken.set(token);
			const user = await fetchCurrentUser();
			const dest = hasCompletedOnboarding(user) ? '/' : '/onboarding';
			setAuth(token, user);
			goto(resolve(dest));
		} catch {
			error = 'Authentication failed. Please try again.';
		}
	});
</script>

<svelte:head>
	<title>Authenticating... — Jatayu AI</title>
</svelte:head>

<div class="flex min-h-screen w-full items-center justify-center bg-background">
	{#if error}
		<div class="text-center">
			<p class="mb-4 text-sm text-accent/85">{error}</p>
			<a href={resolve('/login')} class="text-sm font-medium text-foreground hover:text-accent">
				Back to login
			</a>
		</div>
	{:else}
		<div class="flex flex-col items-center gap-3">
			<LoadingSpinner />
			<p class="text-sm text-subtle">Signing you in...</p>
		</div>
	{/if}
</div>
