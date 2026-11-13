<script lang="ts">
	import X from '@lucide/svelte/icons/x';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Palette from '@lucide/svelte/icons/palette';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import TextAlignStart from '@lucide/svelte/icons/text-align-start';
	import TextAlignCenter from '@lucide/svelte/icons/text-align-center';
	import TextAlignEnd from '@lucide/svelte/icons/text-align-end';
	import TextAlignJustify from '@lucide/svelte/icons/text-align-justify';
	import Sparkles from '@lucide/svelte/icons/sparkles';
	import type { Component } from 'svelte';
	import type {
		Selection,
		DesignTokens,
		ElementApplyPayload,
		DesignSystemApplyPayload
	} from './types';

	type Props = {
		selection: Selection | null;
		framework: string | null;
		designTokens: DesignTokens | null;
		onClose?: () => void;
		onElementStyleChange: (styles: Record<string, string>) => void;
		onElementStyleReset: () => void;
		onRootCssChange: (css: string) => void;
		onApplyElement: (payload: ElementApplyPayload) => void;
		onApplyDesignSystem: (payload: DesignSystemApplyPayload) => void;
	};

	let {
		selection,
		framework,
		designTokens,
		onClose,
		onElementStyleChange,
		onElementStyleReset,
		onRootCssChange,
		onApplyElement,
		onApplyDesignSystem
	}: Props = $props();

	// --- Tabs --------------------------------------------------------------
	let activeTab = $state<'element' | 'design'>('element');
	$effect(() => {
		if (selection == null && activeTab === 'element') activeTab = 'design';
	});

	// --- Element tab state -------------------------------------------------
	let pendingElementChanges = $state<Record<string, string>>({});
	let lastSelectionKey = $state<string | null>(null);
	$effect(() => {
		const key = selection
			? `${selection.sourceLoc?.fileName ?? ''}:${selection.sourceLoc?.lineNumber ?? ''}:${selection.sourceLoc?.columnNumber ?? ''}:${selection.tagName}`
			: null;
		if (key !== lastSelectionKey) {
			lastSelectionKey = key;
			pendingElementChanges = {};
			if (elementApplyTimer) {
				clearTimeout(elementApplyTimer);
				elementApplyTimer = null;
			}
			elementSaving = false;
		}
	});

	function readStyle(prop: string, fallback = ''): string {
		if (prop in pendingElementChanges) return pendingElementChanges[prop];
		return selection?.computedStyles?.[prop] ?? fallback;
	}

	function parsePx(val: string, fallback = 0): number {
		const m = val?.match?.(/^(-?[\d.]+)/);
		return m ? Number(m[1]) : fallback;
	}

	// --- Debounced auto-apply (element tab) -------------------------------
	const APPLY_DEBOUNCE_MS = 1500;
	let elementApplyTimer: ReturnType<typeof setTimeout> | null = null;
	let elementSaving = $state(false);

	function scheduleElementApply(): void {
		if (elementApplyTimer) clearTimeout(elementApplyTimer);
		elementSaving = true;
		elementApplyTimer = setTimeout(() => {
			elementApplyTimer = null;
			if (!selection || Object.keys(pendingElementChanges).length === 0) {
				elementSaving = false;
				return;
			}
			onApplyElement({
				sourceLoc: selection.sourceLoc,
				tagName: selection.tagName,
				classList: selection.classList,
				changes: { ...pendingElementChanges },
				outerHTMLSnippet: selection.outerHTMLSnippet
			});
			pendingElementChanges = {};
			elementSaving = false;
		}, APPLY_DEBOUNCE_MS);
	}

	function setStyle(prop: string, value: string): void {
		pendingElementChanges = { ...pendingElementChanges, [prop]: value };
		onElementStyleChange({ [prop]: value });
		scheduleElementApply();
	}

	function setStyleMany(patch: Record<string, string>): void {
		pendingElementChanges = { ...pendingElementChanges, ...patch };
		onElementStyleChange(patch);
		scheduleElementApply();
	}

	function resetElement(): void {
		if (elementApplyTimer) {
			clearTimeout(elementApplyTimer);
			elementApplyTimer = null;
		}
		elementSaving = false;
		pendingElementChanges = {};
		onElementStyleReset();
	}

	// --- Design system state ----------------------------------------------
	const COLOR_TOKENS = [
		{ key: 'primary', label: 'Primary' },
		{ key: 'secondary', label: 'Secondary' },
		{ key: 'accent', label: 'Accent' },
		{ key: 'background', label: 'Background' },
		{ key: 'foreground', label: 'Foreground' },
		{ key: 'muted', label: 'Muted' },
		{ key: 'destructive', label: 'Destructive' },
		{ key: 'border', label: 'Border' }
	] as const;
	const COLOR_TOKEN_KEYS = COLOR_TOKENS.map((c) => c.key) as readonly string[];

	let pendingDesignSystemChanges = $state<Record<string, string>>({});
	let designApplyTimer: ReturnType<typeof setTimeout> | null = null;
	let designSaving = $state(false);

	function readToken(name: string, fallback = ''): string {
		if (name in pendingDesignSystemChanges) return pendingDesignSystemChanges[name];
		if (!designTokens) return fallback;
		if (COLOR_TOKEN_KEYS.includes(name)) return designTokens.colors?.[name] ?? fallback;
		if (name === 'fontSans') return designTokens.fonts?.sans ?? fallback;
		if (name === 'fontSerif') return designTokens.fonts?.serif ?? fallback;
		if (name === 'fontMono') return designTokens.fonts?.mono ?? fallback;
		if (name === 'radius') return designTokens.radius ?? fallback;
		if (name === 'spacing') return designTokens.spacing ?? fallback;
		return fallback;
	}

	function buildRootCss(): string {
		const lines: string[] = [];
		for (const [name, value] of Object.entries(pendingDesignSystemChanges)) {
			if (COLOR_TOKEN_KEYS.includes(name)) {
				lines.push(`  --${name}: ${value};`);
			} else if (name === 'radius') {
				lines.push(`  --radius: ${value};`);
			}
		}
		if (lines.length === 0) return '';
		return `:root {\n${lines.join('\n')}\n}`;
	}

	function scheduleDesignApply(): void {
		if (designApplyTimer) clearTimeout(designApplyTimer);
		designSaving = true;
		designApplyTimer = setTimeout(() => {
			designApplyTimer = null;
			if (Object.keys(pendingDesignSystemChanges).length === 0) {
				designSaving = false;
				return;
			}
			onApplyDesignSystem({
				framework: framework ?? 'unknown',
				changes: { ...pendingDesignSystemChanges }
			});
			pendingDesignSystemChanges = {};
			designSaving = false;
		}, APPLY_DEBOUNCE_MS);
	}

	function setToken(name: string, value: string): void {
		pendingDesignSystemChanges = { ...pendingDesignSystemChanges, [name]: value };
		onRootCssChange(buildRootCss());
		scheduleDesignApply();
	}

	function resetDesignSystem(): void {
		if (designApplyTimer) {
			clearTimeout(designApplyTimer);
			designApplyTimer = null;
		}
		designSaving = false;
		pendingDesignSystemChanges = {};
		onRootCssChange('');
	}

	// Clean up dangling timers when the panel unmounts.
	$effect(() => {
		return () => {
			if (elementApplyTimer) clearTimeout(elementApplyTimer);
			if (designApplyTimer) clearTimeout(designApplyTimer);
		};
	});

	// --- Friendly presets --------------------------------------------------

	const WEIGHT_CHIPS = [
		{ label: 'Light', value: '300' },
		{ label: 'Regular', value: '400' },
		{ label: 'Medium', value: '500' },
		{ label: 'Bold', value: '700' }
	];

	const ROUNDNESS_CHIPS = [
		{ label: 'None', value: '0' },
		{ label: 'Subtle', value: '4' },
		{ label: 'Rounded', value: '12' },
		{ label: 'Pill', value: '9999' }
	];

	const BORDER_THICKNESS_CHIPS = [
		{ label: 'None', value: '0' },
		{ label: 'Thin', value: '1' },
		{ label: 'Medium', value: '2' },
		{ label: 'Thick', value: '4' }
	];

	const BORDER_STYLE_CHIPS = [
		{ label: 'Solid', value: 'solid' },
		{ label: 'Dashed', value: 'dashed' },
		{ label: 'Dotted', value: 'dotted' }
	];

	const DISPLAY_CHIPS = [
		{ label: 'Block', value: 'block' },
		{ label: 'Row', value: 'flex' },
		{ label: 'Grid', value: 'grid' },
		{ label: 'Inline', value: 'inline' },
		{ label: 'Hidden', value: 'none' }
	];

	const ALIGN_ICONS: { value: string; label: string; icon: Component }[] = [
		{ value: 'left', label: 'Left', icon: TextAlignStart as unknown as Component },
		{ value: 'center', label: 'Center', icon: TextAlignCenter as unknown as Component },
		{ value: 'right', label: 'Right', icon: TextAlignEnd as unknown as Component },
		{ value: 'justify', label: 'Justify', icon: TextAlignJustify as unknown as Component }
	];

	// Swatches: pulled from designTokens colors if present, plus friendly fallback set.
	// Aligned with the Jatayu palette: neutrals + accent + status colours.
	const FALLBACK_SWATCHES = ['#0B0B0C', '#F5F5F7', '#EDEDED', '#6EE7B7', '#FF6B6B', '#FACC15'];
	const colorSwatches = $derived(
		designTokens?.colors ? Object.values(designTokens.colors).slice(0, 6) : FALLBACK_SWATCHES
	);

	// Per-side toggles
	let paddingPerSide = $state(false);
	let marginPerSide = $state(false);
	let roundnessPerCorner = $state(false);
	let showAdvanced = $state(false);

	// --- Helpers -----------------------------------------------------------

	function setAllSides(prefix: 'padding' | 'margin', px: number): void {
		const v = `${px}px`;
		setStyleMany({
			[`${prefix}Top`]: v,
			[`${prefix}Right`]: v,
			[`${prefix}Bottom`]: v,
			[`${prefix}Left`]: v
		});
	}

	function setAllRadius(px: string): void {
		const v = `${px}px`;
		setStyleMany({
			borderTopLeftRadius: v,
			borderTopRightRadius: v,
			borderBottomLeftRadius: v,
			borderBottomRightRadius: v
		});
	}

	function setAllBorderWidth(px: number): void {
		const v = `${px}px`;
		setStyleMany({
			borderTopWidth: v,
			borderRightWidth: v,
			borderBottomWidth: v,
			borderLeftWidth: v
		});
	}

	function setAllBorderStyle(style: string): void {
		setStyleMany({
			borderTopStyle: style,
			borderRightStyle: style,
			borderBottomStyle: style,
			borderLeftStyle: style
		});
	}

	function setAllBorderColor(color: string): void {
		setStyleMany({
			borderTopColor: color,
			borderRightColor: color,
			borderBottomColor: color,
			borderLeftColor: color
		});
	}

	// All-sides read helpers (take the Top edge as representative).
	const paddingAll = $derived(parsePx(readStyle('paddingTop'), 0));
	const marginAll = $derived(parsePx(readStyle('marginTop'), 0));
	const radiusAll = $derived(parsePx(readStyle('borderTopLeftRadius'), 0));
	const borderWidthAll = $derived(parsePx(readStyle('borderTopWidth'), 0));

	// Design system derived pixel values (used in markup — placed here
	// because {@const} can't be an immediate child of a plain element).
	const designRadiusPx = $derived(parsePx(readToken('radius', '10px'), 10));
	const designSpacingPx = $derived(parsePx(readToken('spacing', '16px'), 16));

	// Does the selected element look like it contains text? (heuristic)
	const hasText: boolean = $derived(
		!!selection &&
			(selection.tagName.toLowerCase() === 'p' ||
				selection.tagName.toLowerCase() === 'span' ||
				selection.tagName.toLowerCase().startsWith('h') ||
				!!(selection.outerHTMLSnippet && !selection.outerHTMLSnippet.endsWith('/>')))
	);
</script>

<div
	class="flex h-full w-80 flex-col overflow-hidden border-l border-border-subtle bg-surface-2"
	data-testid="property-panel"
>
	<!-- Header bar -->
	<div
		class="flex shrink-0 items-center gap-2 border-b border-border-subtle bg-surface-2 px-4 py-3"
	>
		<Sparkles size={14} strokeWidth={2} aria-hidden="true" />
		<span class="font-sans text-sm font-medium text-foreground">Inspector</span>
		<div class="flex-1"></div>
		{#if elementSaving || designSaving}
			<span
				class="text-xs italic text-muted"
				data-testid="property-panel-saving"
				title="Saving changes to source…"
			>
				Saving…
			</span>
		{/if}
		<button
			type="button"
			onclick={activeTab === 'element' ? resetElement : resetDesignSystem}
			disabled={activeTab === 'element'
				? Object.keys(pendingElementChanges).length === 0
				: Object.keys(pendingDesignSystemChanges).length === 0}
			aria-label="Reset changes"
			title="Reset changes"
			class="rounded p-1 text-muted hover:bg-background hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
		>
			<RotateCcw size={14} strokeWidth={2} aria-hidden="true" />
		</button>
		{#if onClose}
			<button
				type="button"
				onclick={onClose}
				aria-label="Close inspector"
				class="rounded p-1 text-muted hover:bg-background hover:text-foreground"
			>
				<X size={14} strokeWidth={2} aria-hidden="true" />
			</button>
		{/if}
	</div>

	<!-- Friendly tab strip -->
	<div class="flex shrink-0 gap-1 border-b border-border-subtle bg-surface-2 px-3 py-2">
		<button
			type="button"
			onclick={() => (activeTab = 'element')}
			class="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors {activeTab ===
			'element'
				? 'bg-accent/10 text-accent'
				: 'text-muted hover:text-foreground'}"
			disabled={selection == null}
			data-testid="property-panel-tab-element"
		>
			Element
		</button>
		<button
			type="button"
			onclick={() => (activeTab = 'design')}
			class="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors {activeTab ===
			'design'
				? 'bg-accent/10 text-accent'
				: 'text-muted hover:text-foreground'}"
			data-testid="property-panel-tab-design"
		>
			Design System
		</button>
	</div>

	<!-- Scrollable content -->
	<div class="flex-1 space-y-5 overflow-y-auto px-4 py-4">
		{#if activeTab === 'element'}
			{#if selection == null}
				<div
					class="flex flex-col items-center justify-center gap-2 py-12 text-center text-sm text-muted"
				>
					<span class="italic"
						>Turn on the picker and click something in the preview to edit it.</span
					>
				</div>
			{:else}
				<!-- Text -->
				<details open={hasText} class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Text</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						<!-- Size -->
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="text-xs text-muted">Size</span>
								<span class="text-xs text-foreground">{parsePx(readStyle('fontSize'), 16)}px</span>
							</div>
							<input
								type="range"
								min="8"
								max="128"
								value={parsePx(readStyle('fontSize'), 16)}
								oninput={(e) => setStyle('fontSize', `${(e.target as HTMLInputElement).value}px`)}
								class="w-full accent-accent"
								aria-label="Text size"
							/>
						</div>
						<!-- Weight -->
						<div>
							<div class="mb-1 text-xs text-muted">Weight</div>
							<div class="flex flex-wrap gap-1.5">
								{#each WEIGHT_CHIPS as chip}
									{@const active = readStyle('fontWeight', '400') === chip.value}
									<button
										type="button"
										onclick={() => setStyle('fontWeight', chip.value)}
										class="rounded-full border px-2.5 py-1 text-xs font-medium transition-colors
											{active
											? 'border-accent/40 bg-accent/10 text-accent'
											: 'border-border-subtle text-muted hover:border-border-strong hover:text-foreground'}"
									>
										{chip.label}
									</button>
								{/each}
							</div>
						</div>
						<!-- Text color -->
						<div>
							<div class="mb-1 text-xs text-muted">Text color</div>
							<div class="flex items-center gap-1.5">
								{#each colorSwatches as sw}
									{@const active = readStyle('color').toLowerCase() === sw.toLowerCase()}
									<button
										type="button"
										onclick={() => setStyle('color', sw)}
										class="h-6 w-6 rounded-full border-2 transition-all {active
											? 'border-accent'
											: 'border-transparent hover:border-border-strong'}"
										style="background-color: {sw};"
										aria-label="Use color {sw}"
									></button>
								{/each}
								<label
									class="flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-dashed border-border-strong text-xs text-muted hover:text-foreground"
									title="Custom color"
								>
									+
									<input
										type="color"
										class="sr-only"
										value={readStyle('color', '#000000')}
										oninput={(e) => setStyle('color', (e.target as HTMLInputElement).value)}
									/>
								</label>
							</div>
						</div>
						<!-- Alignment -->
						<div>
							<div class="mb-1 text-xs text-muted">Alignment</div>
							<div class="flex gap-1 rounded-md border border-border-subtle p-0.5">
								{#each ALIGN_ICONS as a}
									{@const active = readStyle('textAlign', 'left') === a.value}
									{@const AlignIcon = a.icon}
									<button
										type="button"
										onclick={() => setStyle('textAlign', a.value)}
										class="flex flex-1 items-center justify-center rounded px-2 py-1 transition-colors
											{active ? 'bg-accent/10 text-accent' : 'text-muted hover:text-foreground'}"
										aria-label={a.label}
										title={a.label}
									>
										<AlignIcon size={14} strokeWidth={2} aria-hidden="true" />
									</button>
								{/each}
							</div>
						</div>
						{#if showAdvanced}
							<div>
								<div class="mb-1 flex items-center justify-between">
									<span class="text-xs text-muted">Line height</span>
									<span class="text-xs text-foreground">{readStyle('lineHeight', '1.5')}</span>
								</div>
								<input
									type="range"
									min="0.8"
									max="3"
									step="0.05"
									value={Number(readStyle('lineHeight', '1.5')) || 1.5}
									oninput={(e) => setStyle('lineHeight', (e.target as HTMLInputElement).value)}
									class="w-full accent-accent"
								/>
							</div>
							<div>
								<div class="mb-1 flex items-center justify-between">
									<span class="text-xs text-muted">Letter spacing</span>
									<span class="text-xs text-foreground"
										>{parsePx(readStyle('letterSpacing'), 0)}px</span
									>
								</div>
								<input
									type="range"
									min="-5"
									max="20"
									value={parsePx(readStyle('letterSpacing'), 0)}
									oninput={(e) =>
										setStyle('letterSpacing', `${(e.target as HTMLInputElement).value}px`)}
									class="w-full accent-accent"
								/>
							</div>
						{/if}
					</div>
				</details>

				<!-- Background -->
				<details open class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Background</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						<div>
							<div class="mb-1 text-xs text-muted">Color</div>
							<div class="flex items-center gap-1.5">
								<button
									type="button"
									onclick={() => setStyle('backgroundColor', 'transparent')}
									class="rounded-full border border-border-subtle px-2.5 py-1 text-xs text-muted hover:border-border-strong hover:text-foreground"
								>
									None
								</button>
								{#each colorSwatches as sw}
									{@const active = readStyle('backgroundColor').toLowerCase() === sw.toLowerCase()}
									<button
										type="button"
										onclick={() => setStyle('backgroundColor', sw)}
										class="h-6 w-6 rounded-full border-2 transition-all {active
											? 'border-accent'
											: 'border-transparent hover:border-border-strong'}"
										style="background-color: {sw};"
										aria-label="Use background {sw}"
									></button>
								{/each}
								<label
									class="flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-dashed border-border-strong text-xs text-muted hover:text-foreground"
									title="Custom color"
								>
									+
									<input
										type="color"
										class="sr-only"
										value={readStyle('backgroundColor', '#ffffff')}
										oninput={(e) =>
											setStyle('backgroundColor', (e.target as HTMLInputElement).value)}
									/>
								</label>
							</div>
						</div>
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="text-xs text-muted">Opacity</span>
								<span class="text-xs text-foreground">
									{Math.round(Number(readStyle('opacity', '1')) * 100)}%
								</span>
							</div>
							<input
								type="range"
								min="0"
								max="100"
								value={Math.round(Number(readStyle('opacity', '1')) * 100)}
								oninput={(e) =>
									setStyle('opacity', String(Number((e.target as HTMLInputElement).value) / 100))}
								class="w-full accent-accent"
							/>
						</div>
					</div>
				</details>

				<!-- Spacing -->
				<details open class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Spacing</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-4">
						<!-- Inside spacing (padding) -->
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="text-xs text-muted">Inside spacing</span>
								<button
									type="button"
									onclick={() => (paddingPerSide = !paddingPerSide)}
									class="text-xs text-muted hover:text-foreground"
								>
									{paddingPerSide ? 'All sides' : 'Per side'}
								</button>
							</div>
							{#if !paddingPerSide}
								<div class="flex items-center gap-2">
									<input
										type="range"
										min="0"
										max="64"
										value={paddingAll}
										oninput={(e) =>
											setAllSides('padding', Number((e.target as HTMLInputElement).value))}
										class="flex-1 accent-accent"
									/>
									<span class="w-10 text-right text-xs text-foreground">{paddingAll}px</span>
								</div>
							{:else}
								<div class="space-y-2">
									{#each [['Top', 'paddingTop'], ['Right', 'paddingRight'], ['Bottom', 'paddingBottom'], ['Left', 'paddingLeft']] as [label, prop]}
										<div>
											<div class="mb-0.5 flex items-center justify-between">
												<span class="text-xs text-muted">{label}</span>
												<span class="text-xs text-foreground">{parsePx(readStyle(prop), 0)}px</span>
											</div>
											<input
												type="range"
												min="0"
												max="64"
												value={parsePx(readStyle(prop), 0)}
												oninput={(e) => setStyle(prop, `${(e.target as HTMLInputElement).value}px`)}
												class="w-full accent-accent"
											/>
										</div>
									{/each}
								</div>
							{/if}
						</div>
						<!-- Outside spacing (margin) -->
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="text-xs text-muted">Outside spacing</span>
								<button
									type="button"
									onclick={() => (marginPerSide = !marginPerSide)}
									class="text-xs text-muted hover:text-foreground"
								>
									{marginPerSide ? 'All sides' : 'Per side'}
								</button>
							</div>
							{#if !marginPerSide}
								<div class="flex items-center gap-2">
									<input
										type="range"
										min="0"
										max="64"
										value={marginAll}
										oninput={(e) =>
											setAllSides('margin', Number((e.target as HTMLInputElement).value))}
										class="flex-1 accent-accent"
									/>
									<span class="w-10 text-right text-xs text-foreground">{marginAll}px</span>
								</div>
							{:else}
								<div class="space-y-2">
									{#each [['Top', 'marginTop'], ['Right', 'marginRight'], ['Bottom', 'marginBottom'], ['Left', 'marginLeft']] as [label, prop]}
										<div>
											<div class="mb-0.5 flex items-center justify-between">
												<span class="text-xs text-muted">{label}</span>
												<span class="text-xs text-foreground">{parsePx(readStyle(prop), 0)}px</span>
											</div>
											<input
												type="range"
												min="0"
												max="64"
												value={parsePx(readStyle(prop), 0)}
												oninput={(e) => setStyle(prop, `${(e.target as HTMLInputElement).value}px`)}
												class="w-full accent-accent"
											/>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				</details>

				<!-- Corners -->
				<details class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Corners</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="text-xs text-muted">Roundness</span>
								<button
									type="button"
									onclick={() => (roundnessPerCorner = !roundnessPerCorner)}
									class="text-xs text-muted hover:text-foreground"
								>
									{roundnessPerCorner ? 'All corners' : 'Per corner'}
								</button>
							</div>
							{#if !roundnessPerCorner}
								<div class="flex flex-wrap gap-1.5">
									{#each ROUNDNESS_CHIPS as chip}
										{@const active = radiusAll === Number(chip.value)}
										<button
											type="button"
											onclick={() => setAllRadius(chip.value)}
											class="rounded-full border px-2.5 py-1 text-xs font-medium transition-colors
												{active
												? 'border-accent/40 bg-accent/10 text-accent'
												: 'border-border-subtle text-muted hover:border-border-strong hover:text-foreground'}"
										>
											{chip.label}
										</button>
									{/each}
								</div>
								<div class="mt-2 flex items-center gap-2">
									<input
										type="range"
										min="0"
										max="48"
										value={Math.min(radiusAll, 48)}
										oninput={(e) => setAllRadius((e.target as HTMLInputElement).value)}
										class="flex-1 accent-accent"
									/>
									<span class="w-10 text-right text-xs text-foreground">{radiusAll}px</span>
								</div>
							{:else}
								<div class="space-y-2">
									{#each [['Top-left', 'borderTopLeftRadius'], ['Top-right', 'borderTopRightRadius'], ['Bottom-right', 'borderBottomRightRadius'], ['Bottom-left', 'borderBottomLeftRadius']] as [label, prop]}
										<div>
											<div class="mb-0.5 flex items-center justify-between">
												<span class="text-xs text-muted">{label}</span>
												<span class="text-xs text-foreground">{parsePx(readStyle(prop), 0)}px</span>
											</div>
											<input
												type="range"
												min="0"
												max="48"
												value={parsePx(readStyle(prop), 0)}
												oninput={(e) => setStyle(prop, `${(e.target as HTMLInputElement).value}px`)}
												class="w-full accent-accent"
											/>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				</details>

				<!-- Border -->
				<details class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Border</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						<div>
							<div class="mb-1 text-xs text-muted">Thickness</div>
							<div class="flex flex-wrap gap-1.5">
								{#each BORDER_THICKNESS_CHIPS as chip}
									{@const active = borderWidthAll === Number(chip.value)}
									<button
										type="button"
										onclick={() => setAllBorderWidth(Number(chip.value))}
										class="rounded-full border px-2.5 py-1 text-xs font-medium transition-colors
											{active
											? 'border-accent/40 bg-accent/10 text-accent'
											: 'border-border-subtle text-muted hover:border-border-strong hover:text-foreground'}"
									>
										{chip.label}
									</button>
								{/each}
							</div>
						</div>
						<div>
							<div class="mb-1 text-xs text-muted">Color</div>
							<div class="flex items-center gap-1.5">
								{#each colorSwatches as sw}
									{@const active = readStyle('borderTopColor').toLowerCase() === sw.toLowerCase()}
									<button
										type="button"
										onclick={() => setAllBorderColor(sw)}
										class="h-6 w-6 rounded-full border-2 transition-all {active
											? 'border-accent'
											: 'border-transparent hover:border-border-strong'}"
										style="background-color: {sw};"
										aria-label="Use border color {sw}"
									></button>
								{/each}
								<label
									class="flex h-6 w-6 cursor-pointer items-center justify-center rounded-full border border-dashed border-border-strong text-xs text-muted hover:text-foreground"
								>
									+
									<input
										type="color"
										class="sr-only"
										value={readStyle('borderTopColor', '#000000')}
										oninput={(e) => setAllBorderColor((e.target as HTMLInputElement).value)}
									/>
								</label>
							</div>
						</div>
						<div>
							<div class="mb-1 text-xs text-muted">Style</div>
							<div class="flex flex-wrap gap-1.5">
								{#each BORDER_STYLE_CHIPS as chip}
									{@const active = readStyle('borderTopStyle', 'solid') === chip.value}
									<button
										type="button"
										onclick={() => setAllBorderStyle(chip.value)}
										class="rounded-full border px-2.5 py-1 text-xs font-medium transition-colors
											{active
											? 'border-accent/40 bg-accent/10 text-accent'
											: 'border-border-subtle text-muted hover:border-border-strong hover:text-foreground'}"
									>
										{chip.label}
									</button>
								{/each}
							</div>
						</div>
					</div>
				</details>

				<!-- Size -->
				<details class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Size</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="text-xs text-muted">Width</span>
								<button
									type="button"
									onclick={() => setStyle('width', 'auto')}
									class="text-xs text-muted hover:text-foreground"
								>
									Auto
								</button>
							</div>
							<div class="flex items-center gap-2">
								<input
									type="range"
									min="0"
									max="1000"
									value={parsePx(readStyle('width'), 0)}
									oninput={(e) => setStyle('width', `${(e.target as HTMLInputElement).value}px`)}
									class="flex-1 accent-accent"
								/>
								<span class="w-14 text-right text-xs text-foreground">
									{readStyle('width', 'auto')}
								</span>
							</div>
						</div>
						<div>
							<div class="mb-1 flex items-center justify-between">
								<span class="text-xs text-muted">Height</span>
								<button
									type="button"
									onclick={() => setStyle('height', 'auto')}
									class="text-xs text-muted hover:text-foreground"
								>
									Auto
								</button>
							</div>
							<div class="flex items-center gap-2">
								<input
									type="range"
									min="0"
									max="1000"
									value={parsePx(readStyle('height'), 0)}
									oninput={(e) => setStyle('height', `${(e.target as HTMLInputElement).value}px`)}
									class="flex-1 accent-accent"
								/>
								<span class="w-14 text-right text-xs text-foreground">
									{readStyle('height', 'auto')}
								</span>
							</div>
						</div>
						{#if showAdvanced}
							<div class="flex items-center gap-2">
								<label class="flex-1 text-xs text-muted">
									Min width
									<input
										type="text"
										value={readStyle('minWidth')}
										oninput={(e) => setStyle('minWidth', (e.target as HTMLInputElement).value)}
										class="mt-0.5 w-full rounded border border-border-subtle bg-background px-2 py-1 text-xs text-foreground"
									/>
								</label>
								<label class="flex-1 text-xs text-muted">
									Max width
									<input
										type="text"
										value={readStyle('maxWidth')}
										oninput={(e) => setStyle('maxWidth', (e.target as HTMLInputElement).value)}
										class="mt-0.5 w-full rounded border border-border-subtle bg-background px-2 py-1 text-xs text-foreground"
									/>
								</label>
							</div>
							<div>
								<div class="mb-1 text-xs text-muted">Display mode</div>
								<div class="flex flex-wrap gap-1.5">
									{#each DISPLAY_CHIPS as chip}
										{@const active = readStyle('display', 'block') === chip.value}
										<button
											type="button"
											onclick={() => setStyle('display', chip.value)}
											class="rounded-full border px-2.5 py-1 text-xs font-medium transition-colors
												{active
												? 'border-accent/40 bg-accent/10 text-accent'
												: 'border-border-subtle text-muted hover:border-border-strong hover:text-foreground'}"
										>
											{chip.label}
										</button>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				</details>

				<!-- Show advanced toggle -->
				<button
					type="button"
					onclick={() => (showAdvanced = !showAdvanced)}
					class="text-xs text-muted underline-offset-2 hover:text-foreground hover:underline"
				>
					{showAdvanced ? 'Hide advanced options' : 'Show advanced options'}
				</button>
			{/if}
		{:else}
			<!-- Design System tab -->
			{#if designTokens == null}
				<div
					class="flex flex-col items-center justify-center gap-2 py-12 text-center text-sm text-muted"
				>
					<Palette size={22} strokeWidth={1.5} aria-hidden="true" />
					<span class="italic">Design system will load when you open a project.</span>
				</div>
			{:else}
				<!-- Colors -->
				<details open class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Colors</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-2">
						{#each COLOR_TOKENS as c}
							<label class="flex items-center gap-3">
								<span
									class="h-6 w-6 shrink-0 rounded-full border border-border-subtle"
									style="background-color: {readToken(c.key, '#000000')};"
									aria-hidden="true"
								></span>
								<span class="flex-1 text-sm text-foreground">{c.label}</span>
								<input
									type="color"
									value={readToken(c.key, '#000000')}
									oninput={(e) => setToken(c.key, (e.target as HTMLInputElement).value)}
									class="h-7 w-10 cursor-pointer rounded border border-border-subtle bg-background"
									aria-label="Change {c.label}"
								/>
							</label>
						{/each}
					</div>
				</details>

				<!-- Fonts -->
				<details class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Fonts</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						{#each [['Body font', 'fontSans', 'system-ui'], ['Heading font', 'fontSerif', 'Georgia'], ['Code font', 'fontMono', 'Berkeley Mono']] as [label, key, fallback]}
							<div>
								<div class="mb-1 text-xs text-muted">{label}</div>
								<input
									type="text"
									value={readToken(key, fallback)}
									oninput={(e) => setToken(key, (e.target as HTMLInputElement).value)}
									class="w-full rounded border border-border-subtle bg-background px-3 py-2 text-sm text-foreground"
									style="font-family: {readToken(key, fallback)};"
								/>
							</div>
						{/each}
					</div>
				</details>

				<!-- Roundness -->
				<details class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Roundness</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						<div class="flex items-center justify-between text-xs">
							<span class="text-muted">Sharp</span>
							<span class="text-foreground">{designRadiusPx}px</span>
							<span class="text-muted">Very round</span>
						</div>
						<input
							type="range"
							min="0"
							max="24"
							value={designRadiusPx}
							oninput={(e) => setToken('radius', `${(e.target as HTMLInputElement).value}px`)}
							class="w-full accent-accent"
						/>
						<div
							class="mx-auto h-12 w-24 border border-border-subtle bg-accent/15"
							style="border-radius: {designRadiusPx}px;"
						></div>
					</div>
				</details>

				<!-- Spacing scale -->
				<details class="group">
					<summary class="flex cursor-pointer list-none items-center justify-between py-1">
						<span class="text-sm font-medium text-foreground">Spacing</span>
						<span class="transition-transform group-open:rotate-180">
							<ChevronDown size={14} strokeWidth={2} aria-hidden="true" />
						</span>
					</summary>
					<div class="mt-2 space-y-3">
						<div class="flex items-center justify-between text-xs">
							<span class="text-muted">Compact</span>
							<span class="text-foreground">{designSpacingPx}px</span>
							<span class="text-muted">Spacious</span>
						</div>
						<input
							type="range"
							min="4"
							max="48"
							value={designSpacingPx}
							oninput={(e) => setToken('spacing', `${(e.target as HTMLInputElement).value}px`)}
							class="w-full accent-accent"
						/>
						<div class="flex items-center justify-center" style="gap: {designSpacingPx}px;">
							<div class="h-10 w-10 rounded bg-accent/20"></div>
							<div class="h-10 w-10 rounded bg-accent/20"></div>
						</div>
					</div>
				</details>
			{/if}
		{/if}
	</div>
</div>
