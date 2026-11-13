<script lang="ts">
	import type { ToolCallMessage, PlanState } from '$services/sse';
	import { planState as planStateStore } from '$services/sse';
	import { type ServerCategory, getServerCategory, getActionLabel } from '$lib/utils/toolLabels';
	import {
		computerPanelWidth,
		computerPanelPinned,
		computerPanelVncActive,
		closeComputerPanel,
		closeComputerPanelMobile
	} from '$stores/computerPanel';
	import SearchResultsRenderer from '$components/toolRenderers/SearchResultsRenderer.svelte';
	import ImageSearchRenderer from '$components/toolRenderers/ImageSearchRenderer.svelte';
	import TerminalRenderer from '$components/toolRenderers/TerminalRenderer.svelte';
	import DiffRenderer from '$components/toolRenderers/DiffRenderer.svelte';
	import CodeViewerRenderer from '$components/toolRenderers/CodeViewerRenderer.svelte';
	import FileTreeRenderer from '$components/toolRenderers/FileTreeRenderer.svelte';
	import FileStatusRenderer from '$components/toolRenderers/FileStatusRenderer.svelte';
	import BrowserRenderer from '$components/toolRenderers/BrowserRenderer.svelte';
	import DownloadRenderer from '$components/toolRenderers/DownloadRenderer.svelte';
	import PreviewRenderer from '$components/toolRenderers/PreviewRenderer.svelte';
	import ProjectRenderer from '$components/toolRenderers/ProjectRenderer.svelte';
	import KmRenderer from '$components/toolRenderers/KmRenderer.svelte';
	import ToolCanvas from '$components/toolRenderers/ToolCanvas.svelte';
	import InfoButton from '$components/ui/InfoButton.svelte';
	import { onDestroy } from 'svelte';
	import { tooltip } from '$lib/actions/tooltip';

	type Props = {
		toolCalls: ToolCallMessage[];
		agentName?: string;
		vncAvailable?: boolean;
		vncUrl?: string;
		onVncToggle?: () => void;
		mobile?: boolean;
		framed?: boolean;
	};

	let {
		toolCalls,
		agentName = 'Agent',
		vncAvailable = false,
		vncUrl = '',
		onVncToggle,
		mobile = false,
		framed = false
	}: Props = $props();

	let panelWidth = $state(480);
	let isResizing = $state(false);
	let startX = 0;
	let startWidth = 0;
	let selectedToolIndex = $state(-1);
	let pinned = $state(false);
	let isFullscreen = $state(false);

	let planExpanded = $state(false);
	let planData = $state<PlanState | null>(null);

	let vncActive = $state(false);
	let vncIframeLoaded = $state(false);

	const unsubWidth = computerPanelWidth.subscribe((w) => {
		panelWidth = w;
	});
	const unsubPinned = computerPanelPinned.subscribe((p) => {
		pinned = p;
	});
	const unsubPlan = planStateStore.subscribe((p) => {
		planData = p;
	});
	const unsubVnc = computerPanelVncActive.subscribe((v) => {
		vncActive = v;
		if (!v) vncIframeLoaded = false;
	});

	onDestroy(() => {
		unsubWidth();
		unsubPinned();
		unsubPlan();
		unsubVnc();
	});

	$effect(() => {
		if (toolCalls.length === 0) {
			selectedToolIndex = -1;
			return;
		}
		if (!pinned || selectedToolIndex < 0 || selectedToolIndex >= toolCalls.length) {
			selectedToolIndex = toolCalls.length - 1;
		}
	});

	let activeToolCall = $derived.by(() => {
		if (selectedToolIndex < 0 || selectedToolIndex >= toolCalls.length) return null;
		return toolCalls[selectedToolIndex];
	});

	let activeCategory = $derived.by<ServerCategory>(() => {
		if (!activeToolCall) return 'unknown';
		return getServerCategory(activeToolCall.toolName, activeToolCall.args);
	});

	let activeToolLabel = $derived.by(() => {
		if (!activeToolCall) return '';
		return getActionLabel(activeToolCall.toolName, activeToolCall.args);
	});

	let activeToolBrief = $derived.by(() => {
		if (!activeToolCall) return '';
		if (typeof activeToolCall.args._exo_tool_brief === 'string')
			return activeToolCall.args._exo_tool_brief;
		return '';
	});

	let categoryIcon = $derived.by(() => {
		const icons: Record<string, string> = {
			search: 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z',
			terminal: 'M4 17l6-5-6-5M12 19h8',
			browser: 'M2 3h20v14H2zM8 21h8M12 17v4',
			file: 'M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9zM13 2v7h7',
			code: 'M16 18l6-6-6-6M8 6l-6 6 6 6',
			download: 'M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3',
			vision: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 9a3 3 0 100 6 3 3 0 000-6z',
			audio:
				'M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3zM19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8'
		};
		return icons[activeCategory] || icons['file'];
	});

	let categoryLabel = $derived.by(() => {
		const labels: Record<string, string> = {
			search: 'Search',
			terminal: 'Terminal',
			browser: 'Browser',
			file: 'Files',
			code: 'Code',
			download: 'Download',
			vision: 'Vision',
			audio: 'Audio',
			web: 'Web',
			slides: 'Slides',
			mobile: 'Mobile',
			media: 'Media',
			plan: 'Plan',
			reading: 'Reading',
			reasoning: 'Reasoning',
			artifact: 'Artifact',
			unknown: 'Tool Result'
		};
		return labels[activeCategory] || 'Tool Result';
	});

	function isRecord(value: unknown): value is Record<string, unknown> {
		return typeof value === 'object' && value !== null && !Array.isArray(value);
	}

	function parsePlanPhases(value: unknown): PlanState['phases'] {
		if (!Array.isArray(value)) return [];
		return value
			.map((phase, index) => {
				if (typeof phase === 'string') {
					return {
						id: `phase_${index + 1}`,
						description: phase,
						status: 'pending' as const
					};
				}
				if (!isRecord(phase)) return null;
				const status = phase.status;
				return {
					id: typeof phase.id === 'string' && phase.id ? phase.id : `phase_${index + 1}`,
					description: typeof phase.description === 'string' ? phase.description : '',
					status:
						status === 'in_progress' || status === 'completed' ? status : ('pending' as const),
					startedAt: typeof phase.startedAt === 'string' ? phase.startedAt : undefined,
					completedAt: typeof phase.completedAt === 'string' ? phase.completedAt : undefined
				};
			})
			.filter((phase): phase is PlanState['phases'][number] => phase !== null);
	}

	function normalisePlanState(value: unknown): PlanState | null {
		if (!isRecord(value)) return null;
		const goal = typeof value.goal === 'string' ? value.goal : '';
		const phases = parsePlanPhases(value.phases);
		const currentFromCamel = value.currentPhaseId;
		const currentFromSnake = value.current_phase_id;
		const currentPhaseId =
			typeof currentFromCamel === 'string'
				? currentFromCamel
				: typeof currentFromSnake === 'string'
					? currentFromSnake
					: '';

		if (!goal && phases.length === 0) return null;
		return { goal, phases, currentPhaseId };
	}

	function extractPlanFromToolResult(value: unknown): PlanState | null {
		const direct = normalisePlanState(value);
		if (direct) return direct;
		if (!isRecord(value)) return null;
		return normalisePlanState(value.message);
	}

	function isPlanTool(toolName: string, args: Record<string, unknown>): boolean {
		return (
			toolName === 'mcp_update_plan' ||
			toolName === 'mcp_advance_plan' ||
			toolName === 'mcp_get_plan' ||
			(toolName === 'plan' && typeof args.action === 'string')
		);
	}

	function getPlanFromToolCalls(calls: ToolCallMessage[]): PlanState | null {
		for (let i = calls.length - 1; i >= 0; i--) {
			const call = calls[i];
			if (!isPlanTool(call.toolName, call.args)) continue;

			const fromResult = extractPlanFromToolResult(call.result);
			if (fromResult) return fromResult;

			const fromArgs = normalisePlanState(call.args);
			if (fromArgs) return fromArgs;
		}
		return null;
	}

	let effectivePlanData = $derived.by(() => planData ?? getPlanFromToolCalls(toolCalls));

	let completedObjectives = $derived.by(() =>
		effectivePlanData
			? effectivePlanData.phases.filter((phase) => phase.status === 'completed')
			: []
	);
	let currentObjective = $derived.by(() =>
		effectivePlanData
			? (effectivePlanData.phases.find((phase) => phase.status === 'in_progress') ?? null)
			: null
	);
	let remainingObjectives = $derived.by(() =>
		effectivePlanData ? effectivePlanData.phases.filter((phase) => phase.status === 'pending') : []
	);
	let totalObjectives = $derived.by(() =>
		effectivePlanData ? effectivePlanData.phases.length : 0
	);
	let planHeadline = $derived.by(() => {
		if (currentObjective?.description) return currentObjective.description;
		if (effectivePlanData?.goal) return effectivePlanData.goal;
		return 'No plan available';
	});
	let planMeta = $derived.by(() => {
		if (!effectivePlanData || totalObjectives === 0)
			return 'No plan available for this conversation yet';
		if (!currentObjective && remainingObjectives.length === 0) return 'Plan complete';
		return `${completedObjectives.length}/${totalObjectives} objectives completed`;
	});

	let planProgress = $derived.by(() => {
		if (!effectivePlanData || effectivePlanData.phases.length === 0) return 0;
		return Math.round((completedObjectives.length / effectivePlanData.phases.length) * 100);
	});

	function moveToPrevTool(): void {
		if (toolCalls.length === 0) return;
		selectedToolIndex = Math.max(0, selectedToolIndex - 1);
		computerPanelPinned.set(true);
		pinned = true;
	}

	function moveToNextTool(): void {
		if (toolCalls.length === 0) return;
		selectedToolIndex = Math.min(toolCalls.length - 1, selectedToolIndex + 1);
		computerPanelPinned.set(true);
		pinned = true;
	}

	function handleResizeStart(e: MouseEvent): void {
		isResizing = true;
		startX = e.clientX;
		startWidth = panelWidth;
		e.preventDefault();
	}

	function handleResizeMove(e: MouseEvent): void {
		if (!isResizing) return;
		const diff = startX - e.clientX;
		const newWidth = Math.max(320, Math.min(800, startWidth + diff));
		panelWidth = newWidth;
		computerPanelWidth.set(newWidth);
	}

	function handleResizeEnd(): void {
		isResizing = false;
	}

	function toggleFullscreen(): void {
		isFullscreen = !isFullscreen;
	}

	function isImageSearchTool(toolName: string, args?: Record<string, unknown>): boolean {
		return (
			toolName === 'mcp_search_google_images' ||
			toolName === 'mcp_image_search' ||
			(toolName === 'search' && args?.action === 'images')
		);
	}

	function isTerminalTool(category: ServerCategory, toolName: string): boolean {
		return category === 'terminal' || category === 'code' || toolName === 'shell';
	}

	function isDiffTool(toolName: string, args?: Record<string, unknown>): boolean {
		return toolName === 'file' && args?.action === 'edit';
	}

	function isFileTreeTool(toolName: string, args?: Record<string, unknown>): boolean {
		return (toolName === 'file' && args?.action === 'view') || toolName === 'match';
	}

	function isFileStatusTool(toolName: string, args?: Record<string, unknown>): boolean {
		if (toolName !== 'file') return false;
		const a = typeof args?.action === 'string' ? (args.action as string) : '';
		return a === 'write' || a === 'append';
	}

	function isCodeViewerTool(toolName: string, args?: Record<string, unknown>): boolean {
		if (toolName === 'file') return args?.action === 'read' || args?.action === 'read_resource';
		return toolName === 'skill';
	}

	function isBrowserTool(toolName: string): boolean {
		return toolName === 'browser' || toolName.startsWith('browser_');
	}

	function isPreviewTool(toolName: string): boolean {
		return toolName === 'expose';
	}

	function isDownloadTool(toolName: string, args?: Record<string, unknown>): boolean {
		return toolName === 'file' && args?.action === 'download';
	}

	function isProjectTool(toolName: string): boolean {
		return (
			toolName === 'web_init' ||
			toolName === 'web_project' ||
			toolName === 'mobile_init' ||
			toolName === 'mobile_project'
		);
	}

	function isKmTool(toolName: string): boolean {
		return toolName.startsWith('km_');
	}
</script>

<svelte:window onmousemove={handleResizeMove} onmouseup={handleResizeEnd} />

<div
	class="computer-panel flex h-full flex-col overflow-hidden {mobile || framed
		? 'border-0 bg-background'
		: 'border-l border-border-subtle bg-background'} {isFullscreen && !mobile
		? 'fixed inset-0 z-[9990]'
		: ''}"
	style={mobile || isFullscreen
		? ''
		: `width: ${panelWidth}px; min-width: 320px; max-width: 800px;`}
	data-testid="computer-panel"
>
	<!-- Resize handle (desktop only) -->
	{#if !mobile && !isFullscreen}
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="absolute -left-[3px] top-0 z-10 h-full w-[5px] cursor-col-resize select-none transition-colors {isResizing
				? 'bg-accent/40'
				: 'hover:bg-accent/20'}"
			onmousedown={handleResizeStart}
			role="separator"
			aria-orientation="vertical"
			aria-label="Resize activity panel"
			tabindex="-1"
			data-testid="panel-resize-handle"
		>
			<div
				class="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 {isResizing ? 'bg-accent' : ''}"
			></div>
		</div>
	{/if}

	<!-- Header -->
	<div
		class="flex shrink-0 items-center gap-2 border-b border-border-subtle px-3 py-2"
		data-testid="panel-header"
	>
		<!-- Category icon + title -->
		<div class="flex items-center gap-2 min-w-0">
			<div class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent/[0.08]">
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
					class="text-accent"
				>
					<path d={categoryIcon} />
				</svg>
			</div>
			<div class="min-w-0">
				<h2 class="truncate text-[14px] font-medium text-foreground">{agentName}'s Computer</h2>
			</div>
		</div>

		<InfoButton context="computer" />
		<div class="flex-1"></div>

		<!-- Header actions -->
		<div class="flex items-center gap-0.5">
			{#if vncAvailable}
				<button
					onclick={() => onVncToggle?.()}
					class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition-all {vncActive
						? 'bg-accent/10 text-accent'
						: 'text-muted hover:bg-surface-2 hover:text-foreground'}"
					use:tooltip={vncActive ? 'Back to tool result' : 'Open streaming desktop'}
					aria-label="Toggle desktop view"
					data-testid="panel-vnc-toggle"
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
						<rect width="20" height="14" x="2" y="3" rx="2" />
						<line x1="8" x2="16" y1="21" y2="21" />
						<line x1="12" x2="12" y1="17" y2="21" />
					</svg>
				</button>
			{/if}

			{#if !mobile}
				<button
					onclick={toggleFullscreen}
					class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted transition-all hover:bg-surface-2 hover:text-foreground"
					use:tooltip={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
					aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
					data-testid="panel-fullscreen-toggle"
				>
					{#if isFullscreen}
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
							<path d="M8 3v3a2 2 0 0 1-2 2H3" />
							<path d="M21 8h-3a2 2 0 0 1-2-2V3" />
							<path d="M3 16h3a2 2 0 0 1 2 2v3" />
							<path d="M16 21v-3a2 2 0 0 1 2-2h3" />
						</svg>
					{:else}
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
							<path d="M8 3H5a2 2 0 0 0-2 2v3" />
							<path d="M21 8V5a2 2 0 0 0-2-2h-3" />
							<path d="M3 16v3a2 2 0 0 0 2 2h3" />
							<path d="M16 21h3a2 2 0 0 0 2-2v-3" />
						</svg>
					{/if}
				</button>
			{/if}

			<button
				onclick={mobile ? closeComputerPanelMobile : closeComputerPanel}
				class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted transition-all hover:bg-surface-2 hover:text-foreground"
				use:tooltip={{
					text: 'Close panel',
					position: 'left',
					shortcut: mobile ? '' : 'Ctrl+Shift+C'
				}}
				aria-label="Close panel"
				data-testid="panel-close-button"
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
					<path d="M18 6 6 18" />
					<path d="m6 6 12 12" />
				</svg>
			</button>
		</div>
	</div>

	<!-- Tool info bar -->
	{#if activeToolCall}
		<div class="shrink-0 border-b border-border-subtle px-3 py-1.5">
			<div class="flex items-center gap-1.5">
				<span
					class="inline-flex items-center rounded-md bg-surface px-1.5 py-0.5 text-[10.5px] font-medium text-subtle"
					>{categoryLabel}</span
				>
				<span class="truncate text-[11.5px] text-subtle">{activeToolLabel}</span>
			</div>
			{#if activeToolBrief}
				<p class="mt-0.5 line-clamp-1 text-[10.5px] text-muted">{activeToolBrief}</p>
			{/if}
		</div>
	{/if}

	<!-- VNC viewer -->
	{#if vncActive}
		<div class="relative flex-1 overflow-hidden bg-background" data-testid="panel-vnc-viewer">
			{#if vncUrl}
				{#if !vncIframeLoaded}
					<div
						class="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-background"
					>
						<div class="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/[0.08]">
							<svg
								class="h-5 w-5 animate-spin text-accent/60"
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
							>
								<circle
									class="opacity-25"
									cx="12"
									cy="12"
									r="10"
									stroke="currentColor"
									stroke-width="4"
								></circle>
								<path
									class="opacity-75"
									fill="currentColor"
									d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
								></path>
							</svg>
						</div>
						<p class="text-xs font-medium text-muted">Connecting to sandbox desktop...</p>
					</div>
				{/if}
				<iframe
					src={vncUrl}
					title="Sandbox desktop VNC viewer"
					class="h-full w-full border-0"
					sandbox="allow-scripts allow-same-origin"
					onload={() => {
						vncIframeLoaded = true;
					}}
					data-testid="panel-vnc-iframe"
				></iframe>
			{:else}
				<div class="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
					<div class="flex h-12 w-12 items-center justify-center rounded-xl bg-surface">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="20"
							height="20"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-muted"
						>
							<rect width="20" height="14" x="2" y="3" rx="2" />
							<line x1="8" x2="16" y1="21" y2="21" />
							<line x1="12" x2="12" y1="17" y2="21" />
						</svg>
					</div>
					<div>
						<p class="text-sm font-medium text-subtle">Desktop not available</p>
						<p class="mt-1 text-xs text-muted">The streaming view is currently unavailable</p>
					</div>
					<button
						onclick={() => onVncToggle?.()}
						class="rounded-lg bg-surface px-4 py-2 text-xs font-medium text-subtle transition-all hover:bg-surface-2"
					>
						Back to tool result
					</button>
				</div>
			{/if}
		</div>
	{:else}
		<!-- Tool content area -->
		<div class="min-h-0 flex-1 overflow-hidden p-2" data-testid="panel-content">
			{#if activeToolCall}
				<div
					class="flex h-full flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface"
				>
					<!-- Content header tab -->
					<div class="flex items-center gap-2 border-b border-border-subtle px-3 py-1.5">
						<div
							class="h-1.5 w-1.5 rounded-full {activeToolCall.status === 'running'
								? 'animate-pulse bg-warning'
								: activeToolCall.error
									? 'bg-accent'
									: 'bg-success'}"
						></div>
						<span class="text-[11.5px] font-medium text-subtle">{categoryLabel}</span>
						{#if toolCalls.length > 1}
							<span class="text-[10.5px] text-muted"
								>{Math.max(0, selectedToolIndex) + 1} of {toolCalls.length}</span
							>
						{/if}
					</div>

					<div class="min-h-0 flex-1 overflow-auto" data-testid="panel-tool-content">
						{#if activeToolCall.status === 'running'}
							<!-- Running skeleton -->
							<div class="space-y-3 p-4">
								<div class="flex items-center gap-2">
									<div class="h-2 w-2 animate-pulse rounded-full bg-accent/30"></div>
									<div class="h-3 w-2/3 animate-pulse rounded-md bg-surface"></div>
								</div>
								<div class="h-3 w-4/5 animate-pulse rounded-md bg-surface"></div>
								<div class="h-3 w-1/2 animate-pulse rounded-md bg-surface"></div>
								<div class="h-3 w-3/4 animate-pulse rounded-md bg-surface"></div>
							</div>
						{:else if activeToolCall.error}
							<div class="m-2 rounded-lg border border-accent/15 bg-accent/[0.04] p-3">
								<div class="flex items-start gap-2">
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
										class="mt-0.5 shrink-0 text-accent/60"
									>
										<circle cx="12" cy="12" r="10" />
										<line x1="15" x2="9" y1="9" y2="15" />
										<line x1="9" x2="15" y1="9" y2="15" />
									</svg>
									<p class="text-xs leading-relaxed text-accent/70">{activeToolCall.error}</p>
								</div>
							</div>
						{:else if activeToolCall.result}
							{#if isBrowserTool(activeToolCall.toolName)}
								<BrowserRenderer toolCall={activeToolCall} />
							{:else if isDownloadTool(activeToolCall.toolName, activeToolCall.args)}
								<DownloadRenderer toolCall={activeToolCall} />
							{:else if isTerminalTool(activeCategory, activeToolCall.toolName)}
								<TerminalRenderer toolCall={activeToolCall} />
							{:else if activeCategory === 'search' && isImageSearchTool(activeToolCall.toolName, activeToolCall.args)}
								<ImageSearchRenderer toolCall={activeToolCall} />
							{:else if activeCategory === 'search'}
								<SearchResultsRenderer toolCall={activeToolCall} />
							{:else if isDiffTool(activeToolCall.toolName, activeToolCall.args)}
								<DiffRenderer toolCall={activeToolCall} />
							{:else if isCodeViewerTool(activeToolCall.toolName, activeToolCall.args)}
								<CodeViewerRenderer toolCall={activeToolCall} />
							{:else if isFileTreeTool(activeToolCall.toolName, activeToolCall.args)}
								<FileTreeRenderer toolCall={activeToolCall} />
							{:else if isFileStatusTool(activeToolCall.toolName, activeToolCall.args)}
								<FileStatusRenderer toolCall={activeToolCall} />
							{:else if isPreviewTool(activeToolCall.toolName)}
								<PreviewRenderer toolCall={activeToolCall} />
							{:else if isProjectTool(activeToolCall.toolName)}
								<ProjectRenderer toolCall={activeToolCall} />
							{:else if isKmTool(activeToolCall.toolName)}
								<KmRenderer toolCall={activeToolCall} />
							{:else}
								<ToolCanvas toolCall={activeToolCall} />
							{/if}
						{:else}
							<div class="flex h-32 items-center justify-center">
								<p class="text-xs italic text-muted">Waiting for result...</p>
							</div>
						{/if}
					</div>
				</div>
			{:else}
				<!-- Empty state -->
				<div
					class="flex h-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-background"
				>
					<div class="flex h-10 w-10 items-center justify-center rounded-xl bg-surface">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="18"
							height="18"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-muted"
						>
							<rect width="20" height="14" x="2" y="3" rx="2" />
							<line x1="8" x2="16" y1="21" y2="21" />
							<line x1="12" x2="12" y1="17" y2="21" />
						</svg>
					</div>
					<div class="text-center">
						<p class="text-xs font-medium text-muted">No tool result yet</p>
						<p class="mt-0.5 text-[10.5px] text-muted">
							Results will appear here as the agent works
						</p>
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Navigation bar -->
	{#if toolCalls.length > 0}
		<div class="flex shrink-0 items-center gap-1.5 border-t border-border-subtle px-2 py-1.5">
			<button
				type="button"
				onclick={moveToPrevTool}
				disabled={selectedToolIndex <= 0}
				class="flex h-7 w-7 items-center justify-center rounded-lg text-subtle transition-all hover:bg-surface-2 hover:text-foreground disabled:opacity-30 disabled:cursor-default disabled:hover:bg-transparent"
				aria-label="Previous tool call"
				use:tooltip={'Previous result'}
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
					<path d="m15 18-6-6 6-6" />
				</svg>
			</button>

			<!-- Progress track -->
			<div class="flex-1 px-1">
				<div class="relative h-1 overflow-hidden rounded-full bg-border-subtle">
					<div
						class="absolute inset-y-0 left-0 rounded-full bg-accent transition-all duration-300 ease-out"
						style="width: {((Math.max(0, selectedToolIndex) + 1) / toolCalls.length) * 100}%"
					></div>
				</div>
			</div>

			<button
				type="button"
				onclick={moveToNextTool}
				disabled={selectedToolIndex >= toolCalls.length - 1}
				class="flex h-7 w-7 items-center justify-center rounded-lg text-subtle transition-all hover:bg-surface-2 hover:text-foreground disabled:opacity-30 disabled:cursor-default disabled:hover:bg-transparent"
				aria-label="Next tool call"
				use:tooltip={'Next result'}
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
					<path d="m9 18 6-6-6-6" />
				</svg>
			</button>

			<span class="ml-0.5 tabular-nums text-[10.5px] font-medium text-muted"
				>{Math.max(0, selectedToolIndex) + 1}/{toolCalls.length}</span
			>
		</div>
	{/if}

	<!-- Plan overview -->
	<div class="shrink-0 border-t border-border-subtle p-2" data-testid="panel-plan-overview">
		<div class="overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-sm">
			<button
				onclick={() => (planExpanded = !planExpanded)}
				class="group relative flex w-full items-start gap-2.5 overflow-hidden px-3 py-2.5 text-left transition-colors hover:bg-background/60"
				data-testid="panel-plan-toggle"
			>
				<div
					class="absolute inset-x-0 top-0 h-10 bg-gradient-to-r from-accent/[0.08] via-transparent to-accent/[0.06]"
				></div>

				<!-- Progress ring -->
				<div class="relative mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center">
					<svg class="h-7 w-7 -rotate-90" viewBox="0 0 20 20">
						<circle
							cx="10"
							cy="10"
							r="8"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							class="text-border-subtle"
						/>
						<circle
							cx="10"
							cy="10"
							r="8"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							class="text-accent transition-all duration-500"
							stroke-dasharray={2 * Math.PI * 8}
							stroke-dashoffset={2 * Math.PI * 8 * (1 - planProgress / 100)}
							stroke-linecap="round"
						/>
					</svg>
					<span class="absolute text-[8.5px] font-medium text-subtle">{planProgress}%</span>
				</div>

				<div class="relative min-w-0 flex-1">
					<div class="flex items-center gap-1.5">
						<span class="text-[10.5px] font-medium uppercase tracking-wide text-muted"
							>Conversation Plan</span
						>
						<span
							class="rounded-full border border-border-subtle bg-background px-1.5 py-0.5 text-[9.5px] font-medium text-subtle"
							>{completedObjectives.length}/{totalObjectives}</span
						>
					</div>
					<p class="mt-0.5 line-clamp-2 text-[11.5px] font-medium leading-relaxed text-subtle">
						{planHeadline}
					</p>
					<p class="mt-1 text-[10.5px] text-muted">{planMeta}</p>
				</div>

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
					class="relative mt-1 shrink-0 text-muted transition-transform duration-200 group-hover:text-subtle"
					class:rotate-180={planExpanded}
				>
					<path d="m6 9 6 6 6-6" />
				</svg>
			</button>

			{#if planExpanded}
				<div
					class="border-t border-border-subtle bg-background/50 px-3 py-2.5"
					data-testid="panel-plan-details"
				>
					<div class="space-y-3 text-[11.5px]">
						{#if effectivePlanData?.goal}
							<div class="rounded-lg border border-border-subtle bg-background px-2 py-1.5">
								<p class="text-[10.5px] font-medium uppercase tracking-wide text-muted">Goal</p>
								<p class="mt-1 leading-relaxed text-subtle">{effectivePlanData.goal}</p>
							</div>
						{/if}

						{#if !effectivePlanData}
							<div class="rounded-lg border border-border-subtle bg-background px-2 py-2">
								<p class="text-[11.5px] text-muted">
									No plan available yet for this conversation. It will appear here when the agent
									creates one.
								</p>
							</div>
						{/if}

						<!-- In progress -->
						{#if currentObjective}
							<div>
								<p class="mb-1.5 text-[10.5px] font-medium uppercase tracking-wide text-muted">
									In Progress
								</p>
								<div class="flex items-start gap-1.5 rounded-md bg-accent/[0.06] px-2 py-1.5">
									<div class="mt-1 h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent"></div>
									<span class="font-medium text-subtle">{currentObjective.description}</span>
								</div>
							</div>
						{/if}

						<!-- Remaining -->
						{#if remainingObjectives.length > 0}
							<div>
								<p class="mb-1.5 text-[10.5px] font-medium uppercase tracking-wide text-muted">
									Up Next
								</p>
								<div class="space-y-1">
									{#each remainingObjectives as phase (phase.id)}
										<div class="flex items-start gap-1.5">
											<div class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-border-subtle"></div>
											<span class="text-muted">{phase.description}</span>
										</div>
									{/each}
								</div>
							</div>
						{/if}

						<!-- Completed -->
						{#if completedObjectives.length > 0}
							<div>
								<p class="mb-1.5 text-[10.5px] font-medium uppercase tracking-wide text-muted">
									Completed
								</p>
								<div class="space-y-1">
									{#each completedObjectives as phase (phase.id)}
										<div class="flex items-start gap-1.5">
											<svg
												xmlns="http://www.w3.org/2000/svg"
												width="12"
												height="12"
												viewBox="0 0 24 24"
												fill="none"
												stroke="currentColor"
												stroke-width="2.5"
												stroke-linecap="round"
												stroke-linejoin="round"
												class="mt-0.5 shrink-0 text-success"
											>
												<path d="M20 6 9 17l-5-5" />
											</svg>
											<span class="text-muted line-through decoration-border-subtle"
												>{phase.description}</span
											>
										</div>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>

<style>
	.computer-panel {
		animation: panelSlideIn 0.25s ease-out;
	}

	@keyframes panelSlideIn {
		from {
			opacity: 0;
			transform: translateX(12px);
		}
		to {
			opacity: 1;
			transform: translateX(0);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.computer-panel {
			animation: none;
		}
	}
</style>
