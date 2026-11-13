<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import MousePointerClick from '@lucide/svelte/icons/mouse-pointer-click';
	import Smartphone from '@lucide/svelte/icons/smartphone';
	import Maximize2 from '@lucide/svelte/icons/maximize-2';
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope } from './_shared';
	import PropertyPanel from './selector/PropertyPanel.svelte';
	import SelectionOverlays from './selector/SelectionOverlays.svelte';
	import DeviceSkin from './DeviceSkin.svelte';
	import ExpoQrButton from './ExpoQrButton.svelte';
	import type {
		Selection,
		DesignTokens,
		ElementApplyPayload,
		DesignSystemApplyPayload,
		SelectorOutboundMessage,
		SelectorInboundMessage
	} from './selector/types';
	import { chatInputPrefill, chatInputAutoSubmit } from '$stores/chatInput';
	import { activeSelectorSelection } from '$stores/selectorSelection';

	type Props = {
		toolCall: ToolCallMessage;
		/** Dev-only escape hatch: when non-null, overrides the internal selection state.
		 * Used by the selector dev playground to simulate an iframe pick without a real
		 * postMessage round-trip. Do NOT use in production code paths. */
		__devMockSelection?: Selection | null;
	};
	let { toolCall, __devMockSelection = null }: Props = $props();

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);

	let argPort = $derived(
		typeof toolCall.args?.port === 'number' ? (toolCall.args.port as number) : undefined
	);
	let argLabel = $derived(
		typeof toolCall.args?.label === 'string' ? (toolCall.args.label as string) : ''
	);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object'
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let port = $derived(typeof resultObj.port === 'number' ? (resultObj.port as number) : argPort);
	let url = $derived(typeof resultObj.url === 'string' ? (resultObj.url as string) : '');
	let label = $derived(
		typeof resultObj.label === 'string' ? (resultObj.label as string) : argLabel
	);
	let framework = $derived(
		typeof resultObj.framework === 'string' ? (resultObj.framework as string) : null
	);
	let kind = $derived(typeof resultObj.kind === 'string' ? (resultObj.kind as string) : null);
	let isExpoWeb = $derived(kind === 'expo-web');

	// --- Selector state ----------------------------------------------------

	let selectorEnabled = $state(false);
	let currentSelection: Selection | null = $state(null);
	// Rects come from the iframe-side selector in iframe-document coordinates.
	// `SelectionOverlays` translates them to viewport space for rendering.
	let hoverRect = $state<{ x: number; y: number; width: number; height: number } | null>(null);
	let selectedRect = $state<{ x: number; y: number; width: number; height: number } | null>(null);
	let designTokens: DesignTokens | null = $state(null);
	let iframeEl: HTMLIFrameElement | null = $state(null);

	const effectiveSelection = $derived(__devMockSelection ?? currentSelection);
	const showPanel = $derived(selectorEnabled || effectiveSelection != null);

	function openFullscreen(): void {
		if (!url) return;
		const params = new URLSearchParams({ url });
		if (framework) params.set('framework', framework);
		if (kind) params.set('kind', kind);
		window.open(`/preview?${params.toString()}`, '_blank', 'noopener');
	}

	// --- Device skin state -------------------------------------------------

	let skinEnabled = $state(true);
	let skinVariant = $state<'android' | 'iphone'>('android');

	// Auto-scale: the skin renders at its realistic logical-pixel size
	// (412x892 iPhone / 382x822 Android). On a large desktop it fits at
	// 1.0; on a narrow panel we shrink it via a ResizeObserver-driven scale.
	let skinContainerEl: HTMLDivElement | null = $state(null);
	let skinAutoScale = $state(1);

	function computeSkinScale(): void {
		if (!skinContainerEl) return;
		const rect = skinContainerEl.getBoundingClientRect();
		const baseW = skinVariant === 'iphone' ? 412 : 382;
		const baseH = skinVariant === 'iphone' ? 892 : 822;
		// Leave a bit of breathing room (24px) on each axis.
		const avW = Math.max(0, rect.width - 24);
		const avH = Math.max(0, rect.height - 24);
		if (avW === 0 || avH === 0) return;
		skinAutoScale = Math.max(0.3, Math.min(avW / baseW, avH / baseH, 1));
	}

	$effect(() => {
		if (!skinContainerEl) return;
		computeSkinScale();
		const ro = new ResizeObserver(() => computeSkinScale());
		ro.observe(skinContainerEl);
		return () => ro.disconnect();
	});

	// Re-compute on variant changes.
	$effect(() => {
		// Subscribe to skinVariant.
		void skinVariant;
		computeSkinScale();
	});

	// Default the skin to enabled only when exposing an expo-web preview.
	$effect(() => {
		skinEnabled = isExpoWeb;
	});

	function toggleSkin(): void {
		skinEnabled = !skinEnabled;
	}

	function toggleSkinVariant(): void {
		skinVariant = skinVariant === 'android' ? 'iphone' : 'android';
	}

	// --- postMessage bridge -----------------------------------------------

	function postToIframe(msg: SelectorOutboundMessage): void {
		try {
			iframeEl?.contentWindow?.postMessage(msg, '*');
		} catch {
			// Cross-origin errors are expected for some sandbox hosts; ignore.
		}
	}

	function handleIframeMessage(ev: MessageEvent): void {
		if (!iframeEl || ev.source !== iframeEl.contentWindow) return;
		const data = ev.data as SelectorInboundMessage | undefined;
		if (!data || typeof data !== 'object' || typeof data.type !== 'string') return;
		if (!data.type.startsWith('sandbox-selector:')) return;

		switch (data.type) {
			case 'sandbox-selector:ready':
				// Re-arm if the iframe was hot-reloaded while the selector is on.
				if (selectorEnabled) postToIframe({ type: 'sandbox-selector:enable' });
				break;
			case 'sandbox-selector:hover':
				hoverRect = data.rect;
				break;
			case 'sandbox-selector:picked':
				currentSelection = data.selection;
				selectedRect = data.selection.boundingRect;
				activeSelectorSelection.set(data.selection);
				// Clear hover once a selection is locked — the selected outline
				// already marks the element.
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

	// Mirror dev-mock selections into the shared store so the chat input
	// chip also reflects playground simulations.
	$effect(() => {
		if (__devMockSelection !== undefined) {
			activeSelectorSelection.set(__devMockSelection);
		}
	});

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

	// Convert camelCase to kebab-case for human-readable output in the prompt.
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
		let message: string;
		if (payload.sourceLoc) {
			const { fileName, lineNumber, columnNumber } = payload.sourceLoc;
			message = `The user selected an element in the preview and edited its styles. Please apply these changes to the source code.

Source: \`${fileName}:${lineNumber}:${columnNumber}\`
Tag: \`<${payload.tagName.toLowerCase()}>\` with classes \`[${classes}]\`

Requested style changes:
${changeLines}

Apply these changes directly to the JSX/TSX source. Prefer editing Tailwind classes if the element currently uses Tailwind; use inline style otherwise.`;
		} else {
			message = `The user selected an element in the preview and edited its styles, but the exact source location couldn't be determined. Please find the element and apply changes.

Tag: \`<${payload.tagName.toLowerCase()}>\` with classes \`[${classes}]\`
Element snippet: ${payload.outerHTMLSnippet}

Requested style changes:
${changeLines}

Search the project source for this element (by class combination or text content), then apply the changes.`;
		}
		sendChatMessage(message);
	}

	function onApplyDesignSystem(payload: DesignSystemApplyPayload): void {
		const target =
			payload.framework === 'next'
				? 'app/globals.css (update :root CSS variables)'
				: payload.framework === 'expo'
					? 'constants/theme.ts (update Colors object)'
					: 'the project design token source (inspect and choose the right file)';
		const changeLines = Object.entries(payload.changes)
			.map(([k, v]) => `- ${k}: ${v}`)
			.join('\n');
		const message = `The user is editing the project's global design system. Please update the design tokens.

Framework: ${payload.framework}
Target file: ${target}

Changes:
${changeLines}

Apply these token changes and preserve the rest of the file's structure.`;
		sendChatMessage(message);
	}

	// Note: the old `onUseAsContext` helper was removed — the active
	// selection is automatically exposed to the chat input via the
	// `activeSelectorSelection` store, so no explicit button is needed.
</script>

{#if (selectorEnabled || effectiveSelection) && iframeEl && !isRunning && !isError && url}
	<SelectionOverlays
		{iframeEl}
		{hoverRect}
		selectedRect={effectiveSelection?.boundingRect ?? selectedRect}
		selection={effectiveSelection}
	/>
{/if}

<div class="h-full p-2" data-testid="preview-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="preview-canvas"
	>
		<!-- Title bar -->
		<div
			class="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface px-3 py-2"
		>
			<div class="flex min-w-0 flex-1 items-center gap-2 text-muted">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="13"
					height="13"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="shrink-0"
				>
					<path d="M2 3h20v14H2z" />
					<path d="M8 21h8" />
					<path d="M12 17v4" />
				</svg>
				<span class="font-sans text-[12px] font-medium text-foreground"> Preview </span>
				{#if label}
					<span
						class="truncate font-sans text-[11px] text-muted"
						title={label}
						data-testid="preview-canvas-label"
					>
						{label}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if url && !isError && !isRunning && isExpoWeb}
					<button
						type="button"
						onclick={toggleSkin}
						aria-pressed={skinEnabled}
						title={skinEnabled ? 'Hide phone frame' : 'Show phone frame'}
						aria-label={skinEnabled ? 'Hide phone frame' : 'Show phone frame'}
						class="flex items-center gap-1 rounded px-1.5 py-1 text-[11px] transition-colors
							{skinEnabled ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-surface hover:text-foreground'}"
						data-testid="preview-canvas-skin-toggle"
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
							data-testid="preview-canvas-skin-variant"
						>
							{skinVariant === 'android' ? 'Android' : 'iPhone'}
						</button>
					{/if}
					<ExpoQrButton publicUrl={url} />
				{/if}
				{#if url && !isError && !isRunning}
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
						data-testid="preview-canvas-selector-toggle"
					>
						<MousePointerClick size={14} strokeWidth={2} aria-hidden="true" />
					</button>
				{/if}
				{#if url && !isError && !isRunning}
					<button
						type="button"
						onclick={openFullscreen}
						title="Open in new tab"
						aria-label="Open in new tab"
						class="flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-muted transition-colors hover:bg-surface hover:text-foreground"
						data-testid="preview-canvas-fullscreen"
					>
						<Maximize2 size={14} strokeWidth={2} aria-hidden="true" />
					</button>
				{/if}
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-sans text-[11px] text-muted"
						data-testid="preview-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						Loading…
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-sans text-[11px] font-medium text-accent"
					>
						Preview unavailable
					</span>
				{:else}
					<span class="rounded bg-success/15 px-2 py-0.5 font-sans text-[11px] text-success">
						Live
					</span>
				{/if}
			</div>
		</div>

		<!-- Body -->
		<div class="flex flex-1 overflow-hidden bg-background" data-testid="preview-canvas-body">
			<div class="flex-1 overflow-hidden">
				{#if isRunning}
					<div
						class="flex h-full items-center justify-center gap-2 text-[12px] text-muted"
						data-testid="preview-canvas-skeleton"
					>
						<span
							class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
							aria-hidden="true"
						></span>
						Exposing port…
					</div>
				{:else if isError}
					<div class="p-4">
						<div
							class="rounded border border-accent/30 bg-accent/5 px-3 py-2"
							data-testid="preview-canvas-error"
						>
							<div class="font-sans text-[12px] font-medium text-accent">
								{envelope.error ?? 'Preview unavailable'}
							</div>
							{#if envelope.message}
								<div class="mt-1 text-[12px] text-foreground">{envelope.message}</div>
							{/if}
							{#if envelope.hint}
								<div class="mt-1 text-[11px] italic text-muted">Hint: {envelope.hint}</div>
							{/if}
						</div>
					</div>
				{:else if url}
					{#if isExpoWeb && skinEnabled}
						<div
							bind:this={skinContainerEl}
							class="flex h-full w-full items-center justify-center bg-background p-3"
						>
							<DeviceSkin variant={skinVariant} scale={skinAutoScale}>
								<iframe
									bind:this={iframeEl}
									src={url}
									title={label || `preview ${port ?? ''}`}
									class="h-full w-full border-0 bg-background"
									sandbox="allow-scripts allow-same-origin allow-forms"
									data-testid="preview-canvas-iframe"
								></iframe>
							</DeviceSkin>
						</div>
					{:else}
						<iframe
							bind:this={iframeEl}
							src={url}
							title={label || `preview ${port ?? ''}`}
							class="h-full w-full border-0 bg-background"
							sandbox="allow-scripts allow-same-origin allow-forms"
							data-testid="preview-canvas-iframe"
						></iframe>
					{/if}
				{:else}
					<div
						class="flex h-full items-center justify-center font-sans text-[12px] italic text-subtle"
					>
						Nothing to preview yet
					</div>
				{/if}
			</div>

			{#if showPanel && !isRunning && !isError && url}
				<div class="border-l border-border-subtle bg-surface-2">
					<PropertyPanel
						selection={effectiveSelection}
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
		</div>
	</div>
</div>
