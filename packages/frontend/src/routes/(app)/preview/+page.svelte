<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import MousePointerClick from '@lucide/svelte/icons/mouse-pointer-click';
	import Smartphone from '@lucide/svelte/icons/smartphone';
	import X from '@lucide/svelte/icons/x';
	import PropertyPanel from '$lib/components/toolRenderers/selector/PropertyPanel.svelte';
	import SelectionOverlays from '$lib/components/toolRenderers/selector/SelectionOverlays.svelte';
	import DeviceSkin from '$lib/components/toolRenderers/DeviceSkin.svelte';
	import ExpoQrButton from '$lib/components/toolRenderers/ExpoQrButton.svelte';
	import type {
		Selection,
		DesignTokens,
		ElementApplyPayload,
		DesignSystemApplyPayload,
		SelectorOutboundMessage,
		SelectorInboundMessage
	} from '$lib/components/toolRenderers/selector/types';
	import { chatInputPrefill, chatInputAutoSubmit } from '$stores/chatInput';
	import { activeSelectorSelection } from '$stores/selectorSelection';

	// --- Query-param props -------------------------------------------------
	const url = $derived($page.url.searchParams.get('url') ?? '');
	const framework = $derived($page.url.searchParams.get('framework') || null);
	const kind = $derived($page.url.searchParams.get('kind') || null);
	const isExpoWeb = $derived(kind === 'expo-web');

	// --- Selector state (mirrors PreviewCanvas) ----------------------------
	let selectorEnabled = $state(false);
	let currentSelection: Selection | null = $state(null);
	let hoverRect = $state<{ x: number; y: number; width: number; height: number } | null>(null);
	let selectedRect = $state<{ x: number; y: number; width: number; height: number } | null>(null);
	const designTokens: DesignTokens | null = $state(null);
	let iframeEl: HTMLIFrameElement | null = $state(null);

	const showPanel = $derived(selectorEnabled || currentSelection != null);

	// --- Skin state --------------------------------------------------------
	let skinEnabled = $state(false);
	let skinVariant = $state<'android' | 'iphone'>('android');
	$effect(() => {
		skinEnabled = isExpoWeb;
	});

	// --- postMessage bridge ------------------------------------------------
	function postToIframe(msg: SelectorOutboundMessage): void {
		try {
			iframeEl?.contentWindow?.postMessage(msg, '*');
		} catch {
			// ignore cross-origin errors
		}
	}

	function handleIframeMessage(ev: MessageEvent): void {
		if (!iframeEl || ev.source !== iframeEl.contentWindow) return;
		const data = ev.data as SelectorInboundMessage | undefined;
		if (!data || typeof data !== 'object' || typeof data.type !== 'string') return;
		if (!data.type.startsWith('sandbox-selector:')) return;

		switch (data.type) {
			case 'sandbox-selector:ready':
				if (selectorEnabled) postToIframe({ type: 'sandbox-selector:enable' });
				break;
			case 'sandbox-selector:hover':
				hoverRect = data.rect;
				break;
			case 'sandbox-selector:picked':
				currentSelection = data.selection;
				selectedRect = data.selection.boundingRect;
				activeSelectorSelection.set(data.selection);
				hoverRect = null;
				break;
			case 'sandbox-selector:cleared':
				currentSelection = null;
				hoverRect = null;
				selectedRect = null;
				activeSelectorSelection.set(null);
				break;
			case 'sandbox-selector:restored':
				currentSelection = data.selection;
				selectedRect = data.selection?.boundingRect ?? null;
				activeSelectorSelection.set(data.selection ?? null);
				break;
		}
	}

	onMount(() => {
		window.addEventListener('message', handleIframeMessage);
	});

	onDestroy(() => {
		window.removeEventListener('message', handleIframeMessage);
		activeSelectorSelection.set(null);
	});

	function toggleSelector(): void {
		selectorEnabled = !selectorEnabled;
		if (selectorEnabled) {
			postToIframe({ type: 'sandbox-selector:enable' });
		} else {
			postToIframe({ type: 'sandbox-selector:disable' });
			postToIframe({ type: 'sandbox-selector:clear-element-styles' });
			currentSelection = null;
			hoverRect = null;
			selectedRect = null;
			activeSelectorSelection.set(null);
		}
	}

	function closePanel(): void {
		if (selectorEnabled) toggleSelector();
		else currentSelection = null;
	}

	function closeFullscreen(): void {
		try {
			window.close();
		} catch {
			// ignore
		}
		// If window.close() silently no-ops (opener gone), fall back to home.
		setTimeout(() => {
			if (!window.closed) goto('/');
		}, 150);
	}

	function toggleSkin(): void {
		skinEnabled = !skinEnabled;
	}
	function toggleSkinVariant(): void {
		skinVariant = skinVariant === 'android' ? 'iphone' : 'android';
	}

	// --- PropertyPanel callbacks ------------------------------------------
	function onElementStyleChange(styles: Record<string, string>): void {
		postToIframe({ type: 'sandbox-selector:apply-element-style', styles });
	}
	function onElementStyleReset(): void {
		postToIframe({ type: 'sandbox-selector:clear-element-styles' });
	}
	function onRootCssChange(css: string): void {
		if (css) postToIframe({ type: 'sandbox-selector:apply-root-css', css });
		else postToIframe({ type: 'sandbox-selector:clear-root-css' });
	}

	function camelToKebab(s: string): string {
		return s.replace(/([A-Z])/g, '-$1').toLowerCase();
	}

	function sendChatMessage(text: string): void {
		chatInputPrefill.set(text);
		chatInputAutoSubmit.set(true);
	}

	function onApplyElement(payload: ElementApplyPayload): void {
		const changeLines = Object.entries(payload.changes)
			.map(([k, v]) => `- ${camelToKebab(k)}: ${v}`)
			.join('\n');
		const classes = payload.classList.join(' ');
		const loc = payload.sourceLoc
			? `${payload.sourceLoc.fileName}:${payload.sourceLoc.lineNumber}:${payload.sourceLoc.columnNumber}`
			: 'unknown';
		sendChatMessage(
			`The user edited styles in the fullscreen preview.\n\nSource: ${loc}\nTag: <${payload.tagName.toLowerCase()}> .${classes}\n\nChanges:\n${changeLines}`
		);
	}

	function onApplyDesignSystem(payload: DesignSystemApplyPayload): void {
		const changeLines = Object.entries(payload.changes)
			.map(([k, v]) => `- ${k}: ${v}`)
			.join('\n');
		sendChatMessage(
			`The user edited the global design system in the fullscreen preview.\n\nFramework: ${payload.framework}\n\nChanges:\n${changeLines}`
		);
	}
</script>

<svelte:head>
	<title>Preview</title>
</svelte:head>

<div class="relative min-h-screen w-screen bg-background">
	{#if url}
		{#if isExpoWeb && skinEnabled}
			<div class="fixed inset-0 flex items-center justify-center bg-background p-6">
				<DeviceSkin variant={skinVariant}>
					<iframe
						bind:this={iframeEl}
						src={url}
						title="fullscreen preview"
						class="h-full w-full border-0 bg-background"
						sandbox="allow-scripts allow-same-origin allow-forms"
						data-testid="fullscreen-preview-iframe"
					></iframe>
				</DeviceSkin>
			</div>
		{:else}
			<iframe
				bind:this={iframeEl}
				src={url}
				title="fullscreen preview"
				class="fixed inset-0 h-screen w-screen border-0 bg-background"
				sandbox="allow-scripts allow-same-origin allow-forms"
				data-testid="fullscreen-preview-iframe"
			></iframe>
		{/if}

		<!-- Selector overlays (fixed viewport layer) -->
		{#if (selectorEnabled || currentSelection) && iframeEl}
			<SelectionOverlays
				{iframeEl}
				{hoverRect}
				selectedRect={currentSelection?.boundingRect ?? selectedRect}
				selection={currentSelection}
			/>
		{/if}

		<!-- PropertyPanel (slides in from right) -->
		{#if showPanel}
			<div class="fixed right-0 top-0 z-40 h-screen">
				<PropertyPanel
					selection={currentSelection}
					{framework}
					{designTokens}
					onClose={closePanel}
					{onElementStyleChange}
					{onElementStyleReset}
					{onRootCssChange}
					{onApplyElement}
					{onApplyDesignSystem}
				/>
			</div>
		{/if}

		<!-- Floating mini-toolbar (top-right) -->
		<div
			class="fixed right-3 top-3 z-50 flex items-center gap-1 rounded-lg border border-border-subtle bg-surface-2/95 px-2 py-1.5 shadow-lg backdrop-blur"
			data-testid="fullscreen-preview-toolbar"
		>
			<button
				type="button"
				onclick={toggleSelector}
				aria-pressed={selectorEnabled}
				title={selectorEnabled ? 'Done selecting' : 'Select element'}
				aria-label={selectorEnabled ? 'Done selecting' : 'Select element'}
				class="flex items-center gap-1 rounded px-1.5 py-1 text-[11px] transition-colors
					{selectorEnabled
					? 'bg-accent/10 text-accent'
					: 'text-muted hover:bg-surface hover:text-foreground'}"
			>
				<MousePointerClick size={14} strokeWidth={2} aria-hidden="true" />
			</button>
			{#if isExpoWeb}
				<button
					type="button"
					onclick={toggleSkin}
					aria-pressed={skinEnabled}
					title={skinEnabled ? 'Hide phone frame' : 'Show phone frame'}
					aria-label={skinEnabled ? 'Hide phone frame' : 'Show phone frame'}
					class="flex items-center gap-1 rounded px-1.5 py-1 text-[11px] transition-colors
						{skinEnabled ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-surface hover:text-foreground'}"
				>
					<Smartphone size={14} strokeWidth={2} aria-hidden="true" />
				</button>
				{#if skinEnabled}
					<button
						type="button"
						onclick={toggleSkinVariant}
						title="Switch phone style"
						aria-label="Switch phone style"
						class="rounded px-2 py-1 font-sans text-[11px] text-muted transition-colors hover:bg-surface hover:text-foreground"
					>
						{skinVariant === 'android' ? 'Android' : 'iPhone'}
					</button>
				{/if}
				<ExpoQrButton publicUrl={url} />
			{/if}
			<button
				type="button"
				onclick={closeFullscreen}
				aria-label="Close preview"
				title="Close"
				class="rounded p-1 text-muted hover:bg-surface hover:text-foreground"
			>
				<X size={13} strokeWidth={2} aria-hidden="true" />
			</button>
		</div>
	{:else}
		<div class="flex h-screen items-center justify-center font-sans text-[12px] italic text-subtle">
			Nothing to preview.
		</div>
	{/if}
</div>
