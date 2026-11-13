<script lang="ts">
	import type { Snippet } from 'svelte';
	import { haptic } from '$lib/actions/gestures';

	type DrawerState = 'closed' | 'peek' | 'half' | 'full';

	type Props = {
		open: boolean;
		onclose?: () => void;
		children: Snippet;
		class?: string;
		initialState?: Exclude<DrawerState, 'closed'>;
		'aria-label'?: string;
		[key: string]: unknown;
	};

	let {
		open = $bindable(false),
		onclose,
		children,
		class: className = '',
		initialState = 'half',
		'aria-label': ariaLabel,
		...rest
	}: Props = $props();

	const stateHeights: Record<Exclude<DrawerState, 'closed'>, string> = {
		peek: 'max-h-[25vh]',
		half: 'max-h-[50vh]',
		full: 'max-h-[90vh]'
	};

	const stateOrder: Exclude<DrawerState, 'closed'>[] = ['peek', 'half', 'full'];

	let drawerState: Exclude<DrawerState, 'closed'> = $state('half');
	let startY = 0;
	let isDragging = false;

	function close(): void {
		open = false;
		onclose?.();
	}

	function handleTouchStart(e: TouchEvent): void {
		startY = e.touches[0].clientY;
		isDragging = true;
	}

	function handleTouchEnd(e: TouchEvent): void {
		if (!isDragging) return;
		isDragging = false;

		const endY = e.changedTouches[0].clientY;
		const diff = endY - startY;
		const threshold = 50;

		if (diff > threshold) {
			// Swipe down — go to smaller state or close
			haptic();
			const currentIdx = stateOrder.indexOf(drawerState);
			if (currentIdx <= 0) {
				close();
			} else {
				drawerState = stateOrder[currentIdx - 1];
			}
		} else if (diff < -threshold) {
			// Swipe up — go to larger state
			haptic();
			const currentIdx = stateOrder.indexOf(drawerState);
			if (currentIdx < stateOrder.length - 1) {
				drawerState = stateOrder[currentIdx + 1];
			}
		}
	}

	function handleBackdropClick(): void {
		close();
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			close();
		}
	}

	$effect(() => {
		if (open) {
			drawerState = initialState;
		}
	});
</script>

{#if open}
	<!-- Backdrop -->
	<div
		class="fixed inset-0 z-[9998] bg-foreground/30 transition-opacity duration-300"
		onclick={handleBackdropClick}
		onkeydown={handleKeydown}
		role="presentation"
	></div>

	<!-- Drawer -->
	<div
		class="fixed inset-x-0 bottom-0 z-[9999] flex flex-col rounded-t-2xl border-t border-border-subtle bg-background shadow-xl transition-all duration-300 {stateHeights[
			drawerState
		]} {className}"
		role="dialog"
		aria-modal="true"
		aria-label={ariaLabel}
		ontouchstart={handleTouchStart}
		ontouchend={handleTouchEnd}
		{...rest}
	>
		<!-- Drag handle -->
		<div class="flex shrink-0 justify-center py-3">
			<div class="h-1 w-8 rounded-full bg-border-strong"></div>
		</div>

		<!-- Content -->
		<div class="flex-1 overflow-y-auto px-4 pb-4">
			{@render children()}
		</div>
	</div>
{/if}
