<script lang="ts">
	import PropertyPanel from '$lib/components/toolRenderers/selector/PropertyPanel.svelte';
	import PreviewCanvas from '$lib/components/toolRenderers/PreviewCanvas.svelte';
	import DeviceSkin from '$lib/components/toolRenderers/DeviceSkin.svelte';
	import ExpoQrButton from '$lib/components/toolRenderers/ExpoQrButton.svelte';
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import type {
		Selection,
		DesignTokens,
		ElementApplyPayload,
		DesignSystemApplyPayload
	} from '$lib/components/toolRenderers/selector/types';
	import type { ToolCallMessage } from '$services/sse';

	// ────────────────────────────────────────────────────────────
	// Section 1: Mock Selection + DesignTokens
	// ────────────────────────────────────────────────────────────
	//
	// A fully-populated Selection so PropertyPanel can render every
	// readStyle() lookup against real values instead of empty strings.
	// Every CSS prop PropertyPanel reads appears here.

	const mockSelection: Selection = {
		sourceLoc: { fileName: 'app/page.tsx', lineNumber: 42, columnNumber: 15 },
		tagName: 'DIV',
		classList: ['hero-title', 'px-6', 'py-4', 'text-4xl', 'font-medium'],
		outerHTMLSnippet:
			'<div class="hero-title px-6 py-4 text-4xl font-medium">Welcome to Jatayu AI</div>',
		boundingRect: { x: 128, y: 96, width: 640, height: 72 },
		computedStyles: {
			// Typography
			fontFamily: 'Inter',
			fontSize: '48px',
			fontWeight: '700',
			lineHeight: '1.1',
			letterSpacing: '-0.5px',
			textAlign: 'left',
			color: 'rgb(17, 17, 17)',
			// Background
			backgroundColor: 'rgba(255, 255, 255, 0)',
			opacity: '1',
			// Padding
			paddingTop: '16px',
			paddingRight: '16px',
			paddingBottom: '16px',
			paddingLeft: '16px',
			// Margin
			marginTop: '0px',
			marginRight: '0px',
			marginBottom: '0px',
			marginLeft: '0px',
			// Border widths
			borderTopWidth: '0px',
			borderRightWidth: '0px',
			borderBottomWidth: '0px',
			borderLeftWidth: '0px',
			// Border styles
			borderTopStyle: 'solid',
			borderRightStyle: 'solid',
			borderBottomStyle: 'solid',
			borderLeftStyle: 'solid',
			// Border colors
			borderTopColor: 'rgb(240, 238, 230)',
			borderRightColor: 'rgb(240, 238, 230)',
			borderBottomColor: 'rgb(240, 238, 230)',
			borderLeftColor: 'rgb(240, 238, 230)',
			// Border radii
			borderTopLeftRadius: '0px',
			borderTopRightRadius: '0px',
			borderBottomRightRadius: '0px',
			borderBottomLeftRadius: '0px',
			// Dimensions & layout
			width: 'auto',
			height: 'auto',
			minWidth: '0px',
			minHeight: '0px',
			maxWidth: 'none',
			maxHeight: 'none',
			display: 'block',
			flexDirection: 'row',
			justifyContent: 'flex-start',
			alignItems: 'stretch',
			gap: '0px'
		}
	};

	const mockDesignTokens: DesignTokens = {
		colors: {
			primary: '#c96442',
			secondary: '#3898ec',
			accent: '#6e8365',
			background: '#faf9f5',
			foreground: '#141413',
			muted: '#5e5d59',
			destructive: '#b53333',
			border: '#f0eee6'
		},
		fonts: {
			sans: 'Bricolage Grotesque',
			serif: 'Libre Baskerville',
			mono: 'Berkeley Mono'
		},
		radius: '0.625rem',
		spacing: '1rem'
	};

	// ────────────────────────────────────────────────────────────
	// Section 1 callbacks — console.log everything
	// ────────────────────────────────────────────────────────────

	function onElementStyleChange(styles: Record<string, string>): void {
		console.log('[playground] onElementStyleChange', styles);
	}
	function onElementStyleReset(): void {
		console.log('[playground] onElementStyleReset');
	}
	function onRootCssChange(css: string): void {
		console.log('[playground] onRootCssChange', css);
	}
	function onApplyElement(payload: ElementApplyPayload): void {
		console.log('[playground] onApplyElement', payload);
	}
	function onApplyDesignSystem(payload: DesignSystemApplyPayload): void {
		console.log('[playground] onApplyDesignSystem', payload);
	}

	// ────────────────────────────────────────────────────────────
	// Section 2: Mock expose tool calls
	// ────────────────────────────────────────────────────────────

	function makeToolCall(callId: string, result: Record<string, unknown>): ToolCallMessage {
		return {
			type: 'tool_call',
			callId,
			toolName: 'expose',
			status: 'success',
			args: { port: result.port, label: result.label },
			result
		};
	}

	const expoToolCall = makeToolCall('pg-expose-expo', {
		success: true,
		port: 8081,
		url: 'https://example.com',
		label: 'expo-dev',
		framework: 'expo',
		kind: 'expo-web'
	});

	const nextToolCall = makeToolCall('pg-expose-next', {
		success: true,
		port: 3000,
		url: 'https://example.com',
		label: 'next-dev',
		framework: 'next',
		kind: 'web'
	});

	const plainToolCall = makeToolCall('pg-expose-plain', {
		success: true,
		port: 5173,
		url: 'https://example.com',
		label: 'vite-dev'
	});

	let mockInjectedSelection = $state<Selection | null>(null);

	function toggleInjected(): void {
		mockInjectedSelection = mockInjectedSelection ? null : mockSelection;
	}

	// ────────────────────────────────────────────────────────────
	// Section 3: Tabs primitive sample
	// ────────────────────────────────────────────────────────────

	const sampleTabs = [
		{ id: 'one', label: 'Overview' },
		{ id: 'two', label: 'Details' },
		{ id: 'three', label: 'History' }
	];
	let sampleActive = $state('one');

	// Section 4: device skin scale slider (0.5–1.0)
	let skinPreviewScale = $state(1);
</script>

<svelte:head>
	<title>Selector Playground</title>
</svelte:head>

<div class="min-h-screen bg-background">
	<div class="mx-auto max-w-6xl p-6">
		<header class="mb-8">
			<h1 class="text-2xl font-medium text-foreground">Selector Playground</h1>
			<p class="mt-1 text-sm text-muted">
				Visual preview of the component-selector UI (PropertyPanel + PreviewCanvas integration)
				without requiring a live Expo/Next dev server.
			</p>
		</header>

		<!-- ═══════════════ Section 1 ═══════════════ -->
		<section class="my-8">
			<h2 class="mb-4 text-lg font-medium text-foreground">
				1. Standalone PropertyPanel (mock Selection)
			</h2>
			<p class="mb-4 text-sm text-muted">
				This is a live mock — changes here only log to the console. Real projects would round-trip
				through the agent. Open devtools to see what payloads would be emitted.
			</p>
			<div class="flex gap-4 rounded-lg border border-border-subtle bg-surface-2 p-4">
				<PropertyPanel
					selection={mockSelection}
					framework="next"
					designTokens={mockDesignTokens}
					{onElementStyleChange}
					{onElementStyleReset}
					{onRootCssChange}
					{onApplyElement}
					{onApplyDesignSystem}
				/>
				<div class="flex-1 text-[12px] text-muted">
					<div class="mb-2 font-mono text-[10px] uppercase tracking-wide">mock element</div>
					<div
						class="rounded border border-border-subtle bg-background p-3 font-mono text-[11px] text-foreground"
					>
						&lt;div class="hero-title px-6 py-4 text-4xl font-medium"&gt;
					</div>
					<div class="mt-3 text-[11px]">
						Source: <span class="font-mono">app/page.tsx:42:15</span>
					</div>
				</div>
			</div>
		</section>

		<!-- ═══════════════ Section 2 ═══════════════ -->
		<section class="my-8">
			<h2 class="mb-4 text-lg font-medium text-foreground">
				2. PreviewCanvas with mocked expose tool calls
			</h2>
			<p class="mb-4 text-sm text-muted">
				The iframe points at <code class="font-mono">example.com</code>, so the real selector can't
				target live elements. Use the button below to inject a mock selection via the
				<code class="font-mono">__devMockSelection</code> dev-only escape hatch.
			</p>

			<div class="mb-3 flex items-center gap-2">
				<button
					type="button"
					onclick={toggleInjected}
					class="rounded-md border border-border-subtle bg-surface-2 px-3 py-1.5 text-[12px] text-foreground hover:bg-surface"
				>
					{mockInjectedSelection ? 'Clear mock selection' : 'Inject mock selection'}
				</button>
				<span class="text-[11px] text-muted">
					{mockInjectedSelection ? 'Panel shows mock element' : 'Panel shows empty state'}
				</span>
			</div>
			<p class="mb-3 text-[11px] italic text-muted">
				This renders the blue accent overlay on top of the iframe. In real projects, the overlay
				tracks hover and selection from the iframe-side client via postMessage.
			</p>

			<div class="mb-6">
				<div class="mb-2 text-[12px] font-medium text-muted">
					Expo variant (framework: expo, kind: expo-web)
				</div>
				<div class="h-[560px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
					<PreviewCanvas toolCall={expoToolCall} __devMockSelection={mockInjectedSelection} />
				</div>
			</div>

			<div class="mb-6">
				<div class="mb-2 text-[12px] font-medium text-muted">
					Next variant (framework: next, kind: web)
				</div>
				<div class="h-[560px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
					<PreviewCanvas toolCall={nextToolCall} __devMockSelection={mockInjectedSelection} />
				</div>
			</div>

			<div class="mb-2">
				<div class="mb-2 text-[12px] font-medium text-muted">
					Plain fallback (no framework / kind)
				</div>
				<div class="h-[560px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
					<PreviewCanvas toolCall={plainToolCall} __devMockSelection={mockInjectedSelection} />
				</div>
			</div>
		</section>

		<!-- ═══════════════ Section 4 ═══════════════ -->
		<section class="my-8 min-h-[940px]">
			<h2 class="mb-4 mt-8 text-lg font-medium text-foreground">4. Device skin variants</h2>
			<p class="mb-4 text-sm text-muted">
				Standalone <code class="font-mono">DeviceSkin</code> wrappers at realistic phone dimensions (iPhone
				412×892, Android 382×822). Both render at full size by default; use the slider to preview smaller
				scales.
			</p>

			<div
				class="mb-4 flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-2 p-4"
			>
				<div class="text-[12px] text-muted">ExpoQrButton (mock URL):</div>
				<ExpoQrButton publicUrl="https://abc123.proxy.midsphere.dev" />
			</div>

			<div
				class="mb-4 flex items-center gap-3 rounded-lg border border-border-subtle bg-surface-2 p-3"
			>
				<span class="text-[12px] font-medium text-foreground">Preview scale</span>
				<input
					type="range"
					min="0.5"
					max="1"
					step="0.05"
					bind:value={skinPreviewScale}
					class="flex-1 accent-accent"
					aria-label="Device skin preview scale"
				/>
				<span class="w-12 text-right text-[11px] text-muted">
					{Math.round(skinPreviewScale * 100)}%
				</span>
			</div>

			<div class="grid gap-4 md:grid-cols-2">
				<div class="rounded-lg border border-border-subtle bg-surface p-6">
					<div class="mb-3 text-[12px] font-medium text-muted">Android</div>
					<div
						class="flex h-[920px] items-center justify-center rounded-lg border border-border-subtle bg-background p-6"
					>
						<DeviceSkin variant="android" scale={skinPreviewScale}>
							<iframe
								src="https://example.com"
								title="android mock"
								class="h-full w-full border-0 bg-background"
								sandbox="allow-scripts allow-same-origin"
							></iframe>
						</DeviceSkin>
					</div>
				</div>
				<div class="rounded-lg border border-border-subtle bg-surface p-6">
					<div class="mb-3 text-[12px] font-medium text-muted">iPhone</div>
					<div
						class="flex h-[920px] items-center justify-center rounded-lg border border-border-subtle bg-background p-6"
					>
						<DeviceSkin variant="iphone" scale={skinPreviewScale}>
							<iframe
								src="https://example.com"
								title="iphone mock"
								class="h-full w-full border-0 bg-background"
								sandbox="allow-scripts allow-same-origin"
							></iframe>
						</DeviceSkin>
					</div>
				</div>
			</div>
		</section>

		<!-- ═══════════════ Section 3 ═══════════════ -->
		<section class="my-8">
			<h2 class="mb-4 text-lg font-medium text-foreground">3. Tabs primitive (standalone)</h2>
			<p class="mb-4 text-sm text-muted">
				Bare Tabs.svelte with three sample tabs. Active: <span class="font-mono"
					>{sampleActive}</span
				>
			</p>
			<div class="rounded-lg border border-border-subtle bg-surface-2 p-4">
				<Tabs bind:value={sampleActive} tabs={sampleTabs} />
				<div
					class="mt-4 rounded border border-border-subtle bg-background p-4 text-[13px] text-foreground"
				>
					Tab content for <span class="font-mono">{sampleActive}</span>
				</div>
			</div>
		</section>
	</div>
</div>
