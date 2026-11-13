<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import ComputerPanel from './ComputerPanel.svelte';
	import { computerPanelMobileOpen, closeComputerPanelMobile } from '$stores/computerPanel';

	type DrawerState = 'peek' | 'half' | 'full';

	type Props = {
		toolCalls: ToolCallMessage[];
		agentName?: string;
		vncAvailable?: boolean;
		vncUrl?: string;
		onVncToggle?: () => void;
	};

	let {
		toolCalls,
		agentName = 'Agent',
		vncAvailable = false,
		vncUrl = '',
		onVncToggle
	}: Props = $props();

	let isOpen = $state(false);
	let drawerState: DrawerState = $state('half');
	let startY = 0;
	let isDragging = false;
	let currentTranslateY = $state(0);

	const stateHeights: Record<DrawerState, string> = {
		peek: '25vh',
		half: '55vh',
		full: '92vh'
	};

	const stateOrder: DrawerState[] = ['peek', 'half', 'full'];

	const unsub = computerPanelMobileOpen.subscribe((v) => {
		isOpen = v;
		if (v) {
			drawerState = 'half';
			currentTranslateY = 0;
		}
	});

	import { onDestroy } from 'svelte';
	onDestroy(() => unsub());

	function close(): void {
		closeComputerPanelMobile();
	}

	function handleTouchStart(e: TouchEvent): void {
		startY = e.touches[0].clientY;
		isDragging = true;
		currentTranslateY = 0;
	}

	function handleTouchMove(e: TouchEvent): void {
		if (!isDragging) return;
		const diff = e.touches[0].clientY - startY;
		// Only allow downward drag (positive diff) or limited upward
		currentTranslateY = Math.max(-30, diff);
	}

	function handleTouchEnd(e: TouchEvent): void {
		if (!isDragging) return;
		isDragging = false;
		currentTranslateY = 0;

		const endY = e.changedTouches[0].clientY;
		const diff = endY - startY;
		const threshold = 50;

		if (diff > threshold) {
			const currentIdx = stateOrder.indexOf(drawerState);
			if (currentIdx <= 0) {
				close();
			} else {
				drawerState = stateOrder[currentIdx - 1];
			}
		} else if (diff < -threshold) {
			const currentIdx = stateOrder.indexOf(drawerState);
			if (currentIdx < stateOrder.length - 1) {
				drawerState = stateOrder[currentIdx + 1];
			}
		}
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') close();
	}
</script>

{#if isOpen}
	<!-- Backdrop -->
	<div
		class="fixed inset-0 z-[9998] bg-foreground/30 transition-opacity duration-300"
		onclick={close}
		onkeydown={handleKeydown}
		role="presentation"
	></div>

	<!-- Drawer -->
	<div
		class="fixed inset-x-0 bottom-0 z-[9999] flex flex-col overflow-hidden rounded-t-2xl border-t border-border-subtle bg-background shadow-xl transition-[height] duration-300 ease-out"
		style="height: {stateHeights[drawerState]}; transform: translateY({Math.max(
			0,
			currentTranslateY
		)}px);"
		role="dialog"
		aria-modal="true"
		aria-label="Activity panel"
		tabindex="-1"
		ontouchstart={handleTouchStart}
		ontouchmove={handleTouchMove}
		ontouchend={handleTouchEnd}
		data-testid="computer-panel-mobile"
	>
		<!-- Drag handle -->
		<div class="flex shrink-0 justify-center pb-1 pt-2.5">
			<div class="h-1 w-8 rounded-full bg-border-subtle"></div>
		</div>

		<!-- Panel content -->
		<div class="flex-1 overflow-hidden">
			<ComputerPanel {toolCalls} {agentName} {vncAvailable} {vncUrl} {onVncToggle} mobile={true} />
		</div>
	</div>
{/if}
