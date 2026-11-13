<script lang="ts">
	import Button from '$components/ui/Button.svelte';
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- public nav links are standard navigation -->
<nav class="mx-auto flex h-16 max-w-6xl items-center justify-between px-6 sm:px-8">
	<!-- Logo -->
	<a href="/" class="flex items-center">
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
	</a>

	<!-- Auth actions -->
	<div class="flex items-center gap-2">
		<Button href="/login" variant="default" class="text-sm">Sign In</Button>
		<Button href="/signup" variant="primary" class="rounded-lg px-4 py-2 text-sm">Sign Up</Button>
	</div>
</nav>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
