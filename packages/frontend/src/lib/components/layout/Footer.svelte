<script lang="ts">
	import { reopenConsentBanner } from '$stores/consent';
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- footer links are standard navigation -->
<footer class="border-t border-border-subtle px-6 py-10 sm:px-8">
	<div class="mx-auto max-w-6xl">
		<div class="flex flex-col items-center gap-6 sm:flex-row sm:justify-between">
			<!-- Logo + tagline -->
			<div class="text-center sm:text-left">
				<a href="/" class="inline-flex items-center">
					<img
						src="/logos/logo-black.png"
						alt="Jatayu AI"
						class="logo-light h-6 w-auto"
						style="filter: drop-shadow(0 0 0.8px rgba(0,0,0,0.8))"
					/>
					<img
						src="/logos/logo-white.png"
						alt="Jatayu AI"
						class="logo-dark h-6 w-auto"
						style="filter: drop-shadow(0 0 0.8px rgba(255,255,255,0.8))"
					/>
				</a>
				<p class="mt-1 text-xs text-muted">Think fast, Build even faster.</p>
			</div>

			<!-- Links -->
			<div class="flex flex-wrap justify-center gap-x-6 gap-y-2 text-sm text-subtle">
				<a href="/tutorials" class="transition-colors duration-200 hover:text-accent">Tutorials</a>
				<a href="/changelog" class="transition-colors duration-200 hover:text-accent">Changelog</a>
				<a href="/support" class="transition-colors duration-200 hover:text-accent">Support</a>
				<a href="/terms" class="transition-colors duration-200 hover:text-accent">Terms</a>
				<a href="/privacy" class="transition-colors duration-200 hover:text-accent">Privacy</a>
				<button
					onclick={reopenConsentBanner}
					class="transition-colors duration-200 hover:text-accent"
				>
					Manage Cookies
				</button>
			</div>
		</div>

		<!-- Copyright -->
		<p class="mt-8 text-center text-xs text-muted">
			&copy; {new Date().getFullYear()} Jatayu AI. All rights reserved.
		</p>
	</div>
</footer>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
