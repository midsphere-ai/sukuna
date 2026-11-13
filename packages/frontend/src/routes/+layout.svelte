<script lang="ts">
	// Medium-only policy: ship only 400 (regular) and 500 (medium). No 600+.
	import '@fontsource/inter-tight/400.css';
	import '@fontsource/inter-tight/500.css';
	import '@fontsource/jetbrains-mono/400.css';
	import '@fontsource/jetbrains-mono/500.css';
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { onMount } from 'svelte';
	import { initAnalytics } from '$services/analytics';
	import { initPWA } from '$stores/pwa';
	import CookieConsent from '$components/ui/CookieConsent.svelte';
	import Toast from '$components/ui/Toast.svelte';
	import NavigationProgress from '$components/ui/NavigationProgress.svelte';
	import UsageLimitModal from '$components/billing/UsageLimitModal.svelte';

	let { children } = $props();

	onMount(() => {
		initAnalytics();
		initPWA();
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<NavigationProgress />
{@render children()}
<CookieConsent />
<Toast />
<UsageLimitModal />
