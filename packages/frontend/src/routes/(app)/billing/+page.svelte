<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { animateWidth, countUp } from '$lib/actions/animate';
	import { Skeleton, EmptyState, PageHeader, Badge } from '$components/ui';
	import InfoButton from '$components/ui/InfoButton.svelte';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import {
		cancelSubscription,
		reactivateSubscription,
		getPaymentHistory,
		retryPayment,
		requestRefund,
		getCreditTransactions,
		purchaseCredits
	} from '$api/billing';
	import {
		subscription as subscriptionStore,
		subscriptionLoading,
		fetchSubscription
	} from '$stores/subscription';
	import { creditBalance, fetchCreditBalance, invalidateCreditBalance } from '$stores/credits';
	import type { UserSubscription, Payment, CreditBalance, CreditTransaction } from '$api/types';

	// SessionStorage cache for payments
	function loadPaymentCache(): Payment[] {
		try {
			const raw = sessionStorage.getItem('midsphere-billing-payments');
			if (raw) return JSON.parse(raw) as Payment[];
		} catch {
			/* ignore */
		}
		return [];
	}

	const cachedPayments = loadPaymentCache();
	const cachedSub = subscriptionStore;

	let subscription: UserSubscription | null = $state(null);
	let payments: Payment[] = $state(cachedPayments);
	let paymentsLoading = $state(cachedPayments.length === 0);
	let loading = $state(true);

	// Subscribe to shared subscription store
	cachedSub.subscribe((v) => {
		subscription = v;
		if (v) loading = false;
	});
	subscriptionLoading.subscribe((v) => {
		if (!subscription) loading = v;
	});
	let error = $state('');
	let cancelDialogOpen = $state(false);
	let cancelReason = $state('');
	let actionLoading = $state(false);

	// Refund dialog state
	let refundDialogOpen = $state(false);
	let refundPayment: Payment | null = $state(null);
	let refundReason = $state('');
	let refundLoading = $state(false);
	let retryLoading = $state(false);

	// Credit state
	let balance: CreditBalance | null = $state(null);
	creditBalance.subscribe((v) => (balance = v));
	let creditTxns: CreditTransaction[] = $state([]);
	let creditTxnsLoading = $state(true);
	let creditTxnPage = $state(1);
	let creditTxnCategory = $state<string | undefined>(undefined);
	let creditTxnHasMore = $state(false);
	let purchaseDialogOpen = $state(false);
	let purchasePacks = $state(1);
	let purchaseLoading = $state(false);

	pageTitle.set('Billing & Usage');
	showHeaderTitle.set(false);

	// Tier badge variant
	function tierVariant(tier: string): 'coral' | 'blue' | 'default' {
		switch (tier) {
			case 'premium':
				return 'coral';
			case 'basic':
				return 'blue';
			default:
				return 'default';
		}
	}

	// Status badge variant
	function statusVariant(status: string): 'green' | 'coral' | 'blue' | 'muted' | 'default' {
		switch (status) {
			case 'active':
				return 'green';
			case 'cancelled':
				return 'coral';
			case 'pending':
				return 'blue';
			case 'expired':
				return 'muted';
			default:
				return 'default';
		}
	}

	// Usage bar percentage
	function usagePercent(used: number, limit: number): number {
		if (limit <= 0) return 0;
		return Math.min(100, Math.round((used / limit) * 100));
	}

	// Usage bar color based on percentage
	function usageBarColor(percent: number): string {
		if (percent >= 90) return 'bg-accent';
		if (percent >= 70) return 'bg-amber-500';
		return 'bg-success';
	}

	// Payment status badge variant
	function paymentStatusVariant(status: string): 'green' | 'blue' | 'coral' | 'muted' | 'default' {
		switch (status) {
			case 'captured':
				return 'green';
			case 'authorized':
				return 'blue';
			case 'failed':
				return 'coral';
			case 'refunded':
			case 'refund_pending':
				return 'muted';
			default:
				return 'default';
		}
	}

	function paymentStatusLabel(status: string): string {
		switch (status) {
			case 'captured':
				return 'Paid';
			case 'refund_pending':
				return 'Refund pending';
			default:
				return status.charAt(0).toUpperCase() + status.slice(1);
		}
	}

	function canRefund(payment: Payment): boolean {
		return payment.status === 'captured' && payment.amount > 0;
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}

	async function loadSubscriptionData(): Promise<void> {
		error = '';
		try {
			await fetchSubscription();
		} catch {
			if (!subscription) error = 'Unable to load subscription details.';
		}
	}

	async function loadPayments(): Promise<void> {
		if (payments.length === 0) paymentsLoading = true;
		try {
			const result = await getPaymentHistory();
			payments = result.items;
			try {
				sessionStorage.setItem('midsphere-billing-payments', JSON.stringify(result.items));
			} catch {
				/* ignore */
			}
		} catch {
			// Non-critical — just show empty if no cache
			if (payments.length === 0) payments = [];
		} finally {
			paymentsLoading = false;
		}
	}

	async function handleRetryPayment(): Promise<void> {
		retryLoading = true;
		try {
			const result = await retryPayment();
			if (result.payment_link) {
				window.location.href = result.payment_link;
				return;
			}
			toasts.success(result.message || 'Payment retry initiated.');
			await loadPayments();
		} catch {
			toasts.error('Failed to retry payment.');
		} finally {
			retryLoading = false;
		}
	}

	function openRefundDialog(payment: Payment): void {
		refundPayment = payment;
		refundReason = '';
		refundDialogOpen = true;
	}

	async function handleRefund(): Promise<void> {
		if (!refundPayment) return;
		refundLoading = true;
		try {
			await requestRefund(refundPayment.id, refundReason);
			toasts.success('Refund request submitted.');
			refundDialogOpen = false;
			refundPayment = null;
			refundReason = '';
			await loadPayments();
		} catch {
			toasts.error('Failed to request refund.');
		} finally {
			refundLoading = false;
		}
	}

	async function handleCancel(): Promise<void> {
		actionLoading = true;
		try {
			await cancelSubscription(false);
			toasts.success(
				'Subscription cancelled. It will remain active until the end of your billing period.'
			);
			cancelDialogOpen = false;
			cancelReason = '';
			await loadSubscriptionData();
		} catch {
			toasts.error('Failed to cancel subscription.');
		} finally {
			actionLoading = false;
		}
	}

	async function handleReactivate(): Promise<void> {
		actionLoading = true;
		try {
			await reactivateSubscription();
			toasts.success('Subscription reactivated.');
			await loadSubscriptionData();
		} catch {
			toasts.error('Failed to reactivate subscription.');
		} finally {
			actionLoading = false;
		}
	}

	// Credit transaction helpers
	const creditCategories = [
		{ key: undefined, label: 'All' },
		{ key: 'llm', label: 'LLM' },
		{ key: 'compute', label: 'Compute' },
		{ key: 'integration', label: 'Integration' },
		{ key: 'purchase', label: 'Purchase' },
		{ key: 'refund', label: 'Refund' },
		{ key: 'grant', label: 'Grant' }
	] as const;

	function categoryBadgeColor(cat: string): string {
		switch (cat) {
			case 'llm':
				return 'bg-purple-100 text-purple-700';
			case 'compute':
				return 'bg-blue-100 text-blue-700';
			case 'integration':
				return 'bg-amber-100 text-amber-700';
			case 'purchase':
				return 'bg-success/10 text-success';
			case 'refund':
				return 'bg-accent/10 text-accent';
			case 'grant':
			case 'refresh':
			case 'signup_bonus':
				return 'bg-emerald-100 text-emerald-700';
			default:
				return 'bg-surface-2 text-subtle';
		}
	}

	const PAGE_SIZE = 25;

	async function loadCreditTransactions(): Promise<void> {
		creditTxnsLoading = true;
		try {
			const result = await getCreditTransactions(creditTxnPage, creditTxnCategory);
			creditTxns = result.items;
			creditTxnHasMore = result.items.length >= PAGE_SIZE;
		} catch {
			creditTxns = [];
		} finally {
			creditTxnsLoading = false;
		}
	}

	function setCreditCategory(cat: string | undefined): void {
		creditTxnCategory = cat;
		creditTxnPage = 1;
		loadCreditTransactions();
	}

	async function handlePurchaseCredits(): Promise<void> {
		purchaseLoading = true;
		try {
			const result = await purchaseCredits(purchasePacks);
			if (result.checkout_url) {
				// Redirect to Dodo Payments checkout
				window.location.href = result.checkout_url;
				return;
			}
			toasts.error('Unable to start payment. Please try again.');
		} catch {
			toasts.error('Failed to initiate credit purchase.');
		} finally {
			purchaseLoading = false;
		}
	}

	onMount(() => {
		loadSubscriptionData();
		loadPayments();
		fetchCreditBalance();
		loadCreditTransactions();
	});
</script>

<svelte:head>
	<title>Billing & Usage - Jatayu AI</title>
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
	<PageHeader
		title="Billing & Usage"
		description="Manage your subscription, view usage metrics, and control your plan."
		class="mb-8"
	>
		{#snippet actions()}
			<InfoButton context="billing" size="md" />
		{/snippet}
	</PageHeader>

	{#if loading}
		<div class="space-y-0" out:fade={{ duration: 80 }}>
			<!-- Plan overview skeleton -->
			<section class="pb-6">
				<div class="flex items-center gap-2">
					<Skeleton class="rounded" width="120px" height="20px" />
					<Skeleton class="rounded-full" width="52px" height="20px" stagger={1} />
					<Skeleton class="rounded-full" width="44px" height="20px" stagger={1} />
				</div>
				<Skeleton class="mt-2 rounded" width="100px" height="28px" stagger={2} />
				<Skeleton class="mt-2 rounded" width="200px" height="12px" stagger={3} />
			</section>

			<!-- Credit balance skeleton -->
			<section class="border-t border-border-subtle py-6">
				<div class="flex items-center justify-between">
					<Skeleton class="rounded" width="100px" height="16px" stagger={2} />
					<Skeleton class="rounded-lg" width="90px" height="32px" stagger={3} />
				</div>
				<Skeleton class="mt-4 rounded" width="80px" height="32px" stagger={3} />
				<Skeleton class="mt-1 rounded" width="100px" height="11px" stagger={4} />
				<div class="mt-4 space-y-1.5">
					<div class="flex items-center justify-between">
						<Skeleton class="rounded" width="120px" height="12px" stagger={4} />
						<Skeleton class="rounded" width="64px" height="12px" stagger={4} />
					</div>
					<Skeleton class="rounded-full" width="100%" height="6px" stagger={5} />
				</div>
				<div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
					{#each [0, 1, 2, 3] as i (i)}
						<div class="rounded-lg bg-surface px-3 py-2">
							<Skeleton class="rounded" width="48px" height="11px" stagger={i + 4} />
							<Skeleton class="mt-1 rounded" width="40px" height="14px" stagger={i + 5} />
						</div>
					{/each}
				</div>
			</section>
		</div>
	{:else if error}
		<div class="py-12 text-center">
			<p class="text-sm text-subtle">{error}</p>
			<button
				onclick={loadSubscriptionData}
				class="mt-3 rounded-lg bg-surface-2 px-4 py-2 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
			>
				Try again
			</button>
		</div>
	{:else if subscription}
		<div class="space-y-0" in:fade={{ duration: 150, delay: 50 }}>
			<!-- Plan overview -->
			<section class="pb-6">
				<div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-lg font-medium text-foreground">
								{subscription.plan.name}
							</h2>
							<Badge variant={tierVariant(subscription.plan.tier)}>
								{subscription.plan.tier}
							</Badge>
							<Badge variant={statusVariant(subscription.status)}>
								{subscription.status}
							</Badge>
						</div>

						{#if subscription.plan.price > 0}
							<p class="mt-1 text-2xl tabular-nums text-foreground">
								${subscription.plan.price}<span class="text-sm text-muted">/month</span>
							</p>
						{:else}
							<p class="mt-1 text-base text-subtle">Free plan</p>
						{/if}

						{#if subscription.start_date}
							<p class="mt-1.5 text-xs text-muted">
								Since {new Date(subscription.start_date).toLocaleDateString('en-US', {
									month: 'long',
									day: 'numeric',
									year: 'numeric'
								})}
								{#if subscription.end_date}
									&middot; Renews {new Date(subscription.end_date).toLocaleDateString('en-US', {
										month: 'long',
										day: 'numeric',
										year: 'numeric'
									})}
								{/if}
							</p>
						{/if}
					</div>

					<div class="flex flex-wrap gap-2">
						{#if subscription.status === 'active'}
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a
								href="/billing/plans"
								class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-colors hover:border-border-strong hover:bg-surface-2"
							>
								Change plan
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
							{#if subscription.plan.tier !== 'free'}
								<button
									onclick={() => (cancelDialogOpen = true)}
									class="rounded-lg border border-accent/20 px-4 py-2 text-xs font-medium text-accent transition-colors hover:border-accent/30 hover:bg-accent/5"
								>
									Cancel
								</button>
							{/if}
						{:else if subscription.status === 'cancelled'}
							<button
								onclick={handleReactivate}
								disabled={actionLoading}
								class="rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
							>
								{actionLoading ? 'Reactivating...' : 'Reactivate'}
							</button>
						{:else if subscription.status === 'expired'}
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<a
								href="/billing/plans"
								class="rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-accent/90"
							>
								Choose a plan
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						{/if}
					</div>
				</div>
			</section>

			<!-- Credit Balance -->
			{#if balance}
				{@const monthlyTotal = subscription.plan.monthly_credits || 300}
				{@const monthlyUsed = monthlyTotal - (balance.monthly_credits_remaining ?? 0)}
				{@const monthlyPercent =
					monthlyTotal > 0 ? Math.min(100, Math.round((monthlyUsed / monthlyTotal) * 100)) : 0}
				<section class="border-t border-border-subtle py-6">
					<div class="flex items-center justify-between mb-4">
						<h3 class="text-sm font-medium text-foreground">Credits</h3>
						<button
							onclick={() => {
								purchasePacks = 1;
								purchaseDialogOpen = true;
							}}
							class="rounded-lg bg-success/10 px-3 py-1.5 text-xs font-medium text-success transition-colors hover:bg-success/20"
						>
							Buy credits
						</button>
					</div>

					<div class="mb-5">
						<p class="text-3xl font-medium tabular-nums text-foreground">
							<span use:countUp={balance.total_available}></span>
						</p>
						<p class="mt-0.5 text-xs text-muted">credits available</p>
					</div>

					<!-- Monthly pool progress -->
					<div class="mb-4">
						<div class="mb-1.5 flex items-baseline justify-between">
							<span class="text-sm text-foreground">Monthly allowance</span>
							<span class="text-xs tabular-nums text-muted">
								{(balance.monthly_credits_remaining ?? 0).toLocaleString()} / {monthlyTotal.toLocaleString()}
							</span>
						</div>
						<div class="h-1.5 overflow-hidden rounded-full bg-surface-2">
							<div
								class="h-full rounded-full transition-all duration-500 {usageBarColor(
									monthlyPercent
								)}"
								use:animateWidth={`${Math.min(monthlyPercent, 100)}%`}
							></div>
						</div>
					</div>

					<!-- Pool breakdown -->
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
						<div class="rounded-lg bg-surface px-3 py-2">
							<p class="text-xs text-muted">Monthly</p>
							<p class="text-sm font-medium tabular-nums text-foreground">
								{(balance.monthly_credits_remaining ?? 0).toLocaleString()}
							</p>
						</div>
						<div class="rounded-lg bg-surface px-3 py-2">
							<p class="text-xs text-muted">Add-on</p>
							<p class="text-sm font-medium tabular-nums text-foreground">
								{(balance.addon_credits ?? 0).toLocaleString()}
							</p>
						</div>
						<div class="rounded-lg bg-surface px-3 py-2">
							<p class="text-xs text-muted">Free</p>
							<p class="text-sm font-medium tabular-nums text-foreground">
								{(balance.free_credits ?? 0).toLocaleString()}
							</p>
						</div>
						<div class="rounded-lg bg-surface px-3 py-2">
							<p class="text-xs text-muted">Grants</p>
							<p class="text-sm font-medium tabular-nums text-foreground">
								{(balance.active_grants ?? 0).toLocaleString()}
							</p>
						</div>
					</div>
				</section>
			{/if}

			<!-- Credit History -->
			<section class="border-t border-border-subtle py-6">
				<h3 class="mb-4 text-sm font-medium text-foreground">Credit history</h3>
				<div class="mb-4 flex flex-wrap gap-1.5">
					{#each creditCategories as cat (cat.label)}
						<button
							onclick={() => setCreditCategory(cat.key)}
							class="rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors {creditTxnCategory ===
							cat.key
								? 'bg-foreground text-white'
								: 'bg-surface text-subtle hover:bg-surface-2 hover:text-foreground'}"
						>
							{cat.label}
						</button>
					{/each}
				</div>

				{#if creditTxnsLoading}
					<div class="space-y-2">
						{#each [0, 1, 2, 3] as i (i)}
							<Skeleton class="h-10 w-full rounded-lg" />
						{/each}
					</div>
				{:else if creditTxns.length === 0}
					<p class="py-6 text-center text-sm text-muted">No credit transactions yet.</p>
				{:else}
					<div class="divide-y divide-border-subtle">
						{#each creditTxns as txn (txn.id)}
							<div class="flex items-center justify-between py-2.5 first:pt-0 last:pb-0">
								<div class="flex items-center gap-3 min-w-0">
									<span
										class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium {categoryBadgeColor(
											txn.category
										)}"
									>
										{txn.category}
									</span>
									<span class="truncate text-sm text-subtle">{txn.description}</span>
								</div>
								<div class="flex shrink-0 items-center gap-3 ml-3">
									<span
										class="text-sm font-medium tabular-nums {txn.amount < 0
											? 'text-accent'
											: 'text-success'}"
									>
										{txn.amount < 0 ? '' : '+'}{txn.amount.toLocaleString()}
									</span>
									<span class="text-xs tabular-nums text-muted">
										{formatDate(txn.created_at)}
									</span>
								</div>
							</div>
						{/each}
					</div>
					<div class="mt-3 flex items-center justify-between">
						<button
							onclick={() => {
								creditTxnPage = Math.max(1, creditTxnPage - 1);
								loadCreditTransactions();
							}}
							disabled={creditTxnPage <= 1}
							class="rounded-md px-3 py-1 text-xs font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-30"
						>
							Previous
						</button>
						<span class="text-xs text-muted">Page {creditTxnPage}</span>
						<button
							onclick={() => {
								creditTxnPage += 1;
								loadCreditTransactions();
							}}
							disabled={!creditTxnHasMore}
							class="rounded-md px-3 py-1 text-xs font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-30"
						>
							Next
						</button>
					</div>
				{/if}
			</section>

			<!-- Usage -->
			{#if subscription.usage_schema}
				{@const usage = subscription.usage_schema}
				{@const usageItems = [
					{ label: 'Credits', metric: usage.credits, format: 'count' as const },
					{ label: 'Concurrent tasks', metric: usage.concurrent_tasks, format: 'count' as const }
				].filter((item) => item.metric)}
				<section class="border-t border-border-subtle py-6">
					<h3 class="mb-4 text-sm font-medium text-foreground">Usage</h3>
					<div class="space-y-4">
						{#each usageItems as item (item.label)}
							{@const percent = usagePercent(item.metric.used, item.metric.limit)}
							<div>
								<div class="mb-1.5 flex items-baseline justify-between">
									<span class="text-sm text-foreground">{item.label}</span>
									<span class="text-xs tabular-nums text-muted">
										{item.metric.used} / {item.metric.limit}
									</span>
								</div>
								<div class="h-1.5 overflow-hidden rounded-full bg-surface-2">
									<div
										class="h-full rounded-full transition-all duration-500 {usageBarColor(percent)}"
										use:animateWidth={`${Math.min(percent, 100)}%`}
									></div>
								</div>
							</div>
						{/each}
					</div>
				</section>
			{/if}

			<!-- Plan features -->
			<section class="border-t border-border-subtle py-6">
				<h3 class="mb-4 text-sm font-medium text-foreground">Plan features</h3>
				<div class="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
					{#each Object.entries(subscription.plan.features) as [key, value] (key)}
						{@const label = key.replace(/_/g, ' ')}
						{@const resolvedValue = Array.isArray(value) ? value[0] : value}
						<div class="flex items-center justify-between gap-2">
							<span class="text-sm capitalize text-subtle">{label}</span>
							<span class="text-sm font-medium text-foreground">
								{#if resolvedValue === true || resolvedValue === 'true'}
									<svg
										class="h-4 w-4 text-success"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2.5"><path d="M5 13l4 4L19 7" /></svg
									>
								{:else if resolvedValue === false || resolvedValue === 'false'}
									<svg
										class="h-4 w-4 text-muted"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"><path d="M18 6L6 18M6 6l12 12" /></svg
									>
								{:else}
									{resolvedValue}
								{/if}
							</span>
						</div>
					{/each}
				</div>
			</section>

			<!-- Transactions -->
			<section class="border-t border-border-subtle py-6">
				<div class="mb-4 flex items-center justify-between">
					<h3 class="text-sm font-medium text-foreground">Transactions</h3>
					{#if payments.some((p) => p.status === 'failed')}
						<button
							onclick={handleRetryPayment}
							disabled={retryLoading}
							class="rounded-lg bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-50"
						>
							{retryLoading ? 'Retrying...' : 'Retry failed'}
						</button>
					{/if}
				</div>

				{#if paymentsLoading}
					<div class="space-y-3">
						{#each [0, 1, 2] as i (i)}
							<Skeleton class="h-12 w-full rounded-lg" />
						{/each}
					</div>
				{:else if payments.length === 0}
					<p class="py-6 text-center text-sm text-muted">
						No transactions yet. Your payment history will appear here.
					</p>
				{:else}
					<div class="divide-y divide-border-subtle">
						{#each payments as payment (payment.id)}
							<div
								class="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
							>
								<div class="flex items-center gap-3">
									<div
										class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg {payment.status ===
										'failed'
											? 'bg-accent/10'
											: payment.status === 'refunded' || payment.status === 'refund_pending'
												? 'bg-surface'
												: 'bg-success/10'}"
									>
										{#if payment.status === 'failed'}
											<svg
												class="h-3.5 w-3.5 text-accent"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="2"
												><circle cx="12" cy="12" r="10" /><path d="M15 9l-6 6m0-6l6 6" /></svg
											>
										{:else if payment.status === 'refunded' || payment.status === 'refund_pending'}
											<svg
												class="h-3.5 w-3.5 text-muted"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="2"><path d="M3 10h10a5 5 0 015 5v2M3 10l4-4m-4 4l4 4" /></svg
											>
										{:else}
											<svg
												class="h-3.5 w-3.5 text-success"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="2.5"><path d="M5 13l4 4L19 7" /></svg
											>
										{/if}
									</div>
									<div>
										<div class="flex items-center gap-2">
											<span class="text-sm font-medium tabular-nums text-foreground">
												{payment.currency}
												{payment.amount.toFixed(2)}
											</span>
											<Badge variant={paymentStatusVariant(payment.status)} class="text-[10px]">
												{paymentStatusLabel(payment.status)}
											</Badge>
										</div>
										<p class="text-xs text-muted">
											{formatDate(payment.created_at)}
											{#if payment.dodo_payment_id}
												<span class="ml-1 text-muted">&middot; {payment.dodo_payment_id}</span>
											{/if}
										</p>
									</div>
								</div>

								<div class="flex gap-1.5 sm:shrink-0">
									{#if payment.status === 'failed'}
										<button
											onclick={handleRetryPayment}
											disabled={retryLoading}
											class="rounded-lg bg-accent/10 px-2.5 py-1 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-50"
										>
											Retry
										</button>
									{/if}
									{#if canRefund(payment)}
										<button
											onclick={() => openRefundDialog(payment)}
											class="rounded-lg bg-surface px-2.5 py-1 text-[11px] font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
										>
											Request refund
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</section>

			<!-- Support link -->
			<div class="border-t border-border-subtle pt-6 text-center">
				<p class="text-sm text-muted">
					Having billing issues?
					<!-- eslint-disable svelte/no-navigation-without-resolve -->
					<a href="/support" class="font-medium text-subtle transition-colors hover:text-accent">
						Contact support
					</a>
					<!-- eslint-enable svelte/no-navigation-without-resolve -->
				</p>
			</div>
		</div>
	{/if}
</div>

<!-- ═══ Cancel Confirmation Dialog ═══ -->
{#if cancelDialogOpen}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20"
		role="dialog"
		aria-modal="true"
		aria-label="Cancel subscription"
		tabindex="-1"
		onkeydown={(e) => {
			if (e.key === 'Escape') cancelDialogOpen = false;
		}}
	>
		<div
			class="mx-4 w-full max-w-md rounded-2xl border border-border-subtle bg-surface-2 p-6 shadow-xl"
		>
			<h3 class="text-lg font-normal text-foreground">Cancel subscription</h3>
			<p class="mt-2 text-sm text-subtle">
				Your subscription will remain active until the end of your current billing period. After
				that, you'll be downgraded to the Free plan.
			</p>

			<label class="mt-4 block">
				<span class="text-xs font-medium text-subtle">Reason (optional)</span>
				<textarea
					bind:value={cancelReason}
					placeholder="Help us improve — why are you cancelling?"
					rows="3"
					class="mt-1 w-full rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm text-foreground transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:outline-none focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				></textarea>
			</label>

			<div class="mt-5 flex justify-end gap-2">
				<button
					onclick={() => {
						cancelDialogOpen = false;
						cancelReason = '';
					}}
					class="rounded-xl px-4 py-2.5 text-xs font-medium text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
				>
					Keep subscription
				</button>
				<button
					onclick={handleCancel}
					disabled={actionLoading}
					class="rounded-xl bg-accent px-4 py-2.5 text-xs font-medium text-white transition-all duration-200 hover:bg-accent/90 disabled:opacity-50"
				>
					{actionLoading ? 'Cancelling...' : 'Confirm cancellation'}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- ═══ Refund Confirmation Dialog ═══ -->
{#if refundDialogOpen && refundPayment}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20"
		role="dialog"
		aria-modal="true"
		aria-label="Request refund"
		tabindex="-1"
		onkeydown={(e) => {
			if (e.key === 'Escape') refundDialogOpen = false;
		}}
	>
		<div class="mx-4 w-full max-w-md rounded-2xl border border-border bg-background p-6 shadow-xl">
			<h3 class="text-lg font-normal text-foreground">Request refund</h3>
			<p class="mt-2 text-sm text-subtle">
				Request a refund of <span class="font-medium"
					>{refundPayment.currency} {refundPayment.amount.toFixed(2)}</span
				>
				from {formatDate(refundPayment.created_at)}. Refunds are typically processed within 5–10
				business days.
			</p>

			<label class="mt-4 block">
				<span class="text-xs font-medium text-subtle">Reason (optional)</span>
				<textarea
					bind:value={refundReason}
					placeholder="Why are you requesting a refund?"
					rows="3"
					class="mt-1 w-full rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm text-foreground transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:outline-none focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				></textarea>
			</label>

			<div class="mt-5 flex justify-end gap-2">
				<button
					onclick={() => {
						refundDialogOpen = false;
						refundReason = '';
					}}
					class="rounded-xl px-4 py-2.5 text-xs font-medium text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
				>
					Cancel
				</button>
				<button
					onclick={handleRefund}
					disabled={refundLoading}
					class="rounded-xl bg-foreground/80 px-4 py-2.5 text-xs font-medium text-white transition-all duration-200 hover:bg-foreground/70 disabled:opacity-50"
				>
					{refundLoading ? 'Submitting...' : 'Submit refund request'}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- ═══ Purchase Credits Dialog ═══ -->
{#if purchaseDialogOpen}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20"
		role="dialog"
		aria-modal="true"
		aria-label="Buy credits"
		tabindex="-1"
		onkeydown={(e) => {
			if (e.key === 'Escape' && !purchaseLoading) purchaseDialogOpen = false;
		}}
	>
		<div class="mx-4 w-full max-w-sm rounded-2xl border border-border bg-background p-6 shadow-xl">
			<h3 class="text-lg font-normal text-foreground">Buy credit packs</h3>
			<p class="mt-2 text-sm text-subtle">
				1,000 credits per pack at $2.50 each. Add-on credits never expire.
			</p>

			<div class="mt-4">
				<label class="block">
					<span class="text-xs font-medium text-subtle">Number of packs</span>
					<input
						type="number"
						bind:value={purchasePacks}
						min="1"
						max="10"
						class="mt-1 w-full rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm tabular-nums text-foreground transition-all duration-200 focus:border-border-strong focus:outline-none focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
					/>
				</label>
				<div class="mt-3 flex items-baseline justify-between rounded-lg bg-surface px-3 py-2">
					<span class="text-sm text-subtle">Total</span>
					<span class="text-lg font-medium tabular-nums text-foreground">
						{(purchasePacks * 1000).toLocaleString()} credits
						<span class="text-sm font-normal text-muted">
							(${(purchasePacks * 2.5).toFixed(2)})
						</span>
					</span>
				</div>
			</div>

			<div class="mt-5 flex justify-end gap-2">
				<button
					onclick={() => {
						purchaseDialogOpen = false;
						purchasePacks = 1;
					}}
					disabled={purchaseLoading}
					class="rounded-xl px-4 py-2.5 text-xs font-medium text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					onclick={handlePurchaseCredits}
					disabled={purchaseLoading || purchasePacks < 1}
					class="rounded-xl bg-success px-4 py-2.5 text-xs font-medium text-white transition-all duration-200 hover:bg-success/90 disabled:opacity-50"
				>
					{purchaseLoading ? 'Processing...' : 'Purchase'}
				</button>
			</div>
		</div>
	</div>
{/if}
