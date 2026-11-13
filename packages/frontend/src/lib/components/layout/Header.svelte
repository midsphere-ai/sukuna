<script lang="ts">
	import { Avatar, Badge } from '$components/ui';
	import NotificationCenter from '$components/layout/NotificationCenter.svelte';
	import TauriWindowControls from '$components/layout/TauriWindowControls.svelte';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { currentUser } from '$stores/auth';
	import { logout } from '$api/auth';
	import { creditBalance, ensureCreditBalance } from '$stores/credits';
	import { subscription as subscriptionStore } from '$stores/subscription';
	import { isTauri } from '$utils/platform';
	import { onMount } from 'svelte';
	import type { CreditBalance, UserSubscription } from '$api/types';

	let title = $state('Home');
	pageTitle.subscribe((v) => (title = v));

	let showTitle = $state(true);
	showHeaderTitle.subscribe((v) => (showTitle = v));

	let userName = $state('');
	let userEmail = $state('');
	let userPlan = $state('Free');

	currentUser.subscribe((u) => {
		if (u) {
			userName = u.name || '';
			userEmail = u.email || '';
		}
	});

	let balance = $state<CreditBalance | null>(null);
	creditBalance.subscribe((v) => (balance = v));

	let sub = $state<UserSubscription | null>(null);
	subscriptionStore.subscribe((v) => {
		sub = v;
		if (v?.plan?.name) userPlan = v.plan.name;
	});

	const creditsAvailable = $derived(balance?.total_available ?? null);
	const monthlyTotal = $derived(sub?.plan?.monthly_credits ?? balance?.monthly_credits ?? 300);
	const creditPercent = $derived(
		monthlyTotal > 0 && creditsAvailable !== null ? (creditsAvailable / monthlyTotal) * 100 : 100
	);
	const creditColor = $derived(
		creditPercent > 50 ? 'text-success' : creditPercent > 20 ? 'text-amber-500' : 'text-accent'
	);

	let popoverOpen = $state(false);

	onMount(() => {
		ensureCreditBalance();
	});

	function togglePopover(): void {
		popoverOpen = !popoverOpen;
	}

	function closePopover(): void {
		popoverOpen = false;
	}

	function handlePopoverKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			closePopover();
		}
	}

	async function handleLogout(): Promise<void> {
		closePopover();
		await logout();
	}
</script>

<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (
			popoverOpen &&
			!target.closest('[data-header-popover]') &&
			!target.closest('[data-notification-center]')
		) {
			closePopover();
		}
	}}
/>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<header
	class="hidden h-[var(--header-height)] shrink-0 items-center justify-between border-b border-border-subtle px-5 lg:flex"
	data-tauri-drag-region={isTauri() ? '' : undefined}
>
	<!-- Page title -->
	{#if showTitle}
		<h1 class="text-[15px] font-medium tracking-tight text-foreground">{title}</h1>
	{:else}
		<div></div>
	{/if}

	<!-- Right section: tasks count, notification bell, user avatar -->
	<div class="flex items-center gap-2">
		<!-- Credit balance -->
		{#if creditsAvailable !== null}
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			<a
				href="/billing"
				class="flex items-center gap-1.5 text-[13px] transition-colors hover:text-accent {creditColor}"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="14"
					height="14"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<circle cx="12" cy="12" r="8" />
					<path d="M14.5 9a3.5 3.5 0 00-5 0" />
					<path d="M12 12v4" />
					<path d="M12 8v.01" />
				</svg>
				<span class="tabular-nums">{creditsAvailable.toLocaleString()} credits</span>
			</a>
			<!-- eslint-enable svelte/no-navigation-without-resolve -->
		{/if}

		{#if creditsAvailable !== null}
			<div class="h-4 w-px bg-border"></div>
		{/if}

		<!-- Notification center -->
		<NotificationCenter />

		<!-- User avatar with popover -->
		<div class="relative" data-header-popover>
			<button
				onclick={togglePopover}
				class="rounded-full ring-2 ring-transparent transition-shadow duration-150 hover:ring-border"
				aria-label="User menu"
				aria-expanded={popoverOpen}
				aria-haspopup="true"
			>
				<Avatar src={null} name={userName} size="sm" />
			</button>

			{#if popoverOpen}
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<!-- svelte-ignore a11y_interactive_supports_focus -->
				<div
					class="popover-animate absolute top-full right-0 z-50 mt-2 w-60 rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-xl"
					role="menu"
					onkeydown={handlePopoverKeydown}
				>
					<!-- User info -->
					<div class="border-b border-border-subtle px-3 py-2.5">
						<p class="text-[13px] font-medium text-foreground">{userName || 'Account'}</p>
						<p class="mt-0.5 text-[11px] text-muted">{userEmail}</p>
						<div class="mt-1.5">
							<Badge variant={userPlan === 'Free' ? 'muted' : 'coral'}>{userPlan}</Badge>
						</div>
					</div>

					<!-- Actions -->
					<div class="py-0.5">
						<button
							onclick={handleLogout}
							class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[13px] text-subtle transition-colors duration-150 hover:bg-surface-2 hover:text-accent"
							role="menuitem"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="15"
								height="15"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
								<polyline points="16 17 21 12 16 7" />
								<line x1="21" y1="12" x2="9" y2="12" />
							</svg>
							<span>Log out</span>
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if isTauri()}
		<div class="shrink-0 border-l border-border-subtle">
			<TauriWindowControls />
		</div>
	{/if}
</header>

<style>
	.popover-animate {
		animation: popover-in 150ms ease-out;
	}
	@keyframes popover-in {
		from {
			opacity: 0;
			transform: scale(0.95) translateY(-4px);
		}
		to {
			opacity: 1;
			transform: scale(1) translateY(0);
		}
	}
</style>
