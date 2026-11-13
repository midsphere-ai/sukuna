<script lang="ts">
	import {
		sidebarHidden,
		sidebarMobileOpen,
		toggleSidebar,
		closeMobileSidebar
	} from '$stores/sidebar';
	import { openSettings, closeSettings, settingsOpen } from '$stores/settings';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { onMount, onDestroy } from 'svelte';
	import { browser } from '$app/environment';
	import EasterEgg from './EasterEgg.svelte';
	import {
		PanelLeft,
		Plus,
		Home,
		ListChecks,
		BookOpen,
		Plug,
		Layers,
		FileText,
		ChevronDown,
		ChevronRight,
		Settings,
		Search
	} from '@lucide/svelte';
	import { flagEnabled } from '$stores/featureFlags';
	import { openSearch } from '$stores/search';
	import { haptic } from '$lib/actions/gestures';
	import { isTauri } from '$utils/platform';
	import { tooltip } from '$lib/actions/tooltip';
	import { activeProjectId, setActiveProject, projects, ensureProjects } from '$stores/projects';
	import { ensureSubscription, subscription } from '$stores/subscription';
	import { creditBalance, ensureCreditBalance } from '$stores/credits';
	import { conversations } from '$stores/conversations';
	import type { Conversation, ProjectListItem, UserSubscription, CreditBalance } from '$api/types';
	import { Avatar } from '$components/ui';
	import { currentUser } from '$stores/auth';
	import { logout } from '$api/auth';

	let collapsed = $state(false);
	let mobileOpen = $state(false);
	let currentPath = $state('/');
	let activeProjId = $state<string | null>(null);

	// Feature flags (hide nav rows for disabled features instead of breaking them)
	const connectorsFlag = flagEnabled('enable-connectors');
	const skillsFlag = flagEnabled('enable-skills');
	const clawFlag = flagEnabled('enable-claw');
	let showConnectors = $state(true);
	let showSkills = $state(true);
	let showClaw = $state(true);
	connectorsFlag.subscribe((v) => {
		showConnectors = v;
	});
	skillsFlag.subscribe((v) => {
		showSkills = v;
	});
	clawFlag.subscribe((v) => {
		showClaw = v;
	});

	// Collapsible groups
	let projectsOpen = $state(
		browser ? localStorage.getItem('midsphere-sidebar-projects-open') !== 'false' : true
	);
	let historyOpen = $state(
		browser ? localStorage.getItem('midsphere-sidebar-history-open') !== 'false' : true
	);
	$effect(() => {
		if (browser) localStorage.setItem('midsphere-sidebar-projects-open', String(projectsOpen));
	});
	$effect(() => {
		if (browser) localStorage.setItem('midsphere-sidebar-history-open', String(historyOpen));
	});

	// Easter egg
	let easterEggOpen = $state(false);
	let logoClickCount = $state(0);
	let logoClickTimer: ReturnType<typeof setTimeout> | undefined;

	// Store subscriptions
	let userName = $state('');
	let userAvatar = $state('');
	let userEmail = $state('');
	let memberSince = $state('');
	let sub = $state<UserSubscription | null>(null);
	let balance = $state<CreditBalance | null>(null);
	let projectList = $state<ProjectListItem[]>([]);
	let recentConversations = $state<Conversation[]>([]);

	const unsubs = [
		sidebarHidden.subscribe((v) => (collapsed = v)),
		sidebarMobileOpen.subscribe((v) => (mobileOpen = v)),
		currentUser.subscribe((u) => {
			if (u) {
				userName = u.name || '';
				userAvatar = u.avatar || '';
				userEmail = u.email || '';
				memberSince = u.date_joined
					? new Date(u.date_joined).toLocaleDateString('en-US', {
							month: 'short',
							year: 'numeric'
						})
					: '';
			}
		}),
		subscription.subscribe((v) => (sub = v)),
		creditBalance.subscribe((v) => (balance = v)),
		projects.subscribe((v) => (projectList = v)),
		conversations.subscribe((v) => (recentConversations = v)),
		page.subscribe((p) => {
			currentPath = p.url.pathname;
			const projectMatch = p.url.pathname.match(/^\/projects\/([^/]+)/);
			setActiveProject(projectMatch ? projectMatch[1] : null);
		}),
		activeProjectId.subscribe((v) => (activeProjId = v))
	];

	onDestroy(() => {
		unsubs.forEach((u) => u());
		clearTimeout(logoClickTimer);
	});

	function handleLogoClick(): void {
		logoClickCount++;
		clearTimeout(logoClickTimer);
		if (logoClickCount >= 5) {
			easterEggOpen = true;
			logoClickCount = 0;
		} else {
			logoClickTimer = setTimeout(() => (logoClickCount = 0), 2000);
		}
	}

	// Touch swipe to close (mobile)
	let startX = 0;
	let isDragging = false;
	function handleTouchStart(e: TouchEvent): void {
		startX = e.touches[0].clientX;
		isDragging = true;
	}
	function handleTouchEnd(e: TouchEvent): void {
		if (!isDragging) return;
		isDragging = false;
		if (e.changedTouches[0].clientX - startX < -50) {
			haptic();
			closeMobileSidebar();
		}
	}

	onMount(() => {
		ensureSubscription();
		ensureCreditBalance();
		ensureProjects();

		/* eslint-disable svelte/no-navigation-without-resolve */
		function handleGlobalKeydown(e: KeyboardEvent): void {
			if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
			const key = e.code;
			if (e.altKey && key === 'KeyN') {
				e.preventDefault();
				goto('/');
			} else if (e.altKey && key === 'KeyB') {
				e.preventDefault();
				toggleSidebar();
			} else if (e.altKey && key === 'KeyS') {
				e.preventDefault();
				let isOpen = false;
				settingsOpen.subscribe((v) => (isOpen = v))();
				if (isOpen) closeSettings();
				else openSettings();
			} else if (e.altKey && e.shiftKey && key === 'KeyF') {
				e.preventDefault();
				goto('/flags');
			}
		}
		/* eslint-enable svelte/no-navigation-without-resolve */
		window.addEventListener('keydown', handleGlobalKeydown);
		return () => window.removeEventListener('keydown', handleGlobalKeydown);
	});

	function isActive(path: string, exact = false): boolean {
		if (exact) return currentPath === path;
		return currentPath === path || currentPath.startsWith(path + '/');
	}

	// ─── Task history grouping ───

	interface HistoryGroup {
		label: string;
		items: Conversation[];
	}

	function groupConversations(items: Conversation[]): HistoryGroup[] {
		const now = new Date();
		const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
		const yesterdayStart = new Date(todayStart);
		yesterdayStart.setDate(todayStart.getDate() - 1);
		const weekStart = new Date(todayStart);
		weekStart.setDate(todayStart.getDate() - 7);

		const today: Conversation[] = [];
		const yesterday: Conversation[] = [];
		const thisWeek: Conversation[] = [];
		const older: Conversation[] = [];

		for (const c of items) {
			const when = new Date(c.date_updated || c.date_created);
			if (when >= todayStart) today.push(c);
			else if (when >= yesterdayStart) yesterday.push(c);
			else if (when >= weekStart) thisWeek.push(c);
			else older.push(c);
		}

		const groups: HistoryGroup[] = [];
		if (today.length) groups.push({ label: 'Today', items: today });
		if (yesterday.length) groups.push({ label: 'Yesterday', items: yesterday });
		if (thisWeek.length) groups.push({ label: 'Earlier this week', items: thisWeek });
		if (older.length) groups.push({ label: 'Older', items: older });
		return groups;
	}

	let historyGroups = $derived(groupConversations(recentConversations.slice(0, 15)));

	function formatTimeShort(iso: string): string {
		const d = new Date(iso);
		const now = new Date();
		const isToday =
			d.getFullYear() === now.getFullYear() &&
			d.getMonth() === now.getMonth() &&
			d.getDate() === now.getDate();
		if (isToday) {
			return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
		}
		const sameYear = d.getFullYear() === now.getFullYear();
		return d.toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric',
			...(sameYear ? {} : { year: 'numeric' })
		});
	}

	// ─── Subscription / credits ───

	const planName = $derived(sub?.plan?.name ?? 'Free');
	const planTier = $derived(sub?.plan?.tier ?? 'free');
	const isPaidPlan = $derived(planTier !== 'free' && planName !== 'Free');

	const totalCredits = $derived(balance?.total_available ?? 0);
	const monthlyCredits = $derived(sub?.plan?.monthly_credits ?? balance?.monthly_credits ?? 0);
	const creditsUsedPct = $derived.by(() => {
		if (!monthlyCredits) return 0;
		const used = Math.max(0, monthlyCredits - totalCredits);
		return Math.min(100, Math.round((used / monthlyCredits) * 100));
	});
	const creditsRemainingPct = $derived(100 - creditsUsedPct);

	function formatCreditNumber(n: number): string {
		return n.toLocaleString();
	}

	const resetLabel = $derived.by(() => {
		if (!sub?.end_date) return 'Renews monthly';
		const end = new Date(sub.end_date);
		const now = new Date();
		const msPerDay = 24 * 60 * 60 * 1000;
		const days = Math.max(0, Math.ceil((end.getTime() - now.getTime()) / msPerDay));
		if (days <= 0) return 'Renews today';
		if (days === 1) return 'Resets in 1 day';
		return `Resets in ${days} days`;
	});

	// ─── Nav items ───

	interface NavItem {
		label: string;
		href: string;
		icon: typeof Home;
		exact?: boolean;
		visible?: boolean;
	}

	const primaryNav: NavItem[] = $derived([
		{ label: 'Home', href: '/', icon: Home, exact: true },
		{ label: 'Tasks', href: '/tasks', icon: ListChecks },
		{ label: 'Knowledge', href: '/skills', icon: BookOpen, visible: showSkills },
		{ label: 'Connections', href: '/connectors', icon: Plug, visible: showConnectors }
	]);

	// ─── Handlers ───

	function goHome(): void {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto('/');
		closeMobileSidebar();
	}

	// Logout + user menu moved to the header avatar; sidebar footer only shows
	// credits + settings now.
</script>

<!-- Mobile backdrop -->
{#if mobileOpen}
	<div
		class="fixed inset-0 z-40 bg-background/60 backdrop-blur-sm transition-opacity duration-200 lg:hidden"
		onclick={closeMobileSidebar}
		onkeydown={(e) => e.key === 'Escape' && closeMobileSidebar()}
		role="presentation"
	></div>
{/if}

<!-- ═══════════════════════════════════════════════════════
     COLLAPSED icon rail (desktop only)
     ═══════════════════════════════════════════════════════ -->
{#if collapsed}
	<aside
		class="hidden h-full w-12 shrink-0 flex-col items-center gap-1 border-r border-border bg-background py-3 lg:flex"
		aria-label="Sidebar navigation (collapsed)"
	>
		<!-- Expand button -->
		<button
			onclick={toggleSidebar}
			class="icon-rail-btn"
			aria-label="Expand sidebar"
			use:tooltip={{ text: 'Expand sidebar', position: 'right', shortcut: 'Alt+B' }}
		>
			<PanelLeft class="h-4 w-4" />
		</button>

		<!-- eslint-disable svelte/no-navigation-without-resolve -->
		<a
			href="/"
			class="icon-rail-btn {isActive('/', true) ? 'is-active' : ''}"
			aria-label="Home"
			use:tooltip={{ text: 'Home', position: 'right', shortcut: 'Alt+N' }}
		>
			<Home class="h-4 w-4" />
		</a>
		{#each primaryNav.slice(1) as item}
			{#if item.visible !== false}
				{@const Icon = item.icon}
				<a
					href={item.href}
					class="icon-rail-btn {isActive(item.href, item.exact) ? 'is-active' : ''}"
					aria-label={item.label}
					use:tooltip={{ text: item.label, position: 'right' }}
				>
					<Icon class="h-4 w-4" />
				</a>
			{/if}
		{/each}
		<!-- eslint-enable svelte/no-navigation-without-resolve -->

		<div class="flex-1"></div>

		<Avatar src={userAvatar || null} name={userName} size="xs" class="!text-[11px]" />
	</aside>
{/if}

<!-- ═══════════════════════════════════════════════════════
     EXPANDED sidebar
     ═══════════════════════════════════════════════════════ -->
<aside
	class="
		fixed top-0 left-0 z-50 flex h-full w-[268px] flex-col border-r border-border bg-background transition-transform duration-200 ease-out
	"
	class:max-lg:-translate-x-full={!mobileOpen}
	class:max-lg:translate-x-0={mobileOpen}
	class:lg:relative={!collapsed}
	class:lg:translate-x-0={!collapsed}
	class:lg:hidden={collapsed}
	ontouchstart={handleTouchStart}
	ontouchend={handleTouchEnd}
	aria-label="Sidebar navigation"
>
	<!-- ── Brand + collapse ── -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="flex h-12 shrink-0 items-center justify-between px-4"
		data-tauri-drag-region={isTauri() ? '' : undefined}
	>
		<button
			type="button"
			onclick={handleLogoClick}
			class="flex items-center gap-2 text-foreground transition-opacity hover:opacity-80"
			aria-label="Jatayu AI"
		>
			<!-- Mark: Simple X/asterisk-style monochrome glyph that fits the monochrome aesthetic. -->
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="22"
				height="22"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				stroke-linecap="round"
				stroke-linejoin="round"
				aria-hidden="true"
			>
				<path d="M4 4 L20 20" />
				<path d="M20 4 L4 20" />
				<path d="M12 2 V22" />
				<path d="M2 12 H22" />
			</svg>
			<span class="text-[13px] font-medium tracking-[0.02em]">JATAYU AI</span>
		</button>

		<div class="flex items-center gap-1">
			<button
				onclick={openSearch}
				class="sidebar-icon-btn hidden lg:flex"
				aria-label="Search"
				use:tooltip={{ text: 'Search', shortcut: '⌘K' }}
			>
				<Search class="h-4 w-4" />
			</button>
			<!-- One button that collapses on desktop, closes the drawer on mobile. -->
			<button
				onclick={() => {
					closeMobileSidebar();
					toggleSidebar();
				}}
				class="sidebar-icon-btn"
				aria-label="Collapse sidebar"
				use:tooltip={{ text: 'Collapse sidebar', shortcut: 'Alt+B' }}
			>
				<PanelLeft class="h-4 w-4" />
			</button>
		</div>
	</div>

	<!-- ── New task CTA — same 36 px rhythm as nav rows. ── -->
	<div class="px-3 pb-2">
		<button
			onclick={goHome}
			class="flex h-8 w-full items-center justify-between rounded-[6px] border border-border bg-background px-2.5 text-[13px] text-foreground transition-colors hover:bg-surface"
		>
			<span class="flex items-center gap-2.5">
				<Plus class="h-4 w-4 text-muted" strokeWidth={1.5} />
				<span>New task</span>
			</span>
			<kbd class="rounded bg-surface-2 px-1 py-px font-mono text-[10px] text-subtle">⌘K</kbd>
		</button>
	</div>

	<!-- eslint-disable svelte/no-navigation-without-resolve -->

	<!-- Scrollable middle ── primary nav + projects + history -->
	<div class="flex min-h-0 flex-1 flex-col overflow-y-auto px-3 pt-1 pb-2">
		<!-- ── Primary navigation ── -->
		<nav aria-label="Primary navigation" class="flex flex-col gap-0.5 px-1">
			{#each primaryNav as item (item.href)}
				{#if item.visible !== false}
					{@const Icon = item.icon}
					{@const active = isActive(item.href, item.exact)}
					<a
						href={item.href}
						onclick={closeMobileSidebar}
						class="nav-row {active ? 'is-active' : ''}"
						aria-current={active ? 'page' : undefined}
					>
						<Icon
							class="h-4 w-4 flex-shrink-0 {active ? 'text-foreground' : 'text-muted'}"
							strokeWidth={1.5}
						/>
						<span>{item.label}</span>
					</a>
				{/if}
			{/each}
		</nav>

		<!-- ── PROJECTS ── -->
		<div class="mt-5">
			<button
				type="button"
				onclick={() => (projectsOpen = !projectsOpen)}
				class="group flex w-full items-center justify-between px-2.5 pb-1"
			>
				<span class="sidebar-group-label">PROJECTS</span>
				{#if projectsOpen}
					<ChevronDown
						class="h-3 w-3 text-subtle opacity-0 transition-opacity group-hover:opacity-100"
					/>
				{:else}
					<ChevronRight
						class="h-3 w-3 text-subtle opacity-0 transition-opacity group-hover:opacity-100"
					/>
				{/if}
			</button>
			{#if projectsOpen}
				<div class="flex flex-col gap-0.5">
					{#each projectList.slice(0, 6) as project (project.id)}
						{@const active = currentPath.startsWith(`/projects/${project.id}`)}
						<a
							href="/projects/{project.id}"
							onclick={closeMobileSidebar}
							class="nav-row {active ? 'is-active' : ''}"
						>
							<Layers
								class="h-4 w-4 flex-shrink-0 {active ? 'text-foreground' : 'text-muted'}"
								strokeWidth={1.5}
							/>
							<span class="truncate">{project.title}</span>
						</a>
					{/each}
					<a href="/projects/new" onclick={closeMobileSidebar} class="nav-row group">
						<Plus class="h-4 w-4 text-muted" />
						<span>New Space</span>
						<Plus
							class="ml-auto h-3 w-3 text-subtle opacity-0 transition-opacity group-hover:opacity-100"
						/>
					</a>
				</div>
			{/if}
		</div>

		<!-- ── TASK HISTORY ── -->
		<div class="mt-5">
			<button
				type="button"
				onclick={() => (historyOpen = !historyOpen)}
				class="sidebar-group-label flex w-full px-2.5 pb-1 hover:text-muted"
			>
				TASK HISTORY
			</button>
			{#if historyOpen}
				{#if historyGroups.length === 0}
					<p class="px-2.5 py-2 text-[12px] text-subtle">No tasks yet</p>
				{:else}
					{#each historyGroups as group (group.label)}
						<p class="mt-2 mb-0.5 px-2.5 text-[10.5px] text-subtle">{group.label}</p>
						<div class="flex flex-col">
							{#each group.items as conv (conv.id)}
								{@const active = currentPath === `/chat/${conv.id}`}
								<a
									href="/chat/{conv.id}"
									onclick={closeMobileSidebar}
									class="history-row {active ? 'is-active' : ''}"
								>
									<FileText class="h-3.5 w-3.5 flex-shrink-0 text-subtle" />
									<span class="min-w-0 flex-1 truncate">{conv.title || 'Untitled'}</span>
									<span class="flex-shrink-0 text-[11px] text-subtle">
										{formatTimeShort(conv.date_updated || conv.date_created)}
									</span>
								</a>
							{/each}
						</div>
					{/each}
				{/if}
			{/if}
		</div>
	</div>

	<!-- ── Footer: credits + settings ── -->
	<div class="shrink-0">
		<!-- Credits card -->
		{#if monthlyCredits > 0}
			<div class="mx-3 mt-3 mb-2 rounded-[6px] border border-border bg-surface px-3.5 py-3">
				<div class="flex items-baseline justify-between gap-2">
					<span class="text-[11px] text-subtle">Credits</span>
					<span class="text-[11px] text-subtle">{resetLabel}</span>
				</div>
				<div class="mt-1.5 flex items-baseline gap-1.5">
					<span class="text-[16px] font-medium leading-none text-foreground">
						{formatCreditNumber(totalCredits)}
					</span>
					<span class="text-[11px] text-subtle">
						/ {formatCreditNumber(monthlyCredits)}
					</span>
				</div>
				<div class="mt-2.5 h-[3px] w-full overflow-hidden rounded-full bg-surface-2">
					<div
						class="h-full rounded-full bg-foreground transition-all duration-300"
						style="width: {creditsRemainingPct}%"
					></div>
				</div>
			</div>
		{/if}

		<!-- Settings row -->
		<button
			type="button"
			onclick={() => {
				openSettings();
				closeMobileSidebar();
			}}
			class="flex w-full items-center justify-between px-4 py-1.5 text-[13px] text-muted transition-colors hover:bg-surface hover:text-foreground"
		>
			<span class="flex items-center gap-2">
				<Settings class="h-4 w-4" strokeWidth={1.5} />
				Settings
			</span>
			<ChevronRight class="h-3 w-3 text-subtle" strokeWidth={1.5} />
		</button>
	</div>
	<!-- eslint-enable svelte/no-navigation-without-resolve -->
</aside>

<EasterEgg bind:open={easterEggOpen} />

<style>
	/* Primary nav row. Reference-matched: uniform 36 px height, filled
	   rounded background for the active state (no left accent bar so the
	   visual rhythm stays even), consistent 12 px horizontal padding. */
	:global(.nav-row) {
		display: flex;
		align-items: center;
		gap: 10px;
		border-radius: 6px;
		padding: 0 10px;
		height: 30px;
		font-size: 13px;
		line-height: 1;
		color: var(--text-secondary);
		transition:
			background 160ms ease-in-out,
			color 160ms ease-in-out;
		width: 100%;
	}
	:global(.nav-row:hover) {
		background: var(--surface);
		color: var(--text-primary);
	}
	:global(.nav-row.is-active) {
		background: var(--surface-2);
		color: var(--text-primary);
	}
	@media (max-width: 767px) {
		:global(.nav-row) {
			min-height: 40px;
			padding: 9px 10px;
		}
	}

	/* Task history row — uniform 28 px tile, tighter than primary nav.
	   Title truncates, timestamp hugs right in tertiary colour. */
	:global(.history-row) {
		display: flex;
		align-items: center;
		gap: 8px;
		border-radius: 4px;
		padding: 0 10px;
		height: 26px;
		font-size: 12px;
		line-height: 1;
		color: var(--text-secondary);
		transition:
			background 160ms ease-in-out,
			color 160ms ease-in-out;
		width: 100%;
	}
	:global(.history-row:hover) {
		background: var(--surface);
		color: var(--text-primary);
	}
	:global(.history-row.is-active) {
		background: var(--surface-2);
		color: var(--text-primary);
	}

	/* Section label (PROJECTS / TASK HISTORY) — small uppercase, tertiary,
	   generous tracking to read as a label rather than a heading. */
	:global(.sidebar-group-label) {
		font-size: 10px;
		font-weight: 500;
		letter-spacing: 0.1em;
		color: var(--text-tertiary);
		text-transform: uppercase;
	}

	/* Icon buttons in sidebar header + icon rail */
	:global(.sidebar-icon-btn) {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 6px;
		color: var(--text-secondary);
		transition:
			background 120ms ease-out,
			color 120ms ease-out;
	}
	:global(.sidebar-icon-btn:hover) {
		background: var(--surface);
		color: var(--text-primary);
	}

	:global(.icon-rail-btn) {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 34px;
		height: 34px;
		border-radius: 8px;
		color: var(--text-secondary);
		transition:
			background 120ms ease-out,
			color 120ms ease-out;
	}
	:global(.icon-rail-btn:hover) {
		background: var(--surface);
		color: var(--text-primary);
	}
	:global(.icon-rail-btn.is-active) {
		background: var(--surface-2);
		color: var(--text-primary);
	}
</style>
