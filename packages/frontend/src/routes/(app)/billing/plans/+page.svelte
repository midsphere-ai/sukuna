<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { fade } from 'svelte/transition';
	import { zenReveal } from '$lib/actions/animate';
	import { Skeleton, PageHeader, Badge } from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import {
		getSubscriptionPlans,
		getUserSubscription,
		createSubscription,
		changePlan,
		validatePromoCode
	} from '$api/billing';
	import type { SubscriptionPlan, UserSubscription } from '$api/types';

	let plans: SubscriptionPlan[] = $state([]);
	let currentSubscription: UserSubscription | null = $state(null);
	let loading = $state(true);
	let error = $state('');
	let actionPlanId = $state('');
	let actionLoading = $state(false);

	// Promo code state
	let promoCode = $state('');
	let promoApplied = $state(false);
	let promoError = $state('');
	let promoDiscount: { type: 'percentage' | 'fixed'; value: number } | null = $state(null);

	// Confirm dialog
	let confirmOpen = $state(false);
	let confirmPlan: SubscriptionPlan | null = $state(null);
	let confirmAction: 'upgrade' | 'downgrade' | 'subscribe' = $state('subscribe');

	pageTitle.set('Choose a Plan');
	showHeaderTitle.set(false);

	// Tier ordering for upgrade/downgrade detection
	const tierOrder: Record<string, number> = { free: 0, basic: 1, premium: 2 };

	// Feature display config — ordered list of features to show in comparison
	const featureDisplay: {
		key: string;
		label: string;
		format: 'count' | 'time' | 'boolean' | 'credits';
	}[] = [
		{ key: 'monthly_credits', label: 'Monthly credits', format: 'credits' },
		{ key: 'max_concurrent_tasks', label: 'Concurrent tasks', format: 'count' },
		{ key: 'use_custom_llm', label: 'Bring your own model', format: 'boolean' },
		{ key: 'use_custom_mcp', label: 'Custom MCP servers', format: 'boolean' },
		{ key: 'can_schedule_tasks', label: 'Task scheduling', format: 'boolean' },
		{ key: 'use_custom_e2b', label: 'Custom sandbox', format: 'boolean' }
	];

	function resolveFeatureValue(plan: SubscriptionPlan, key: string): unknown {
		// monthly_credits lives on the plan object, not inside features
		if (key === 'monthly_credits') return plan.monthly_credits;
		const raw = plan.features[key];
		return Array.isArray(raw) ? raw[0] : raw;
	}

	function formatFeatureValue(
		val: unknown,
		format: 'count' | 'time' | 'boolean' | 'credits'
	): string {
		if (format === 'boolean') return ''; // handled with icons
		if (format === 'credits') return Number(val).toLocaleString();
		if (format === 'time') {
			const secs = Number(val);
			if (secs >= 86400) return `${Math.floor(secs / 86400)}d`;
			if (secs >= 3600) return `${Math.floor(secs / 3600)}h`;
			if (secs >= 60) return `${Math.floor(secs / 60)}m`;
			return `${secs}s`;
		}
		return String(val);
	}

	function isFeatureTrue(val: unknown): boolean {
		return val === true || val === 'true';
	}

	function tierColor(tier: string): string {
		switch (tier) {
			case 'premium':
				return 'border-accent/20 bg-accent/[0.02]';
			case 'basic':
				return 'border-accent/20 bg-accent/[0.02]';
			default:
				return 'border-border bg-background';
		}
	}

	function tierAccent(tier: string): string {
		switch (tier) {
			case 'premium':
				return 'bg-accent text-white hover:bg-accent/90';
			case 'basic':
				return 'bg-accent text-white hover:bg-accent/90';
			default:
				return 'bg-surface-2 text-foreground hover:bg-surface-2';
		}
	}

	function tierBadgeVariant(tier: string): 'coral' | 'blue' | 'default' {
		switch (tier) {
			case 'premium':
				return 'coral';
			case 'basic':
				return 'blue';
			default:
				return 'default';
		}
	}

	// Plan icon path
	function tierIcon(tier: string): string {
		switch (tier) {
			case 'premium':
				return 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2';
			case 'basic':
				return 'M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5';
			default:
				return 'M12 2a10 10 0 100 20 10 10 0 000-20zM12 6v6l4 2';
		}
	}

	function getActionLabel(plan: SubscriptionPlan): string {
		if (!currentSubscription) return 'Get started';
		if (currentSubscription.plan.id === plan.id) return 'Current plan';
		const current = tierOrder[currentSubscription.plan.tier] ?? 0;
		const target = tierOrder[plan.tier] ?? 0;
		if (target > current) return 'Upgrade';
		return 'Downgrade';
	}

	function getActionType(plan: SubscriptionPlan): 'upgrade' | 'downgrade' | 'subscribe' {
		if (!currentSubscription) return 'subscribe';
		const current = tierOrder[currentSubscription.plan.tier] ?? 0;
		const target = tierOrder[plan.tier] ?? 0;
		if (target > current) return 'upgrade';
		return 'downgrade';
	}

	function computeDiscountedPrice(price: number): number {
		if (!promoDiscount) return price;
		if (promoDiscount.type === 'percentage') {
			return Math.max(0, price * (1 - promoDiscount.value / 100));
		}
		return Math.max(0, price - promoDiscount.value);
	}

	let promoValidating = $state(false);

	async function handleApplyPromo(): Promise<void> {
		promoError = '';
		if (!promoCode.trim()) {
			promoError = 'Enter a promo code.';
			return;
		}
		promoValidating = true;
		try {
			const result = await validatePromoCode(promoCode.trim());
			if (result.valid) {
				promoApplied = true;
				promoDiscount =
					result.discount_percent > 0
						? { type: 'percentage', value: result.discount_percent }
						: null;
				toasts.success(result.message);
			} else {
				promoError = result.message;
			}
		} catch {
			promoError = 'Failed to validate promo code. Please try again.';
		} finally {
			promoValidating = false;
		}
	}

	function clearPromo(): void {
		promoCode = '';
		promoApplied = false;
		promoDiscount = null;
		promoError = '';
	}

	function openConfirm(plan: SubscriptionPlan): void {
		confirmPlan = plan;
		confirmAction = getActionType(plan);
		confirmOpen = true;
	}

	async function handleConfirmAction(): Promise<void> {
		if (!confirmPlan) return;
		actionLoading = true;
		actionPlanId = confirmPlan.id;
		try {
			if (currentSubscription && currentSubscription.plan.id !== confirmPlan.id) {
				// Change plan
				const result = await changePlan(confirmPlan.id);
				toasts.success(result.message || 'Plan changed successfully.');
			} else {
				// New subscription
				const result = await createSubscription(confirmPlan.id);
				if (result.checkout_url) {
					// Redirect to Dodo Payments checkout
					window.location.href = result.checkout_url;
					return;
				}
				toasts.success('Subscription created.');
			}
			confirmOpen = false;
			// Redirect back to billing overview
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto('/billing');
		} catch {
			toasts.error('Something went wrong. Please try again.');
		} finally {
			actionLoading = false;
			actionPlanId = '';
		}
	}

	async function loadData(): Promise<void> {
		loading = true;
		error = '';
		try {
			const [plansResponse, sub] = await Promise.all([
				getSubscriptionPlans(),
				getUserSubscription().catch(() => null)
			]);
			plans = plansResponse.items;
			currentSubscription = sub;
		} catch {
			error = 'Unable to load plans.';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		loadData();
	});
</script>

<svelte:head>
	<title>Choose a Plan - Jatayu AI</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
	<!-- Header -->
	<div class="mb-8">
		<!-- eslint-disable svelte/no-navigation-without-resolve -->
		<a
			href="/billing"
			class="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-accent"
		>
			<svg
				class="h-3.5 w-3.5"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"><path d="M19 12H5m0 0l7 7m-7-7l7-7" /></svg
			>
			Back to Billing
		</a>
		<!-- eslint-enable svelte/no-navigation-without-resolve -->
		<PageHeader
			title="Choose a plan"
			description="Compare features and pick the plan that fits your workflow."
		/>
	</div>

	{#if loading}
		<!-- Loading skeleton -->
		<div class="grid gap-6 lg:grid-cols-3" out:fade={{ duration: 80 }}>
			{#each [0, 1, 2] as i (i)}
				<div class="rounded-2xl border border-border-subtle bg-background p-6">
					<div class="mb-4 flex items-center gap-3">
						<Skeleton class="h-10 w-10 rounded-xl" />
						<Skeleton class="h-5 w-28" />
					</div>
					<Skeleton class="mb-6 h-8 w-20" />
					<div class="space-y-3">
						{#each [0, 1, 2, 3, 4, 5] as j (j)}
							<Skeleton class="h-4 w-full" />
						{/each}
					</div>
					<Skeleton class="mt-6 h-11 w-full rounded-xl" />
				</div>
			{/each}
		</div>
	{:else if error}
		<!-- Error state -->
		<div class="rounded-2xl border border-accent/20 bg-accent/5 p-8 text-center">
			<div
				class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-accent/10 text-accent"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="24"
					height="24"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<circle cx="12" cy="12" r="10" />
					<path d="M12 8v4m0 4h.01" />
				</svg>
			</div>
			<p class="text-sm font-medium text-foreground">{error}</p>
			<button
				onclick={loadData}
				class="mt-4 rounded-xl bg-surface-2 px-4 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
			>
				Try again
			</button>
		</div>
	{:else}
		<!-- Plan cards -->
		<div class="grid gap-6 lg:grid-cols-3" in:fade={{ duration: 150, delay: 50 }}>
			{#each plans as plan, i (plan.id)}
				{@const isCurrent = currentSubscription?.plan.id === plan.id}
				{@const actionLabel = getActionLabel(plan)}
				{@const discountedPrice = computeDiscountedPrice(plan.price)}
				{@const hasDiscount = promoApplied && promoDiscount && discountedPrice < plan.price}
				<div
					class="card-hover relative flex flex-col rounded-2xl border-2 p-6 {isCurrent
						? 'ring-2 ring-success/40 '
						: ''}{tierColor(plan.tier)}"
					use:zenReveal={{ delay: i + 1 }}
				>
					{#if isCurrent}
						<div
							class="absolute -top-3 left-4 rounded-full bg-success px-3 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white"
						>
							Current
						</div>
					{/if}

					{#if plan.tier === 'premium'}
						<div
							class="absolute -top-3 right-4 rounded-full bg-accent px-3 py-0.5 text-[10px] font-medium uppercase tracking-wider text-white"
						>
							Popular
						</div>
					{/if}

					<!-- Plan icon + name -->
					<div class="mb-4 flex items-center gap-3">
						<div
							class="flex h-10 w-10 items-center justify-center rounded-xl {plan.tier === 'premium'
								? 'bg-accent/10 text-accent'
								: plan.tier === 'basic'
									? 'bg-accent/10 text-accent'
									: 'bg-surface-2 text-muted'}"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="20"
								height="20"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d={tierIcon(plan.tier)} />
							</svg>
						</div>
						<div class="flex items-center gap-2">
							<h2 class="text-lg font-normal text-foreground">{plan.name}</h2>
							<Badge variant={tierBadgeVariant(plan.tier)} class="text-[10px]">
								{plan.tier}
							</Badge>
						</div>
					</div>

					<!-- Price -->
					<div class="mb-6">
						{#if plan.price > 0}
							<div class="flex items-baseline gap-1">
								{#if hasDiscount}
									<span class="text-lg text-muted line-through">${plan.price}</span>
									<span class="text-3xl font-normal text-foreground"
										>${discountedPrice.toFixed(2)}</span
									>
								{:else}
									<span class="text-3xl font-normal text-foreground">${plan.price}</span>
								{/if}
								<span class="text-sm text-muted">/month</span>
							</div>
						{:else}
							<span class="text-3xl font-normal text-foreground">Free</span>
							<span class="ml-1 text-sm text-muted">forever</span>
						{/if}
					</div>

					<!-- Monthly credits -->
					{#if plan.monthly_credits}
						<div class="mb-4 rounded-xl bg-success/5 px-3 py-2.5 text-center">
							<span class="text-xl font-medium tabular-nums text-success">
								{plan.monthly_credits.toLocaleString()}
							</span>
							<span class="text-sm text-subtle"> credits/month</span>
						</div>
					{/if}

					<!-- Features list -->
					<div class="mb-6 flex-1 space-y-2.5">
						{#each featureDisplay as feat (feat.key)}
							{@const val = resolveFeatureValue(plan, feat.key)}
							<div class="flex items-center gap-2.5 text-sm">
								{#if feat.format === 'boolean'}
									{#if isFeatureTrue(val)}
										<div
											class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success/10"
										>
											<svg
												class="h-3 w-3 text-success"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="3"><path d="M5 13l4 4L19 7" /></svg
											>
										</div>
										<span class="text-foreground">{feat.label}</span>
									{:else}
										<div
											class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2"
										>
											<svg
												class="h-3 w-3 text-muted"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="2"><path d="M18 6L6 18M6 6l12 12" /></svg
											>
										</div>
										<span class="text-muted">{feat.label}</span>
									{/if}
								{:else}
									<div
										class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success/10"
									>
										<svg
											class="h-3 w-3 text-success"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="3"><path d="M5 13l4 4L19 7" /></svg
										>
									</div>
									<span class="text-foreground">
										{#if val === 0}
											No {feat.label.toLowerCase()}
										{:else}
											<span class="font-medium text-foreground"
												>{formatFeatureValue(val, feat.format)}</span
											>
											{feat.label.toLowerCase()}
										{/if}
									</span>
								{/if}
							</div>
						{/each}
					</div>

					<!-- CTA button -->
					<button
						onclick={() => {
							if (!isCurrent) openConfirm(plan);
						}}
						disabled={isCurrent || (actionLoading && actionPlanId === plan.id)}
						class="mt-auto w-full rounded-xl px-4 py-2.5 text-sm font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-40 {isCurrent
							? 'bg-surface-2 text-muted'
							: tierAccent(plan.tier)}"
					>
						{#if actionLoading && actionPlanId === plan.id}
							Processing...
						{:else}
							{actionLabel}
						{/if}
					</button>
				</div>
			{/each}
		</div>

		<!-- Add-on credits info -->
		<div class="mt-4 rounded-xl border border-border-subtle bg-background px-4 py-3 text-center">
			<p class="text-sm text-subtle">
				Need more credits? <span class="font-medium text-foreground">1,000 credits for $2.50</span> —
				add-on packs never expire.
			</p>
		</div>

		<!-- Promo code section -->
		<div
			class="mt-8 rounded-2xl border border-border-subtle bg-background p-6 transition-all duration-200 hover:border-border-strong hover:shadow-lg"
		>
			<div class="flex items-center gap-2.5">
				<div class="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-2 text-muted">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<line x1="19" y1="5" x2="5" y2="19" />
						<circle cx="6.5" cy="6.5" r="2.5" />
						<circle cx="17.5" cy="17.5" r="2.5" />
					</svg>
				</div>
				<h3 class="text-sm font-medium text-foreground">Have a promo code?</h3>
			</div>
			<div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-start">
				<div class="flex-1">
					<div class="flex gap-2">
						<input
							type="text"
							bind:value={promoCode}
							disabled={promoApplied}
							placeholder="Enter promo code"
							class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm text-foreground transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:outline-none focus:ring-1 focus:ring-[rgba(59,130,246,0.3)] disabled:opacity-50"
						/>
						{#if promoApplied}
							<button
								onclick={clearPromo}
								class="rounded-xl border border-border px-4 py-2.5 text-xs font-medium text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
							>
								Clear
							</button>
						{:else}
							<button
								onclick={handleApplyPromo}
								disabled={promoValidating}
								class="rounded-xl bg-surface-2 px-4 py-2.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-50"
							>
								{promoValidating ? 'Validating...' : 'Apply'}
							</button>
						{/if}
					</div>
					{#if promoError}
						<p class="mt-1.5 text-xs text-accent">{promoError}</p>
					{/if}
					{#if promoApplied}
						<p class="mt-1.5 text-xs text-success">
							Code "{promoCode}" applied.{promoDiscount ? ` ${promoDiscount.value}% discount.` : ''}
						</p>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>

<!-- Confirmation dialog -->
{#if confirmOpen && confirmPlan}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20"
		role="dialog"
		aria-modal="true"
		aria-label="{confirmAction === 'upgrade'
			? 'Upgrade'
			: confirmAction === 'downgrade'
				? 'Downgrade'
				: 'Subscribe to'} plan"
		tabindex="-1"
		onkeydown={(e) => {
			if (e.key === 'Escape') confirmOpen = false;
		}}
	>
		<div class="mx-4 w-full max-w-md rounded-2xl border border-border bg-background p-6 shadow-xl">
			<h3 class="text-lg font-normal text-foreground">
				{#if confirmAction === 'upgrade'}
					Upgrade to {confirmPlan.name}
				{:else if confirmAction === 'downgrade'}
					Downgrade to {confirmPlan.name}
				{:else}
					Subscribe to {confirmPlan.name}
				{/if}
			</h3>

			<p class="mt-2 text-sm text-subtle">
				{#if confirmAction === 'upgrade'}
					You'll be upgraded immediately. Your billing will be adjusted pro-rata.
				{:else if confirmAction === 'downgrade'}
					Your current plan will remain active until the end of your billing period, then switch to
					{confirmPlan.name}.
				{:else if confirmPlan.price > 0}
					You'll be redirected to complete payment of <span class="font-medium"
						>${confirmPlan.price}/month</span
					>.
				{:else}
					You'll be subscribed to the free plan immediately.
				{/if}
			</p>

			{#if promoApplied}
				<p class="mt-2 text-xs text-success">
					Promo code "{promoCode}" will be applied.
				</p>
			{/if}

			<div class="mt-5 flex justify-end gap-2">
				<button
					onclick={() => {
						confirmOpen = false;
					}}
					class="rounded-xl px-4 py-2.5 text-xs font-medium text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
				>
					Cancel
				</button>
				<button
					onclick={handleConfirmAction}
					disabled={actionLoading}
					class="rounded-xl px-4 py-2.5 text-xs font-medium text-white transition-all duration-200 disabled:opacity-50 {confirmAction ===
					'downgrade'
						? 'bg-foreground/70 hover:bg-foreground/60'
						: tierAccent(confirmPlan.tier)}"
				>
					{#if actionLoading}
						Processing...
					{:else if confirmAction === 'upgrade'}
						Confirm upgrade
					{:else if confirmAction === 'downgrade'}
						Confirm downgrade
					{:else}
						{confirmPlan.price > 0 ? 'Continue to payment' : 'Confirm'}
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
