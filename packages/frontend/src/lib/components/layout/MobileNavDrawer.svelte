<script lang="ts">
	import { page } from '$app/stores';
	import { openSettings } from '$stores/settings';
	import { haptic } from '$lib/actions/gestures';
	import { openSearch } from '$stores/search';
	import { mobileNavOpen, closeMobileNav } from '$stores/sidebar';
	import {
		groupedConversations,
		conversationsLoading,
		activeConversationId,
		favouriteIds,
		isFavourite,
		formatRelativeTime
	} from '$stores/conversations';
	import type { ConversationGroup } from '$stores/conversations';

	let open = $state(false);
	let currentPath = $state('/');
	let groups: ConversationGroup[] = $state([]);
	let loading = $state(false);
	let activeId = $state<string | null>(null);
	let favs = $state<Set<string>>(new Set());

	mobileNavOpen.subscribe((v) => (open = v));
	page.subscribe((p) => {
		currentPath = p.url.pathname;
		if (open) close();
	});
	groupedConversations.subscribe((v) => (groups = v));
	conversationsLoading.subscribe((v) => (loading = v));
	activeConversationId.subscribe((v) => (activeId = v));
	favouriteIds.subscribe((v) => (favs = v));

	export function openDrawer() {
		haptic();
		mobileNavOpen.set(true);
	}

	function close() {
		closeMobileNav();
	}

	function handleSettings() {
		close();
		openSettings();
	}

	function isActive(path: string): boolean {
		if (path === '/') return currentPath === '/';
		return currentPath.startsWith(path);
	}

	function handleSearch() {
		close();
		openSearch();
	}

	const navItems = [
		{ href: '/', label: 'New Task', icon: 'sparkle' },
		{ href: null, label: 'Search', icon: 'search', action: handleSearch },
		{ href: '/library', label: 'Library', icon: 'folder' },
		{ href: '/projects', label: 'Projects', icon: 'grid' }
	] as const;
</script>

{#if open}
	<div
		class="fixed inset-0 z-[999] flex flex-col bg-background lg:hidden"
		role="dialog"
		aria-modal="true"
		aria-label="Navigation"
	>
		<!-- Header -->
		<header
			class="flex h-[var(--header-height)] shrink-0 items-center justify-between px-2 pt-[env(safe-area-inset-top,0px)]"
		>
			<button
				onclick={close}
				class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-subtle active:bg-surface"
				aria-label="Close"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg
				>
			</button>
			<button
				onclick={handleSettings}
				class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-subtle active:bg-surface"
				aria-label="Settings"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					><path
						d="M12.22 2h-.44a2 2 0 00-2 2v.18a2 2 0 01-1 1.73l-.43.25a2 2 0 01-2 0l-.15-.08a2 2 0 00-2.73.73l-.22.38a2 2 0 00.73 2.73l.15.1a2 2 0 011 1.72v.51a2 2 0 01-1 1.74l-.15.09a2 2 0 00-.73 2.73l.22.38a2 2 0 002.73.73l.15-.08a2 2 0 012 0l.43.25a2 2 0 011 1.73V20a2 2 0 002 2h.44a2 2 0 002-2v-.18a2 2 0 011-1.73l.43-.25a2 2 0 012 0l.15.08a2 2 0 002.73-.73l.22-.39a2 2 0 00-.73-2.73l-.15-.08a2 2 0 01-1-1.74v-.5a2 2 0 011-1.74l.15-.09a2 2 0 00.73-2.73l-.22-.38a2 2 0 00-2.73-.73l-.15.08a2 2 0 01-2 0l-.43-.25a2 2 0 01-1-1.73V4a2 2 0 00-2-2z"
					/><circle cx="12" cy="12" r="3" /></svg
				>
			</button>
		</header>

		<!-- Scrollable content -->
		<div class="flex-1 overflow-y-auto">
			<!-- Navigation section -->
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			<div class="px-4 pt-5 pb-2">
				<h2 class="text-[13px] font-medium uppercase tracking-wider text-subtle">Navigate</h2>
			</div>
			<div class="grid grid-cols-2 gap-2 px-4 pb-6">
				{#each navItems as item (item.label)}
					{@const active = item.href ? isActive(item.href) : false}
					{#if item.href}
						<a
							href={item.href}
							class="flex items-center gap-2.5 rounded-2xl border px-4 py-3.5 transition-all duration-100
								{active
								? 'border-accent/20 bg-accent/[0.05] text-accent'
								: 'border-border-subtle bg-surface text-foreground active:border-border-strong active:bg-surface'}"
						>
							{#if item.icon === 'sparkle'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="18"
									height="18"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									><path
										d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"
									/><path d="M5 3v4" /><path d="M19 17v4" /><path d="M3 5h4" /><path
										d="M17 19h4"
									/></svg
								>
							{:else if item.icon === 'folder'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="18"
									height="18"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									><path
										d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"
									/></svg
								>
							{:else if item.icon === 'grid'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="18"
									height="18"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									><rect width="7" height="7" x="3" y="3" rx="1" /><rect
										width="7"
										height="7"
										x="14"
										y="3"
										rx="1"
									/><rect width="7" height="7" x="14" y="14" rx="1" /><rect
										width="7"
										height="7"
										x="3"
										y="14"
										rx="1"
									/></svg
								>
							{/if}
							<span class="text-[14px] font-medium">{item.label}</span>
						</a>
					{:else}
						<button
							onclick={item.action}
							class="flex items-center gap-2.5 rounded-2xl border px-4 py-3.5 transition-all duration-100 border-border-subtle bg-surface text-foreground active:border-border-strong active:bg-surface"
						>
							{#if item.icon === 'search'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="18"
									height="18"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></svg
								>
							{/if}
							<span class="text-[14px] font-medium">{item.label}</span>
						</button>
					{/if}
				{/each}
			</div>

			<!-- Conversations section -->
			<div class="px-4 pb-2">
				<h2 class="text-[13px] font-medium uppercase tracking-wider text-subtle">Conversations</h2>
			</div>

			<div class="px-4 pb-[env(safe-area-inset-bottom,16px)]">
				{#if loading && groups.length === 0}
					<div class="space-y-2">
						{#each [0, 1, 2, 3, 4] as i (i)}
							<div class="h-14 animate-pulse rounded-xl bg-surface"></div>
						{/each}
					</div>
				{:else if groups.length === 0}
					<div
						class="flex flex-col items-center gap-2 rounded-2xl border border-border-subtle bg-surface py-10"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="24"
							height="24"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-muted"
							><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg
						>
						<p class="text-[14px] text-muted">No conversations yet</p>
					</div>
				{:else}
					{#each groups as group (group.label)}
						<div class="mb-1">
							<p class="px-1 pb-1 pt-3 text-[12px] font-medium text-muted">{group.label}</p>
							{#each group.conversations as conv (conv.id)}
								{@const active = activeId === conv.id}
								<a
									href="/chat/{conv.id}"
									class="flex h-11 items-center gap-2 rounded-lg px-1 transition-colors duration-75
										{active ? 'bg-surface-2 text-foreground' : 'text-foreground active:bg-surface'}"
								>
									<span class="min-w-0 flex-1 truncate text-[14px] {active ? 'font-medium' : ''}">
										{conv.title || 'Untitled'}
									</span>
									{#if conv.status === 'running' || conv.status === 'queued' || conv.status === 'provisioning'}
										<span class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"></span>
									{/if}
									{#if isFavourite(conv.id, favs)}
										<span class="shrink-0 text-[10px]">⭐</span>
									{/if}
									<span class="shrink-0 text-[11px] text-muted"
										>{formatRelativeTime(conv.date_updated)}</span
									>
								</a>
							{/each}
						</div>
					{/each}
				{/if}
			</div>
			<!-- eslint-enable svelte/no-navigation-without-resolve -->
		</div>
	</div>
{/if}
