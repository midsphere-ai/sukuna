<script lang="ts">
	import { page } from '$app/state';

	const is404 = $derived(page.status === 404);
	const is500 = $derived(page.status >= 500);

	const title = $derived(
		is404 ? 'Page not found' : is500 ? 'Something went wrong' : 'An error occurred'
	);

	const description = $derived(
		is404
			? "This page doesn't exist, or it was moved."
			: is500
				? 'Our servers hit a snag. Try again in a moment.'
				: (page.error?.message ?? 'An unexpected error occurred.')
	);
</script>

<svelte:head>
	<title>{page.status} — {title} — Jatayu AI</title>
</svelte:head>

<div class="flex min-h-screen flex-col items-center justify-center bg-background px-4">
	<div class="w-full max-w-md text-center">
		<p
			class="text-[clamp(8rem,25vw,16rem)] leading-none font-medium tracking-tighter text-foreground/[0.05]"
		>
			{page.status}
		</p>

		{#if is404}
			<p class="-mt-1 text-sm text-foreground">
				You've wandered off the map. Even our agents can't find this one.
			</p>
		{:else if is500}
			<p class="-mt-1 text-sm text-foreground">
				Our servers tripped over themselves. Give it a sec.
			</p>
		{:else}
			<h1 class="-mt-2 text-lg font-normal tracking-tight text-foreground">{title}</h1>
			<p class="mt-1.5 text-sm leading-relaxed text-subtle">{description}</p>
		{/if}

		<!-- eslint-disable svelte/no-navigation-without-resolve -- error page links are static -->
		<div class="mt-8 flex items-center justify-center gap-3">
			{#if is404}
				<a
					href="/"
					class="rounded-lg bg-foreground px-5 py-2 text-sm font-medium text-background transition-transform duration-150"
				>
					Go home
				</a>
				<button
					onclick={() => history.back()}
					class="cursor-pointer rounded-lg border border-border-strong px-5 py-2 text-sm font-medium text-subtle transition-colors duration-150 hover:border-border-strong hover:text-foreground"
				>
					Go back
				</button>
			{:else if is500}
				<button
					onclick={() => window.location.reload()}
					class="cursor-pointer rounded-lg bg-foreground px-5 py-2 text-sm font-medium text-background transition-transform duration-150"
				>
					Try again
				</button>
				<a
					href="/"
					class="rounded-lg border border-border-strong px-5 py-2 text-sm font-medium text-subtle transition-colors duration-150 hover:border-border-strong hover:text-foreground"
				>
					Go home
				</a>
			{:else}
				<a
					href="/"
					class="rounded-lg bg-foreground px-5 py-2 text-sm font-medium text-background transition-transform duration-150"
				>
					Go home
				</a>
				<button
					onclick={() => history.back()}
					class="cursor-pointer rounded-lg border border-border-strong px-5 py-2 text-sm font-medium text-subtle transition-colors duration-150 hover:border-border-strong hover:text-foreground"
				>
					Go back
				</button>
			{/if}
		</div>
		<!-- eslint-enable svelte/no-navigation-without-resolve -->
	</div>
</div>
