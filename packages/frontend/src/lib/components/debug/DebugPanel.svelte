<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		debugPanelOpen,
		debugPanelWidth,
		debugPanelTab,
		setDebugPanelWidth,
		type DebugTab
	} from '$stores/debugPanel';
	import OverviewTab from './tabs/OverviewTab.svelte';
	import StreamTab from './tabs/StreamTab.svelte';
	import TransportTab from './tabs/TransportTab.svelte';
	import TokensTab from './tabs/TokensTab.svelte';
	import SandboxTab from './tabs/SandboxTab.svelte';
	import ContextTab from './tabs/ContextTab.svelte';
	import RalphTab from './tabs/RalphTab.svelte';
	import GuardsTab from './tabs/GuardsTab.svelte';

	let width = $state(380);
	let activeTab: DebugTab = $state('overview');

	const unsubWidth = debugPanelWidth.subscribe((v) => (width = v));
	const unsubTab = debugPanelTab.subscribe((v) => (activeTab = v));

	onDestroy(() => {
		unsubWidth();
		unsubTab();
	});

	const TABS: { id: DebugTab; label: string }[] = [
		{ id: 'overview', label: 'Overview' },
		{ id: 'stream', label: 'Stream' },
		{ id: 'transport', label: 'Transport' },
		{ id: 'tokens', label: 'Tokens' },
		{ id: 'sandbox', label: 'Sandbox' },
		{ id: 'context', label: 'Context' },
		{ id: 'ralph', label: 'Ralph' },
		{ id: 'guards', label: 'Guards' }
	];

	let dragging = $state(false);
	let dragStartX = 0;
	let dragStartWidth = 0;

	function onDragStart(e: PointerEvent): void {
		dragging = true;
		dragStartX = e.clientX;
		dragStartWidth = width;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onDragMove(e: PointerEvent): void {
		if (!dragging) return;
		const dx = dragStartX - e.clientX;
		setDebugPanelWidth(dragStartWidth + dx);
	}

	function onDragEnd(e: PointerEvent): void {
		dragging = false;
		try {
			(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
		} catch {
			// ignore
		}
	}

	function close(): void {
		debugPanelOpen.set(false);
	}
</script>

<aside
	class="relative flex shrink-0 flex-col border-l border-border bg-background"
	style="width: {width}px"
	aria-label="Debug panel"
>
	<button
		type="button"
		class="absolute bottom-0 left-0 top-0 z-10 w-1 -translate-x-1/2 cursor-col-resize bg-transparent hover:bg-border-strong"
		onpointerdown={onDragStart}
		onpointermove={onDragMove}
		onpointerup={onDragEnd}
		onpointercancel={onDragEnd}
		aria-label="Resize debug panel"
	></button>

	<header class="flex items-center gap-2 border-b border-border-subtle px-3 py-2">
		<span class="text-[12px] font-medium text-foreground">Debug</span>
		<span class="rounded-full bg-accent/15 px-1.5 py-0.5 font-mono text-[9px] uppercase text-accent"
			>dev</span
		>
		<button
			type="button"
			onclick={close}
			class="ml-auto rounded p-1 text-subtle hover:bg-surface-2 hover:text-foreground"
			aria-label="Close debug panel"
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
				<line x1="18" y1="6" x2="6" y2="18" />
				<line x1="6" y1="6" x2="18" y2="18" />
			</svg>
		</button>
	</header>

	<nav class="flex gap-0.5 overflow-x-auto border-b border-border-subtle bg-background px-2 py-1">
		{#each TABS as t (t.id)}
			{@const isActive = activeTab === t.id}
			<button
				type="button"
				onclick={() => debugPanelTab.set(t.id)}
				class="rounded px-2 py-1 text-[11px] font-medium transition-colors {isActive
					? 'bg-foreground text-background'
					: 'text-subtle hover:bg-surface-2 hover:text-foreground'}"
			>
				{t.label}
			</button>
		{/each}
	</nav>

	<div class="min-h-0 flex-1 overflow-auto">
		{#if activeTab === 'overview'}
			<OverviewTab />
		{:else if activeTab === 'stream'}
			<StreamTab />
		{:else if activeTab === 'transport'}
			<TransportTab />
		{:else if activeTab === 'tokens'}
			<TokensTab />
		{:else if activeTab === 'sandbox'}
			<SandboxTab />
		{:else if activeTab === 'context'}
			<ContextTab />
		{:else if activeTab === 'ralph'}
			<RalphTab />
		{:else if activeTab === 'guards'}
			<GuardsTab />
		{/if}
	</div>
</aside>
