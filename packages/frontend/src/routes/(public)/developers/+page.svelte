<script lang="ts">
	import { onMount } from 'svelte';

	let container: HTMLDivElement;
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			const { createApiReference } = await import('@scalar/api-reference');
			await import('@scalar/api-reference/style.css');

			createApiReference(container, {
				url: '/api/v1/developer/openapi.json',
				theme: 'kepler',
				hideDownloadButton: false,
				hideModels: false,
				defaultHttpClient: {
					targetKey: 'js',
					clientKey: 'fetch'
				}
			});

			loading = false;
		} catch (e) {
			console.error('Failed to load API docs:', e);
			error = 'Failed to load API documentation. Please try again later.';
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>Developer API Documentation — Jatayu AI</title>
	<meta
		name="description"
		content="Interactive API documentation for the Jatayu AI developer API."
	/>
</svelte:head>

<div class="developers-page">
	{#if loading}
		<div class="flex min-h-screen items-center justify-center bg-background">
			<div class="flex flex-col items-center gap-3">
				<div
					class="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-800"
				></div>
				<p class="text-sm text-zinc-500">Loading API documentation…</p>
			</div>
		</div>
	{/if}

	{#if error}
		<div class="flex min-h-screen items-center justify-center bg-background">
			<div class="flex flex-col items-center gap-4 text-center">
				<p class="text-sm text-red-500">{error}</p>
				<button
					class="rounded-md bg-zinc-800 px-4 py-2 text-sm text-white hover:bg-zinc-700"
					onclick={() => location.reload()}
				>
					Retry
				</button>
			</div>
		</div>
	{/if}

	<div bind:this={container} class:hidden={loading || !!error}></div>
</div>

<style>
	.developers-page {
		min-height: 100vh;
	}

	.developers-page :global(.scalar-app) {
		min-height: 100vh;
	}
</style>
