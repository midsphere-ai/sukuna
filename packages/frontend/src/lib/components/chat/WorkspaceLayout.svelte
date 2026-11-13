<script lang="ts">
	import type { Snippet } from 'svelte';
	import { get } from 'svelte/store';
	import { workspaceLayout, setChatWidth } from '$stores/workspaceLayout';
	import { toolCalls } from '$services/sse';

	type Props = {
		editor: Snippet;
		chat: Snippet;
	};

	let { editor, chat }: Props = $props();

	// Initialize from store's current value to avoid a flash of wrong layout
	let layout = $state(get(workspaceLayout));
	let hasToolCalls = $state(false);

	const unsubLayout = workspaceLayout.subscribe((v) => {
		layout = v;
	});
	const unsubToolCalls = toolCalls.subscribe((tc) => {
		hasToolCalls = tc.size > 0;
	});

	// Editor is effectively hidden when explicitly collapsed OR when the canvas has no content
	let editorHidden = $derived(layout.editorCollapsed || !hasToolCalls);

	const CANVAS_MIN_WIDTH = 300;

	// Resize state — plain let, NOT $state (mouse event handlers + $state causes effect_update_depth_exceeded)
	// svelte-ignore non_reactive_update
	let resizing = false;
	let resizeStartX = 0;
	let resizeStartWidth = 0;
	let containerEl: HTMLDivElement | undefined = $state();

	function handleResizeStart(e: MouseEvent): void {
		resizing = true;
		resizeStartX = e.clientX;
		resizeStartWidth = layout.chatWidth;
		e.preventDefault();
	}

	function handleResizeMove(e: MouseEvent): void {
		if (!resizing) return;
		const diff = e.clientX - resizeStartX;
		let newWidth = resizeStartWidth + diff;
		// Clamp so canvas always gets at least CANVAS_MIN_WIDTH
		if (containerEl) {
			const maxChat = containerEl.clientWidth - CANVAS_MIN_WIDTH;
			newWidth = Math.min(newWidth, maxChat);
		}
		setChatWidth(newWidth);
	}

	function handleResizeEnd(): void {
		resizing = false;
	}

	import { onDestroy } from 'svelte';
	onDestroy(() => {
		unsubLayout();
		unsubToolCalls();
	});
</script>

<svelte:window onmousemove={handleResizeMove} onmouseup={handleResizeEnd} />

<!-- Desktop: 3-pane split layout (hidden on mobile) -->
<div
	bind:this={containerEl}
	class="hidden h-full min-h-0 lg:flex"
	class:cursor-col-resize={resizing}
	data-testid="workspace-layout"
>
	<!-- Chat pane (left) -->
	<div
		class="flex h-full flex-col overflow-hidden {editorHidden
			? 'w-full'
			: 'shrink-0 border-r border-border'}"
		style={editorHidden ? '' : `width: ${layout.chatWidth}px; min-width: 320px;`}
		data-testid="workspace-chat"
		data-editor-collapsed={editorHidden || undefined}
	>
		{@render chat()}
	</div>

	{#if !editorHidden}
		<!-- Chat-to-canvas divider -->
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="group relative z-10 flex w-1.5 cursor-col-resize items-center justify-center"
			onmousedown={handleResizeStart}
			role="separator"
			aria-orientation="vertical"
			aria-label="Resize canvas panel"
			tabindex="-1"
		>
			<div
				class="h-full w-1 transition-colors group-hover:bg-accent/30 {resizing
					? 'bg-accent/40'
					: ''}"
			></div>
		</div>

		<!-- Canvas pane (right) — takes remaining space -->
		<div
			class="flex flex-1 flex-col overflow-hidden"
			style="min-width: {CANVAS_MIN_WIDTH}px;"
			data-testid="workspace-editor"
		>
			{@render editor()}
		</div>
	{/if}
</div>

<!-- Mobile: single pane chat (no tabs) -->
<div
	class="flex h-full min-w-0 flex-col overflow-hidden lg:hidden"
	data-testid="workspace-layout-mobile"
>
	{@render chat()}
</div>
