<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Badge, Skeleton, Dialog, LoadingSpinner } from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import {
		getAddonDetail,
		registerAddon,
		unregisterAddon,
		getAddonAuthLink,
		checkAddonAuthStatus
	} from '$api/addons';
	import type { MarketplaceAddon, UserAddon } from '$api/types';
	import type { ApiError } from '$api/types';

	// Route param
	let addonId = $derived(page.params.id ?? '');

	// State
	let addon: MarketplaceAddon | null = $state(null);
	let userAddon: UserAddon | null = $state(null);
	let features: Record<string, unknown>[] = $state([]);
	let loading = $state(true);
	let installing = $state(false);
	let uninstalling = $state(false);
	let authorizing = $state(false);
	let checkingAuth = $state(false);
	let refreshingAuth = $state(false);
	let showUninstallDialog = $state(false);
	let showAllTools = $state(false);

	// Derived states
	let isInstalled = $derived(userAddon !== null);
	let isAuthorized = $derived.by(() => {
		return userAddon !== null && userAddon.auth_complete === true;
	});

	let visibleFeatures = $derived.by(() => {
		if (showAllTools || features.length <= 5) return features;
		return features.slice(0, 5);
	});

	async function loadAddon(): Promise<void> {
		loading = true;
		try {
			const res = await getAddonDetail(addonId);
			addon = res.marketplace_addon;
			userAddon = res.user_addon;
			features = res.features;
			if (addon) {
				pageTitle.set(addon.name);
			}
		} catch {
			toasts.error('Failed to load connector details');
		} finally {
			loading = false;
		}
	}

	async function handleInstall(): Promise<void> {
		if (!addon) return;
		installing = true;
		try {
			const res = await registerAddon(addon.id);
			toasts.success(`${addon.name} installed successfully`);
			// Reload to get fresh user_addon data
			const detail = await getAddonDetail(addonId);
			userAddon = detail.user_addon;
			features = detail.features;
			// If registerAddon didn't return a new ID but we still need to track it
			if (!userAddon && res.user_addon_id) {
				userAddon = {
					id: res.user_addon_id,
					enabled_addon: addon,
					auth_complete: false,
					config_id: null,
					auth_link: null,
					auth_link_created_at: null
				};
			}
		} catch (err) {
			const apiErr = err as ApiError;
			if (apiErr.status === 400) {
				toasts.error(apiErr.message || 'Addon limit reached. Upgrade your plan to install more.');
			} else {
				toasts.error(`Failed to install ${addon.name}`);
			}
		} finally {
			installing = false;
		}
	}

	async function handleUninstall(): Promise<void> {
		if (!userAddon || !addon) return;
		uninstalling = true;
		try {
			await unregisterAddon(userAddon.id);
			toasts.success(`${addon.name} uninstalled`);
			userAddon = null;
			showUninstallDialog = false;
		} catch {
			toasts.error('Failed to uninstall connector');
		} finally {
			uninstalling = false;
		}
	}

	async function handleAuthorize(): Promise<void> {
		if (!userAddon) return;
		authorizing = true;
		try {
			const res = await getAddonAuthLink(userAddon.id);
			if (res.auth_link) {
				window.open(res.auth_link, '_blank', 'noopener,noreferrer');
				toasts.info('Complete authorization in the new tab, then check the status below.');
			}
		} catch {
			toasts.error('Failed to get authorization link');
		} finally {
			authorizing = false;
		}
	}

	async function handleCheckAuth(): Promise<void> {
		if (!userAddon) return;
		checkingAuth = true;
		try {
			const res = await checkAddonAuthStatus(userAddon.id);
			if (res.is_authorised) {
				userAddon = { ...userAddon, auth_complete: true };
				toasts.success(`${addon?.name} is connected!`);
			} else {
				toasts.warning('Not yet authorized. Complete the OAuth flow first.');
			}
		} catch {
			toasts.error('Failed to check authorization status');
		} finally {
			checkingAuth = false;
		}
	}

	async function handleRefreshAuth(): Promise<void> {
		if (!userAddon) return;
		refreshingAuth = true;
		try {
			const res = await getAddonAuthLink(userAddon.id);
			if (res.auth_link) {
				userAddon = { ...userAddon, auth_complete: false };
				window.open(res.auth_link, '_blank', 'noopener,noreferrer');
				toasts.info(
					'A new authorization link has been opened. Complete the flow and check the status.'
				);
			}
		} catch {
			toasts.error('Failed to refresh authorization link');
		} finally {
			refreshingAuth = false;
		}
	}

	function handleBack(): void {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto('/connectors');
	}

	onMount(() => {
		pageTitle.set('Connector');
		showHeaderTitle.set(false);
		loadAddon();
	});
</script>

<svelte:head>
	<title>{addon?.name ?? 'Connector'} - Jatayu AI</title>
</svelte:head>

<div class="mx-auto flex w-full max-w-4xl flex-col px-4 pt-16 pb-6 sm:px-6 lg:px-8">
	<!-- Back -->
	<button
		onclick={handleBack}
		class="mb-8 flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-foreground"
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
			<path d="M19 12H5" /><polyline points="12 19 5 12 12 5" />
		</svg>
		Connectors
	</button>

	{#if loading}
		<div class="flex items-center gap-4">
			<Skeleton class="shrink-0 rounded-xl" width="48px" height="48px" />
			<div class="flex-1">
				<Skeleton class="rounded" width="30%" height="20px" stagger={1} />
				<div class="mt-2"><Skeleton class="rounded" width="50%" height="13px" stagger={2} /></div>
			</div>
		</div>
		<div class="mt-8 border-t border-border-subtle pt-6">
			<Skeleton class="rounded" width="100%" height="60px" stagger={3} />
		</div>
	{:else if !addon}
		<div class="flex flex-col items-center justify-center py-16 text-center">
			<p class="text-sm text-muted">This connector doesn't exist or was removed.</p>
			<button
				onclick={handleBack}
				class="mt-3 text-sm font-medium text-subtle hover:text-foreground">Browse Connectors</button
			>
		</div>
	{:else}
		<!-- Header -->
		<div class="flex items-start gap-4">
			<div
				class="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border-subtle bg-surface"
			>
				{#if addon.logo}
					<img
						src={addon.logo}
						alt={addon.name}
						class="h-full w-full object-contain p-1.5"
						onerror={(e) => {
							const target = e.currentTarget as HTMLImageElement;
							target.style.display = 'none';
							if (target.nextElementSibling)
								(target.nextElementSibling as HTMLElement).style.display = 'flex';
						}}
					/>
					<div
						class="hidden h-full w-full items-center justify-center text-lg font-normal text-muted"
					>
						{addon.name.charAt(0)}
					</div>
				{:else}
					<span class="text-lg font-normal text-muted">{addon.name.charAt(0)}</span>
				{/if}
			</div>

			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-2.5">
					<h1 class="text-2xl font-normal tracking-tight text-foreground">{addon.name}</h1>
					{#if isAuthorized}
						<Badge variant="green">Connected</Badge>
					{:else if isInstalled}
						<Badge variant="warning">Needs Auth</Badge>
					{/if}
				</div>
				<div class="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted">
					<span class="font-medium text-subtle">Free</span>
					{#if addon.enum}
						<span>by {addon.enum}</span>
					{/if}
					{#if addon.tags.length > 0}
						{#each addon.tags as tag (tag)}
							<span>{tag}</span>
						{/each}
					{/if}
					{#if features.length > 0}
						<span>{features.length} tools</span>
					{/if}
					{#if addon.link}
						<!-- eslint-disable svelte/no-navigation-without-resolve -->
						<a
							href={addon.link}
							target="_blank"
							rel="noopener noreferrer"
							class="flex items-center gap-1 transition-colors hover:text-subtle"
						>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="11"
								height="11"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline
									points="15 3 21 3 21 9"
								/><line x1="10" y1="14" x2="21" y2="3" />
							</svg>
							Website
						</a>
					{/if}
				</div>
			</div>
		</div>

		<!-- Actions -->
		<div class="mt-5 flex flex-wrap items-center gap-2.5">
			{#if !isInstalled}
				<button
					onclick={handleInstall}
					disabled={installing}
					class="inline-flex h-9 items-center gap-2 rounded-xl bg-foreground px-4 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
				>
					{#if installing}
						<LoadingSpinner />Installing...
					{:else}
						Install
					{/if}
				</button>
			{:else}
				{#if !isAuthorized}
					<button
						onclick={handleAuthorize}
						disabled={authorizing}
						class="inline-flex h-9 items-center gap-2 rounded-xl bg-foreground px-4 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
					>
						{#if authorizing}
							<LoadingSpinner />Opening...
						{:else}
							Authorise
						{/if}
					</button>
					<button
						onclick={handleCheckAuth}
						disabled={checkingAuth}
						class="inline-flex h-9 items-center gap-2 rounded-xl border border-border px-3.5 text-sm font-medium text-foreground transition-colors hover:border-border-strong disabled:opacity-50"
					>
						{#if checkingAuth}
							<LoadingSpinner />Checking...
						{:else}
							Check Status
						{/if}
					</button>
				{/if}
				<button
					onclick={handleRefreshAuth}
					disabled={refreshingAuth}
					class="inline-flex h-9 items-center gap-2 rounded-xl border border-border px-3.5 text-sm font-medium text-foreground transition-colors hover:border-border-strong disabled:opacity-50"
				>
					{#if refreshingAuth}
						<LoadingSpinner />Refreshing...
					{:else}
						Refresh Auth
					{/if}
				</button>
				<button
					onclick={() => (showUninstallDialog = true)}
					class="ml-auto text-xs font-medium text-muted transition-colors hover:text-red-600"
				>
					Uninstall
				</button>
			{/if}
		</div>

		<!-- Auth guidance -->
		{#if isInstalled && !isAuthorized}
			<div class="mt-5 flex flex-col gap-2 text-sm text-subtle">
				<div class="flex items-start gap-2.5">
					<span
						class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[10px] font-medium text-subtle"
						>1</span
					>
					<span
						>Click <strong class="text-foreground">Authorise</strong> above to open {addon.name}'s
						permission page.</span
					>
				</div>
				<div class="flex items-start gap-2.5">
					<span
						class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[10px] font-medium text-subtle"
						>2</span
					>
					<span>Grant the requested permissions in the tab that opens.</span>
				</div>
				<div class="flex items-start gap-2.5">
					<span
						class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[10px] font-medium text-subtle"
						>3</span
					>
					<span
						>Come back and click <strong class="text-foreground">Check Status</strong> to verify the connection.</span
					>
				</div>
			</div>
		{/if}

		<!-- Connected -->
		{#if isAuthorized}
			<div class="mt-5 flex items-start gap-2.5 text-sm text-subtle">
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
					class="mt-0.5 shrink-0 text-success"
				>
					<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
				</svg>
				<span
					><strong class="text-foreground">{addon.name}</strong> is connected. Your agent will automatically
					use its tools when relevant during conversations.</span
				>
			</div>
		{/if}

		<!-- About -->
		{#if addon.description}
			<div class="mt-8 border-t border-border-subtle pt-6">
				<h2 class="text-[11px] font-medium tracking-wide text-muted uppercase">About</h2>
				<p class="mt-2 text-sm leading-relaxed text-subtle">{addon.description}</p>
			</div>
		{/if}

		<!-- Tools -->
		{#if features.length > 0}
			<div class="mt-8 border-t border-border-subtle pt-6">
				<div class="flex items-center justify-between">
					<h2 class="text-[11px] font-medium tracking-wide text-muted uppercase">
						Tools <span class="font-normal text-muted">({features.length})</span>
					</h2>
					{#if features.length > 5}
						<button
							onclick={() => (showAllTools = !showAllTools)}
							class="text-xs font-medium text-muted transition-colors hover:text-foreground"
						>
							{showAllTools ? 'Show less' : `Show all`}
						</button>
					{/if}
				</div>
				<div class="mt-3 flex flex-col">
					{#each visibleFeatures as feature, i (i)}
						<div class="flex items-start gap-3 border-b border-border-subtle py-2.5 last:border-0">
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
								class="mt-0.5 shrink-0 text-muted"
							>
								<path
									d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
								/>
							</svg>
							<div class="min-w-0 flex-1">
								<span class="text-sm font-medium text-foreground">
									{typeof feature.name === 'string'
										? feature.name
										: typeof feature.display_name === 'string'
											? feature.display_name
											: `Tool ${i + 1}`}
								</span>
								{#if typeof feature.description === 'string' && feature.description}
									<p class="mt-0.5 text-xs text-muted">{feature.description}</p>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
</div>

<!-- Uninstall confirmation dialog -->
<Dialog bind:open={showUninstallDialog}>
	<div class="p-6">
		<div class="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-red-50">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="text-red-600"
			>
				<polyline points="3 6 5 6 21 6" />
				<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
			</svg>
		</div>
		<h2 class="text-lg font-normal text-foreground">Uninstall {addon?.name ?? 'Connector'}?</h2>
		<p class="mt-2 text-sm text-subtle">
			This will remove the connector and revoke its authorization. You can reinstall it later from
			the marketplace.
		</p>
		<div class="mt-6 flex justify-end gap-2.5">
			<button
				onclick={() => (showUninstallDialog = false)}
				class="h-9 rounded-xl border border-border px-3.5 text-sm font-medium text-foreground transition-colors hover:border-border-strong"
				>Cancel</button
			>
			<button
				onclick={handleUninstall}
				disabled={uninstalling}
				class="h-9 rounded-xl bg-red-600 px-4 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
			>
				{uninstalling ? 'Uninstalling...' : 'Uninstall'}
			</button>
		</div>
	</div>
</Dialog>
