<script lang="ts">
	import Dialog from '$components/ui/Dialog.svelte';
	import { dev, version as svelteKitVersion } from '$app/environment';
	import { goto } from '$app/navigation';

	type Props = {
		open: boolean;
	};

	let { open = $bindable(false) }: Props = $props();

	const appVersion = '0.0.1';
	const buildId = svelteKitVersion;
	const environment = dev ? 'Development' : 'Production';

	const info: [string, string][] = [
		['App', 'Jatayu AI'],
		['Version', appVersion],
		['Build', buildId],
		['Platform', 'SvelteKit'],
		['Environment', environment]
	];
</script>

<Dialog bind:open>
	<div class="p-6 text-center">
		<!-- Header -->
		<div class="mb-5">
			<span class="inline-block text-4xl leading-none animate-bounce">&#x2728;</span>
			<h2 class="mt-3 text-lg font-normal text-foreground">You found the secret!</h2>
			<p class="mt-1 text-sm text-subtle">Nice detective work. Here's what's under the hood.</p>
		</div>

		<!-- Info grid -->
		<div class="mx-auto max-w-xs rounded-xl border border-border-subtle bg-surface p-4 text-left">
			{#each info as [label, value] (label)}
				<div class="flex items-center justify-between py-1.5">
					<span class="text-xs font-medium text-muted uppercase tracking-wider">{label}</span>
					<span class="text-sm text-foreground font-mono">{value}</span>
				</div>
			{/each}
		</div>

		<!-- Footer -->
		<p class="mt-5 text-xs text-muted">Made with care in India</p>
		<button
			onclick={() => {
				open = false;
				goto('/flags');
			}}
			class="mt-1 text-[10px] text-muted/50 transition-colors duration-150 hover:text-muted cursor-pointer"
		>
			experimental features
		</button>

		<!-- Close -->
		<button
			onclick={() => (open = false)}
			class="mt-4 rounded-lg bg-surface-2 px-4 py-1.5 text-sm text-subtle transition-colors duration-150 hover:bg-border hover:text-foreground"
		>
			Close
		</button>
	</div>
</Dialog>
