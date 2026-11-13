<script lang="ts">
	import { creditBalance, ensureCreditBalance } from '$stores/credits';
	import { subscription as subscriptionStore } from '$stores/subscription';
	import { onMount } from 'svelte';
	import type { CreditBalance } from '$api/types';
	import type { UserSubscription } from '$api/types';

	let balance = $state<CreditBalance | null>(null);
	let sub = $state<UserSubscription | null>(null);

	const unsub1 = creditBalance.subscribe((v) => (balance = v));
	const unsub2 = subscriptionStore.subscribe((v) => (sub = v));

	const totalAvailable = $derived(balance?.total_available ?? 0);
	const monthlyTotal = $derived(sub?.plan?.monthly_credits ?? balance?.monthly_credits ?? 300);
	const percentRemaining = $derived(monthlyTotal > 0 ? (totalAvailable / monthlyTotal) * 100 : 100);
	const colorClass = $derived(
		percentRemaining > 50 ? 'text-muted' : percentRemaining > 20 ? 'text-warning' : 'text-accent'
	);

	onMount(() => {
		ensureCreditBalance();
		return () => {
			unsub1();
			unsub2();
		};
	});
</script>

{#if balance}
	<!-- eslint-disable svelte/no-navigation-without-resolve -->
	<a
		href="/billing"
		class="flex items-center gap-1.5 rounded-[var(--radius-md)] px-2 py-1 text-[12px] transition-colors duration-150 hover:bg-surface-2 {colorClass}"
		title="Credits: {totalAvailable.toLocaleString()} available"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="14"
			height="14"
			viewBox="0 0 24 24"
			fill="currentColor"
		>
			<path d="M12 1C12 1 14.5 8.5 12 12C9.5 8.5 12 1 12 1Z" />
			<path d="M12 23C12 23 9.5 15.5 12 12C14.5 15.5 12 23 12 23Z" />
			<path d="M1 12C1 12 8.5 9.5 12 12C8.5 14.5 1 12 1 12Z" />
			<path d="M23 12C23 12 15.5 14.5 12 12C15.5 9.5 23 12 23 12Z" />
		</svg>
		<span class="tabular-nums font-medium">{totalAvailable.toLocaleString()}</span>
	</a>
	<!-- eslint-enable svelte/no-navigation-without-resolve -->
{/if}
