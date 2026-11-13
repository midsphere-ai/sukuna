<script lang="ts">
	import { page } from '$app/state';
	import TauriTitleBar from '$components/layout/TauriTitleBar.svelte';
	import { isTauri } from '$utils/platform';

	let { children } = $props();
</script>

{#key page.url.pathname}
	<div class="page-enter flex min-h-screen flex-col bg-background">
		{#if isTauri()}
			<TauriTitleBar />
		{/if}
		<a href="#main-content" class="skip-to-content">Skip to content</a>
		<main id="main-content" class="flex-1">
			{@render children()}
		</main>
	</div>
{/key}
