<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	onMount(() => {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto('/onboarding?flow=enterprise');
	});
</script>

<div class="flex min-h-dvh items-center justify-center bg-background p-6 text-subtle">
	<p class="text-sm">Redirecting to onboarding…</p>
</div>
