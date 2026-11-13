<script lang="ts">
	import type { Snippet } from 'svelte';
	import { haptic } from '$lib/actions/gestures';
	import { scale } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';

	interface MenuItem {
		label: string;
		icon?: string;
		danger?: boolean;
		action: () => void;
	}

	interface Props {
		items: MenuItem[];
		children: Snippet;
	}

	let { items, children }: Props = $props();

	let menuOpen = $state(false);
	let menuX = $state(0);
	let menuY = $state(0);
	let longPressTimer: ReturnType<typeof setTimeout> | null = null;
	let menuEl: HTMLDivElement | undefined = $state();

	function openMenu(x: number, y: number): void {
		menuX = x;
		menuY = y;
		menuOpen = true;

		// Adjust position if menu would overflow viewport
		requestAnimationFrame(() => {
			if (!menuEl) return;
			const rect = menuEl.getBoundingClientRect();
			if (rect.right > window.innerWidth) {
				menuX = window.innerWidth - rect.width - 8;
			}
			if (rect.bottom > window.innerHeight) {
				menuY = window.innerHeight - rect.height - 8;
			}
		});
	}

	function closeMenu(): void {
		menuOpen = false;
	}

	function handleContextMenu(e: MouseEvent): void {
		e.preventDefault();
		openMenu(e.clientX, e.clientY);
	}

	function handleTouchStart(e: TouchEvent): void {
		const touch = e.touches[0];
		longPressTimer = setTimeout(() => {
			e.preventDefault();
			haptic(15);
			openMenu(touch.clientX, touch.clientY);
		}, 500);
	}

	function handleTouchEnd(): void {
		if (longPressTimer) {
			clearTimeout(longPressTimer);
			longPressTimer = null;
		}
	}

	function handleTouchMove(): void {
		if (longPressTimer) {
			clearTimeout(longPressTimer);
			longPressTimer = null;
		}
	}

	function handleItemClick(item: MenuItem): void {
		closeMenu();
		item.action();
	}

	function handleWindowClick(e: MouseEvent): void {
		if (menuEl && !menuEl.contains(e.target as Node)) {
			closeMenu();
		}
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			closeMenu();
		}
	}
</script>

<svelte:window onclick={handleWindowClick} onkeydown={handleKeydown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	oncontextmenu={handleContextMenu}
	ontouchstart={handleTouchStart}
	ontouchend={handleTouchEnd}
	ontouchmove={handleTouchMove}
>
	{@render children()}
</div>

{#if menuOpen}
	<div
		bind:this={menuEl}
		class="fixed z-[9999] min-w-[160px] rounded-xl border border-border-subtle bg-surface-2 py-1 shadow-sm"
		style="left: {menuX}px; top: {menuY}px;"
		role="menu"
		tabindex="-1"
		transition:scale={{ duration: 120, start: 0.95, easing: cubicOut }}
	>
		{#each items as item, i (item.label)}
			<button
				onclick={() => handleItemClick(item)}
				class="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors duration-100
					{item.danger
					? 'text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10'
					: 'text-foreground hover:bg-surface-2'}"
				role="menuitem"
				style="animation: fadeSlideUp 0.12s {i * 30}ms var(--ease-out) both"
			>
				{#if item.icon}
					<span class="text-base leading-none" aria-hidden="true">{item.icon}</span>
				{/if}
				{item.label}
			</button>
		{/each}
	</div>
{/if}
