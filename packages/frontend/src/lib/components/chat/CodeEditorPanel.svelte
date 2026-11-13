<script lang="ts">
	import { onDestroy } from 'svelte';
	import type { ToolCallMessage, PlanState } from '$services/sse';
	import { planState as planStateStore } from '$services/sse';
	import { getServerCategory } from '$lib/utils/toolLabels';
	import FileExplorer from './FileExplorer.svelte';
	import NewTabPage from './NewTabPage.svelte';
	import ToolCanvas from '$components/toolRenderers/ToolCanvas.svelte';
	import ArtifactCanvas from '$components/toolRenderers/ArtifactCanvas.svelte';
	import LazyCodeMirrorEditor from './LazyCodeMirrorEditor.svelte';
	import {
		selectedFilePath,
		startFileWatch,
		stopFileWatch,
		onFileEvent
	} from '$stores/fileExplorer';
	import {
		editorTabs,
		activeTabPath,
		agentExecuting,
		editorWordWrap,
		openTab,
		closeTab,
		updateTabContent,
		markTabDirty,
		saveTab,
		resolveConflict,
		type EditorTab as EditorTabType
	} from '$stores/editorTabs';
	import { tooltip } from '$lib/actions/tooltip';
	import { collapsePane } from '$stores/workspaceLayout';
	import { computerPanelToolIndex, computerPanelPinned } from '$stores/computerPanel';
	import {
		openPanelTabs as panelTabsStore,
		activePanelTab as activePanelTabStore,
		newTabPageActive as newTabPageActiveStore,
		ALL_PANEL_TABS,
		addPanelTab,
		jumpToPanelTab,
		closePanelTabById,
		openNewTabPage as storeOpenNewTab,
		closeNewTabPage as storeCloseNewTab,
		type PanelTab
	} from '$stores/panelTabs';

	type Props = {
		toolCalls: ToolCallMessage[];
		conversationId?: string;
	};

	let { toolCalls, conversationId = '' }: Props = $props();
	let planData = $state<PlanState | null>(null);
	let planExpanded = $state(false);
	const unsubPlan = planStateStore.subscribe((v) => (planData = v));

	// Panel tab state from store
	let openPanelTabs: PanelTab[] = $state([]);
	let newTabPageActive = $state(false);
	let activeTab: PanelTab = $state('preview');
	const unsubPanelTabs = panelTabsStore.subscribe((v) => (openPanelTabs = v));
	const unsubPanelActive = activePanelTabStore.subscribe((v) => (activeTab = v));
	const unsubPanelNewTab = newTabPageActiveStore.subscribe((v) => (newTabPageActive = v));

	// Editor tabs state
	let tabs: EditorTabType[] = $state([]);
	let activeFile: string | null = $state(null);
	let isAgentRunning = $state(false);
	let wordWrap = $state(false);

	const unsubTabs = editorTabs.subscribe((v) => (tabs = v));
	const unsubActiveTab = activeTabPath.subscribe((v) => (activeFile = v));
	const unsubAgentExec = agentExecuting.subscribe((v) => (isAgentRunning = v));
	const unsubWordWrap = editorWordWrap.subscribe((v) => (wordWrap = v));

	// Reload editor tab content when sandbox files change
	const unsubFileEvent = onFileEvent((event) => {
		if (event.type === 'file_modified') {
			const match = tabs.find((t) => t.path === event.path);
			if (match && conversationId) {
				import('$api/sandbox').then(({ readSandboxFile }) => {
					readSandboxFile(conversationId, event.path)
						.then((resp) => {
							updateTabContent(event.path, resp.content);
						})
						.catch(() => {
							// Failed to reload
						});
				});
			}
		}
	});

	// Watch for file selection from file explorer — open as editor tab
	const unsubSelected = selectedFilePath.subscribe((path) => {
		if (path && conversationId) {
			addPanelTab('code');
			openTab(conversationId, path);
		}
	});

	// Start/stop file watch SSE based on whether a file-related tab is open in the canvas.
	const FILE_TABS: PanelTab[] = ['code', 'files'];
	$effect(() => {
		const needsWatch = conversationId && openPanelTabs.some((tab) => FILE_TABS.includes(tab));
		if (needsWatch) {
			startFileWatch(conversationId);
		} else {
			stopFileWatch();
		}
	});

	let existingTabDefs = $derived(
		ALL_PANEL_TABS.filter((t) => openPanelTabs.includes(t.id)).map(
			({ id, label, description }) => ({ id, label, description })
		)
	);
	let suggestedTabDefs = $derived(
		ALL_PANEL_TABS.filter((t) => !openPanelTabs.includes(t.id)).map(
			({ id, label, description }) => ({ id, label, description })
		)
	);

	// Active tool call — only when user explicitly clicked a tool (pinned)
	let showToolCanvas = $derived($computerPanelPinned);
	let activeToolCall = $derived.by(() => {
		if (!showToolCanvas) return null;
		const idx = $computerPanelToolIndex;
		if (idx >= 0 && idx < toolCalls.length) return toolCalls[idx];
		return null;
	});

	function closePanelTab(e: MouseEvent, id: PanelTab): void {
		e.stopPropagation();
		closePanelTabById(id);
	}

	function closeNewTabPage(e: MouseEvent): void {
		e.stopPropagation();
		storeCloseNewTab();
	}

	onDestroy(() => {
		unsubTabs();
		unsubActiveTab();
		unsubAgentExec();
		unsubWordWrap();
		unsubSelected();
		unsubFileEvent();
		unsubPlan();
		unsubPanelTabs();
		unsubPanelActive();
		unsubPanelNewTab();
		stopFileWatch();
	});

	function handleCloseTab(e: MouseEvent, path: string): void {
		e.stopPropagation();
		closeTab(path);
	}

	function handleTabClick(path: string): void {
		activeTabPath.set(path);
	}

	function toggleWordWrap(): void {
		editorWordWrap.update((v) => !v);
	}

	function getFileIcon(path: string): string {
		const ext = path.split('.').pop()?.toLowerCase() ?? '';
		const iconMap: Record<string, string> = {
			ts: 'TS',
			tsx: 'TX',
			js: 'JS',
			jsx: 'JX',
			py: 'PY',
			html: '< >',
			css: '#',
			json: '{}',
			md: 'MD',
			svelte: 'SV',
			go: 'GO',
			rs: 'RS',
			java: 'JV',
			rb: 'RB',
			php: 'PH',
			sql: 'SQ',
			sh: '$',
			yml: 'YM',
			yaml: 'YM',
			xml: 'XM',
			c: 'C',
			cpp: 'C+',
			h: 'H',
			kt: 'KT'
		};
		return iconMap[ext] || path.split('.').pop()?.toUpperCase()?.slice(0, 2) || '?';
	}

	function getFileName(path: string): string {
		return path.split('/').pop() ?? path;
	}

	let activeTabData = $derived.by(() => {
		if (!activeFile) return null;
		return tabs.find((t) => t.path === activeFile) ?? null;
	});

	function handleEditorChange(content: string): void {
		if (!activeFile || !conversationId) return;
		markTabDirty(conversationId, activeFile, content);
	}

	function handleEditorSave(): void {
		if (!activeFile || !conversationId) return;
		saveTab(conversationId, activeFile);
	}

	function handleResolveConflict(path: string, keep: 'mine' | 'theirs'): void {
		if (!conversationId) return;
		resolveConflict(conversationId, path, keep);
	}

	function isDatabaseTool(toolName: string): boolean {
		return toolName.startsWith('mcp_sql');
	}

	let databaseTool = $derived.by(() => {
		for (let i = toolCalls.length - 1; i >= 0; i--) {
			const call = toolCalls[i];
			if (isDatabaseTool(call.toolName)) return call;
		}
		return null;
	});

	type SqlRow = Record<string, unknown>;
	let databaseRows = $derived.by(() => {
		if (!databaseTool || !databaseTool.result) return [] as SqlRow[];
		const result = databaseTool.result;
		if (Array.isArray(result)) {
			return result.filter((value): value is SqlRow => typeof value === 'object' && value !== null);
		}
		if (typeof result === 'object' && result !== null) {
			const obj = result as Record<string, unknown>;
			if (Array.isArray(obj.rows)) {
				return obj.rows.filter(
					(value): value is SqlRow => typeof value === 'object' && value !== null
				);
			}
		}
		return [] as SqlRow[];
	});

	let databaseColumns = $derived.by(() => {
		if (databaseRows.length === 0) return [] as string[];
		return Object.keys(databaseRows[0]).slice(0, 8);
	});

	// All artifact tool calls for the artifact tab, most recent first
	let artifactToolCalls = $derived.by(() => {
		return toolCalls.filter((tc) => tc.toolName === 'artifact' && tc.result).reverse();
	});

	let latestArtifactTool = $derived.by(() => {
		return artifactToolCalls.length > 0 ? artifactToolCalls[0] : null;
	});

	let latestPreviewTool = $derived.by(() => {
		for (let i = toolCalls.length - 1; i >= 0; i--) {
			if (toolCalls[i].toolName === 'expose_port' && toolCalls[i].result) return toolCalls[i];
		}
		return null;
	});

	let previewUrl = $derived.by(() => {
		if (!latestPreviewTool) return '';
		const r = latestPreviewTool.result as Record<string, unknown> | undefined;
		return (r?.url || '') as string;
	});

	let previewLabel = $derived.by(() => {
		if (!latestPreviewTool) return '';
		const r = latestPreviewTool.result as Record<string, unknown> | undefined;
		return (r?.label || '') as string;
	});

	let latestEditorTool = $derived.by(() => {
		for (let i = toolCalls.length - 1; i >= 0; i--) {
			const call = toolCalls[i];
			const category = getServerCategory(call.toolName, call.args);
			if (category === 'web' || category === 'mobile') return call;
		}
		return null;
	});

	let planPhases = $derived.by(() => (planData ? planData.phases : []));
	let completedPlanObjectives = $derived.by(() =>
		planPhases.filter((phase) => phase.status === 'completed')
	);
	let currentPlanObjective = $derived.by(
		() => planPhases.find((phase) => phase.status === 'in_progress') ?? null
	);
	let upcomingPlanObjectives = $derived.by(() =>
		planPhases.filter((phase) => phase.status === 'pending')
	);
	let totalPlanObjectives = $derived.by(() => planPhases.length);
	let hasPlan = $derived.by(() => totalPlanObjectives > 0);
	let summaryPlanObjective = $derived.by(() => {
		if (currentPlanObjective) return currentPlanObjective;
		if (upcomingPlanObjectives.length > 0) return upcomingPlanObjectives[0];
		if (completedPlanObjectives.length > 0)
			return completedPlanObjectives[completedPlanObjectives.length - 1];
		return null;
	});

	function getPlanPhaseLabel(phase: PlanState['phases'][number], idx: number): string {
		const description = phase.description?.trim();
		if (description) return description;

		const idLabel = phase.id.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
		if (idLabel && !/^phase\s*\d+$/i.test(idLabel)) return idLabel;

		return `Step ${idx + 1}`;
	}

	let summaryPlanObjectiveLabel = $derived.by(() => {
		if (!summaryPlanObjective) return '';
		const idx = planPhases.findIndex((phase) => phase.id === summaryPlanObjective.id);
		return getPlanPhaseLabel(summaryPlanObjective, idx >= 0 ? idx : 0);
	});

	let planHeadline = $derived.by(() => {
		if (!hasPlan) return 'No plan available';
		if (summaryPlanObjectiveLabel) return summaryPlanObjectiveLabel;
		const goal = planData?.goal?.trim();
		if (goal) return goal;
		return 'Task in progress';
	});
	let planCountLabel = $derived.by(() =>
		hasPlan ? `${completedPlanObjectives.length} / ${totalPlanObjectives}` : ''
	);
</script>

<div
	class="relative flex h-full w-full flex-col overflow-hidden bg-background"
	data-testid="code-editor-panel"
>
	<!-- Canvas header: tabs + actions -->
	<div
		class="flex h-[var(--header-height)] shrink-0 items-center overflow-hidden border-b border-border-subtle"
		data-testid="canvas-tab-bar"
	>
		<div class="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto px-2">
			<!-- Panel tabs (dynamically added/removed) -->
			{#each openPanelTabs as panelId (panelId)}
				{@const def = ALL_PANEL_TABS.find((t) => t.id === panelId)}
				{#if def}
					<div
						class="canvas-tab group {!newTabPageActive && activeTab === panelId
							? 'canvas-tab-active'
							: 'canvas-tab-inactive'}"
					>
						<button
							type="button"
							onclick={() => {
								computerPanelPinned.set(false);
								jumpToPanelTab(panelId);
							}}
							class="flex min-w-0 items-center gap-1.5"
						>
							{#if def.icon === 'code'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="shrink-0"
									><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg
								>
							{:else if def.icon === 'monitor'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="shrink-0"
									><rect width="20" height="14" x="2" y="3" rx="2" /><line
										x1="8"
										x2="16"
										y1="21"
										y2="21"
									/><line x1="12" x2="12" y1="17" y2="21" /></svg
								>
							{:else if def.icon === 'database'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="shrink-0"
									><ellipse cx="12" cy="5" rx="9" ry="3" /><path
										d="M3 5V19A9 3 0 0 0 21 19V5"
									/><path d="M3 12A9 3 0 0 0 21 12" /></svg
								>
							{:else if def.icon === 'settings'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="shrink-0"
									><path
										d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
									/><circle cx="12" cy="12" r="3" /></svg
								>
							{:else if def.icon === 'files'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="shrink-0"
									><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
										d="M14 2v4a2 2 0 0 0 2 2h4"
									/></svg
								>
							{:else if def.icon === 'vnc'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="16"
									height="16"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="shrink-0"
									><rect width="20" height="14" x="2" y="3" rx="2" /><path d="M12 17v4" /><path
										d="M8 21h8"
									/><circle cx="12" cy="10" r="2" /></svg
								>
							{/if}
							<span class="truncate">{def.label}</span>
						</button>
						{#if openPanelTabs.length > 1}
							<button
								type="button"
								onclick={(e) => closePanelTab(e, panelId)}
								class="shrink-0 rounded p-0.5 opacity-0 transition-all hover:bg-border-strong group-hover:opacity-100 {activeTab ===
								panelId
									? 'opacity-60'
									: ''}"
								aria-label="Close {def.label}"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="10"
									height="10"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2.5"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg
								>
							</button>
						{/if}
					</div>
				{/if}
			{/each}

			<!-- Open file tabs (within code context) -->
			{#each tabs as tab (tab.path)}
				<div
					class="canvas-tab group {!newTabPageActive &&
					activeTab === 'code' &&
					tab.path === activeFile
						? 'canvas-tab-active'
						: 'canvas-tab-inactive'}"
				>
					<button
						type="button"
						onclick={() => {
							addPanelTab('code');
							handleTabClick(tab.path);
						}}
						class="flex min-w-0 items-center gap-1.5"
					>
						<span
							class="shrink-0 font-mono text-[9.5px] font-medium uppercase leading-none opacity-40"
						>
							{getFileIcon(tab.path)}
						</span>
						<span class="max-w-[100px] truncate">
							{getFileName(tab.path)}
						</span>
						{#if tab.dirty}
							<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"></span>
						{/if}
					</button>
					<button
						type="button"
						onclick={(e) => handleCloseTab(e, tab.path)}
						class="shrink-0 rounded p-0.5 opacity-0 transition-all hover:bg-border-strong group-hover:opacity-100 {activeTab ===
							'code' && tab.path === activeFile
							? 'opacity-60'
							: ''}"
						aria-label="Close {getFileName(tab.path)}"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="10"
							height="10"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2.5"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg
						>
					</button>
				</div>
			{/each}

			<!-- New tab tab -->
			{#if newTabPageActive}
				<div class="canvas-tab group canvas-tab-active">
					<span class="truncate">New tab</span>
					{#if openPanelTabs.length > 0}
						<button
							type="button"
							onclick={closeNewTabPage}
							class="shrink-0 rounded p-0.5 opacity-60 transition-all hover:bg-border-strong"
							aria-label="Close new tab"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="10"
								height="10"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2.5"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg
							>
						</button>
					{/if}
				</div>
			{/if}

			<!-- + button -->
			<button
				type="button"
				onclick={storeOpenNewTab}
				class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-subtle"
				aria-label="New tab"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d="M5 12h14" />
					<path d="M12 5v14" />
				</svg>
			</button>
		</div>

		<!-- Right-side actions -->
		<div class="flex shrink-0 items-center gap-1.5 px-3">
			{#if activeTab === 'code' && activeTabData}
				{#if activeTabData.saveStatus === 'saving'}
					<span class="text-[14px] text-muted">Saving...</span>
				{:else if activeTabData.saveStatus === 'saved'}
					<span class="text-[14px] text-success/70">Saved</span>
				{:else if activeTabData.saveStatus === 'error'}
					<span class="text-[14px] text-error/70" title={activeTabData.saveError ?? ''}>Error</span>
				{/if}
				<button
					type="button"
					onclick={toggleWordWrap}
					class="rounded-md p-1 text-muted transition-colors hover:bg-surface-2 hover:text-foreground {wordWrap
						? 'bg-border text-foreground'
						: ''}"
					aria-label="Toggle word wrap"
					use:tooltip={'Word wrap'}
				>
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
					>
						<path d="M3 6h18" />
						<path d="M3 12h15a3 3 0 1 1 0 6h-4" />
						<polyline points="16 16 14 18 16 20" />
						<path d="M3 18h7" />
					</svg>
				</button>
				{#if isAgentRunning}
					<span class="rounded-md bg-warning/10 px-1.5 py-0.5 text-[14px] font-medium text-warning"
						>Read-only</span
					>
				{/if}
			{/if}
			{#if latestEditorTool}
				<button
					class="flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1 text-[14px] font-medium text-white transition-all hover:opacity-90"
				>
					Publish
				</button>
			{/if}
			<!-- Close canvas panel -->
			<button
				type="button"
				onclick={() => collapsePane('editor')}
				class="hidden items-center justify-center rounded-md p-1 text-foreground transition-colors hover:bg-surface-2 hover:text-accent lg:flex"
				use:tooltip={{ text: 'Close canvas', position: 'bottom' }}
				aria-label="Close canvas"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="16"
					height="16"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<rect width="18" height="18" x="3" y="3" rx="2" />
					<path d="M15 3v18" />
				</svg>
			</button>
		</div>
	</div>

	<!-- Tab content -->
	<div class="min-h-0 flex-1 overflow-hidden">
		{#if activeToolCall && !newTabPageActive}
			<div class="flex h-full min-h-0 flex-col overflow-hidden">
				<div class="min-h-0 flex-1 overflow-hidden">
					<ToolCanvas toolCall={activeToolCall} />
				</div>

				<div class="shrink-0 border-t border-border-subtle p-2" data-testid="preview-plan-overview">
					<div class="overflow-hidden rounded-xl border border-border-subtle bg-surface">
						<button
							type="button"
							onclick={() => {
								if (hasPlan) planExpanded = !planExpanded;
							}}
							class="flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors {hasPlan
								? 'hover:bg-surface-2'
								: ''}"
							aria-expanded={hasPlan ? planExpanded : undefined}
							data-testid="preview-plan-toggle"
						>
							{#if hasPlan && planExpanded}
								<p class="text-[14px] font-medium text-foreground">Task progress</p>
							{:else}
								<div class="flex min-w-0 flex-1 items-center gap-2">
									{#if summaryPlanObjective?.status === 'completed'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="14"
											height="14"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2.5"
											stroke-linecap="round"
											stroke-linejoin="round"
											class="shrink-0 text-success"
										>
											<path d="M20 6 9 17l-5-5" />
										</svg>
									{:else if summaryPlanObjective?.status === 'in_progress'}
										<div class="relative h-2.5 w-2.5 shrink-0">
											<span class="absolute inset-0 animate-ping rounded-full bg-accent/30"></span>
											<span class="absolute inset-[2px] rounded-full bg-accent"></span>
										</div>
									{:else if hasPlan}
										<div
											class="h-2.5 w-2.5 shrink-0 rounded-full border border-border-strong"
										></div>
									{:else}
										<div class="h-2.5 w-2.5 shrink-0 rounded-full bg-border-subtle"></div>
									{/if}
									<p class="truncate text-[14px] font-medium text-foreground">{planHeadline}</p>
								</div>
							{/if}

							<div class="ml-auto flex shrink-0 items-center gap-1.5">
								{#if hasPlan}
									<span class="text-[14px] tabular-nums text-subtle">{planCountLabel}</span>
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
										class="text-subtle transition-transform duration-200"
										class:rotate-180={planExpanded}
									>
										<path d="m6 9 6 6 6-6" />
									</svg>
								{/if}
							</div>
						</button>

						{#if hasPlan && planExpanded}
							<div
								class="border-t border-border-subtle px-3 pb-2 pt-1.5"
								data-testid="preview-plan-details"
							>
								<div class="space-y-1">
									{#each planPhases as phase, idx (phase.id)}
										<div class="flex items-center gap-2 py-1">
											{#if phase.status === 'completed'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="14"
													height="14"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="2.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="shrink-0 text-success"
												>
													<path d="M20 6 9 17l-5-5" />
												</svg>
											{:else if phase.status === 'in_progress'}
												<div class="relative h-2.5 w-2.5 shrink-0">
													<span class="absolute inset-0 animate-ping rounded-full bg-accent/30"
													></span>
													<span class="absolute inset-[2px] rounded-full bg-accent"></span>
												</div>
											{:else}
												<div
													class="h-2.5 w-2.5 shrink-0 rounded-full border border-border-strong"
												></div>
											{/if}
											<p
												class="truncate text-[14px] {phase.status === 'pending'
													? 'text-subtle'
													: 'text-foreground'}"
											>
												{getPlanPhaseLabel(phase, idx)}
											</p>
										</div>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				</div>
			</div>
		{:else if newTabPageActive}
			<NewTabPage
				existing={existingTabDefs}
				suggested={suggestedTabDefs}
				onjump={(id) => jumpToPanelTab(id as PanelTab)}
				onadd={(id) => addPanelTab(id as PanelTab)}
			/>
		{:else if activeTab === 'preview'}
			<div class="flex h-full min-h-0 flex-col overflow-hidden">
				<div class="min-h-0 flex-1">
					{#if previewUrl}
						<div class="flex h-full flex-col overflow-hidden">
							<!-- Preview header -->
							<div
								class="flex shrink-0 items-center gap-2 border-b border-border bg-background px-3 py-1.5"
							>
								<div
									class="flex min-w-0 flex-1 items-center gap-1.5 rounded-md bg-surface-2 px-2.5 py-1"
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="11"
										height="11"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										stroke-linecap="round"
										stroke-linejoin="round"
										class="shrink-0 text-muted"
										><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /></svg
									>
									<span class="truncate text-[14px] text-muted">{previewUrl}</span>
								</div>
								{#if previewLabel}
									<span
										class="shrink-0 truncate rounded bg-surface-2 px-1.5 py-0.5 text-[11.5px] text-muted"
										>{previewLabel}</span
									>
								{/if}
								<button
									type="button"
									onclick={() => window.open(previewUrl, '_blank', 'noopener,noreferrer')}
									class="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-muted transition-colors hover:bg-border hover:text-subtle"
									title="Open in new tab"
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="12"
										height="12"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										stroke-linecap="round"
										stroke-linejoin="round"
									>
										<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
										<polyline points="15 3 21 3 21 9" />
										<line x1="10" x2="21" y1="14" y2="3" />
									</svg>
								</button>
							</div>
							<!-- Iframe -->
							<div class="min-h-0 flex-1 overflow-hidden">
								<iframe
									src={previewUrl}
									title={previewLabel || 'Live preview'}
									class="h-full w-full border-0"
									sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
								></iframe>
							</div>
						</div>
					{:else}
						<div class="flex h-full items-center justify-center p-4">
							<div class="text-center">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="36"
									height="36"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									class="mx-auto text-muted"
								>
									<rect width="18" height="18" x="3" y="3" rx="2" />
									<path d="M3 9h18" />
									<path d="M9 21V9" />
								</svg>
								<p class="mt-3 text-sm text-subtle">No preview yet</p>
								<p class="mt-1 text-xs text-muted">
									A live preview will appear when the agent runs a web or mobile tool.
								</p>
							</div>
						</div>
					{/if}
				</div>

				<div class="shrink-0 border-t border-border-subtle p-2" data-testid="preview-plan-overview">
					<div class="overflow-hidden rounded-xl border border-border-subtle bg-surface">
						<button
							type="button"
							onclick={() => {
								if (hasPlan) planExpanded = !planExpanded;
							}}
							class="flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors {hasPlan
								? 'hover:bg-surface-2'
								: ''}"
							aria-expanded={hasPlan ? planExpanded : undefined}
							data-testid="preview-plan-toggle"
						>
							{#if hasPlan && planExpanded}
								<p class="text-[14px] font-medium text-foreground">Task progress</p>
							{:else}
								<div class="flex min-w-0 flex-1 items-center gap-2">
									{#if summaryPlanObjective?.status === 'completed'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="14"
											height="14"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2.5"
											stroke-linecap="round"
											stroke-linejoin="round"
											class="shrink-0 text-success"
										>
											<path d="M20 6 9 17l-5-5" />
										</svg>
									{:else if summaryPlanObjective?.status === 'in_progress'}
										<div class="relative h-2.5 w-2.5 shrink-0">
											<span class="absolute inset-0 animate-ping rounded-full bg-accent/30"></span>
											<span class="absolute inset-[2px] rounded-full bg-accent"></span>
										</div>
									{:else if hasPlan}
										<div
											class="h-2.5 w-2.5 shrink-0 rounded-full border border-border-strong"
										></div>
									{:else}
										<div class="h-2.5 w-2.5 shrink-0 rounded-full bg-border-subtle"></div>
									{/if}
									<p class="truncate text-[14px] font-medium text-foreground">{planHeadline}</p>
								</div>
							{/if}

							<div class="ml-auto flex shrink-0 items-center gap-1.5">
								{#if hasPlan}
									<span class="text-[14px] tabular-nums text-subtle">{planCountLabel}</span>
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
										class="text-subtle transition-transform duration-200"
										class:rotate-180={planExpanded}
									>
										<path d="m6 9 6 6 6-6" />
									</svg>
								{/if}
							</div>
						</button>

						{#if hasPlan && planExpanded}
							<div
								class="border-t border-border-subtle px-3 pb-2 pt-1.5"
								data-testid="preview-plan-details"
							>
								<div class="space-y-1">
									{#each planPhases as phase, idx (phase.id)}
										<div class="flex items-center gap-2 py-1">
											{#if phase.status === 'completed'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="14"
													height="14"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="2.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="shrink-0 text-success"
												>
													<path d="M20 6 9 17l-5-5" />
												</svg>
											{:else if phase.status === 'in_progress'}
												<div class="relative h-2.5 w-2.5 shrink-0">
													<span class="absolute inset-0 animate-ping rounded-full bg-accent/30"
													></span>
													<span class="absolute inset-[2px] rounded-full bg-accent"></span>
												</div>
											{:else}
												<div
													class="h-2.5 w-2.5 shrink-0 rounded-full border border-border-strong"
												></div>
											{/if}
											<p
												class="truncate text-[14px] {phase.status === 'pending'
													? 'text-subtle'
													: 'text-foreground'}"
											>
												{getPlanPhaseLabel(phase, idx)}
											</p>
										</div>
									{/each}
								</div>
							</div>
						{/if}
					</div>
				</div>
			</div>
		{:else if activeTab === 'code'}
			<div class="flex h-full min-h-0 overflow-hidden">
				<!-- File tree sidebar -->
				<div class="h-full w-[200px] shrink-0 overflow-hidden border-r border-border bg-background">
					{#if conversationId}
						<FileExplorer {conversationId} />
					{:else}
						<div class="px-3 py-8 text-center text-xs text-muted">No active conversation</div>
					{/if}
				</div>
				<!-- Editor content -->
				<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
					{#if activeTabData}
						{#if activeTabData.loading}
							<div class="flex flex-1 items-center justify-center">
								<div
									class="h-4 w-4 animate-spin rounded-full border-2 border-foreground/20 border-t-dark/60"
								></div>
							</div>
						{:else if activeTabData.error}
							<div class="flex flex-1 items-center justify-center p-4">
								<div class="text-center">
									<p class="text-xs font-medium text-error/80">Failed to load file</p>
									<p class="mt-1 text-[14px] text-muted">{activeTabData.error}</p>
								</div>
							</div>
						{:else}
							{#if activeTabData.conflict}
								<div
									class="shrink-0 border-b border-warning/30 bg-warning/[0.06] px-3 py-2"
									data-testid="conflict-banner"
								>
									<div class="flex items-center gap-2">
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="14"
											height="14"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											class="shrink-0 text-warning"
										>
											<path
												d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"
											/>
											<path d="M12 9v4" />
											<path d="M12 17h.01" />
										</svg>
										<span class="text-xs text-foreground"
											>File modified externally with unsaved changes.</span
										>
										<div class="ml-auto flex items-center gap-1.5">
											<button
												type="button"
												onclick={() => handleResolveConflict(activeTabData.path, 'mine')}
												class="rounded-md bg-border px-2 py-0.5 text-[14px] font-medium text-foreground transition-colors hover:bg-border-strong"
											>
												Keep mine
											</button>
											<button
												type="button"
												onclick={() => handleResolveConflict(activeTabData.path, 'theirs')}
												class="rounded-md bg-border px-2 py-0.5 text-[14px] font-medium text-foreground transition-colors hover:bg-border-strong"
											>
												Use server version
											</button>
										</div>
									</div>
								</div>
							{/if}
							<div class="min-h-0 flex-1">
								<LazyCodeMirrorEditor
									content={activeTabData.content}
									language={activeTabData.language}
									readonly={isAgentRunning}
									{wordWrap}
									onchange={handleEditorChange}
									onsave={handleEditorSave}
								/>
							</div>
						{/if}
					{:else}
						<div class="flex h-full items-center justify-center">
							<div class="text-center">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="36"
									height="36"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									class="mx-auto text-muted"
								>
									<polyline points="16 18 22 12 16 6" />
									<polyline points="8 6 2 12 8 18" />
								</svg>
								<p class="mt-3 text-xs text-muted">Select a file to open in the canvas</p>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{:else if activeTab === 'database'}
			<div class="h-full overflow-auto">
				{#if databaseColumns.length > 0}
					<table class="min-w-full text-left text-xs">
						<thead class="sticky top-0 border-b border-border bg-surface text-subtle">
							<tr>
								{#each databaseColumns as column (column)}
									<th class="px-2.5 py-2 font-medium">{column}</th>
								{/each}
							</tr>
						</thead>
						<tbody>
							{#each databaseRows as row, index (index)}
								<tr class="border-b border-border-subtle text-subtle">
									{#each databaseColumns as column (column)}
										<td class="max-w-[200px] truncate px-2.5 py-2">{String(row[column] ?? '')}</td>
									{/each}
								</tr>
							{/each}
						</tbody>
					</table>
				{:else}
					<div class="flex h-full items-center justify-center">
						<div class="text-center">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="36"
								height="36"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								class="mx-auto text-muted"
							>
								<ellipse cx="12" cy="5" rx="9" ry="3" />
								<path d="M3 5V19A9 3 0 0 0 21 19V5" />
								<path d="M3 12A9 3 0 0 0 21 12" />
							</svg>
							<p class="mt-3 text-xs text-muted">No database output yet</p>
						</div>
					</div>
				{/if}
			</div>
		{:else if activeTab === 'settings'}
			<div class="h-full overflow-auto p-3">
				<div class="space-y-3">
					<div class="rounded-lg border border-border bg-background p-3">
						<p class="text-xs font-medium text-foreground">Publish & Access</p>
						<p class="mt-1 text-xs text-subtle">
							Domains are available once the project is published.
						</p>
					</div>
					<div class="rounded-lg border border-border bg-background p-3">
						<div class="flex items-center justify-between">
							<p class="text-xs font-medium text-foreground">Hide badge</p>
							<button
								type="button"
								class="h-5 w-9 rounded-full bg-border-strong p-0.5"
								aria-label="Toggle hide badge"
							>
								<span class="block h-4 w-4 rounded-full bg-background"></span>
							</button>
						</div>
						<p class="mt-1 text-xs text-subtle">Remove branding from preview surfaces.</p>
					</div>
				</div>
			</div>
		{:else if activeTab === 'files'}
			<div class="h-full overflow-hidden">
				{#if conversationId}
					<FileExplorer {conversationId} />
				{:else}
					<div class="flex h-full items-center justify-center">
						<p class="text-xs text-muted">No active conversation</p>
					</div>
				{/if}
			</div>
		{:else if activeTab === 'vnc'}
			<div class="flex h-full items-center justify-center">
				<div class="text-center">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="36"
						height="36"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						class="mx-auto text-muted"
					>
						<rect width="20" height="14" x="2" y="3" rx="2" />
						<path d="M12 17v4" />
						<path d="M8 21h8" />
						<circle cx="12" cy="10" r="2" />
					</svg>
					<p class="mt-3 text-xs text-muted">VNC connection will appear here</p>
				</div>
			</div>
		{:else if activeTab === 'artifact'}
			<div class="h-full overflow-hidden">
				{#if latestArtifactTool}
					<ArtifactCanvas toolCall={latestArtifactTool} />
				{:else}
					<div class="flex h-full items-center justify-center">
						<div class="text-center">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="36"
								height="36"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								class="mx-auto text-muted"
							>
								<path
									d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"
								/>
								<path d="M5 3v4" />
								<path d="M19 17v4" />
								<path d="M3 5h4" />
								<path d="M17 19h4" />
							</svg>
							<p class="mt-3 text-xs text-muted">No artifacts yet</p>
							<p class="mt-1 text-[10.5px] text-muted">
								Artifacts will appear here when the agent creates rich content
							</p>
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	.canvas-tab {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.375rem 0.75rem;
		font-size: 0.875rem;
		line-height: 1;
		white-space: nowrap;
		border-radius: 0.5rem;
		cursor: pointer;
		transition:
			background-color 150ms,
			color 150ms,
			opacity 150ms;
		min-width: 0;
		max-width: 14rem;
		height: 2.25rem;
		flex-shrink: 0;
	}
	.canvas-tab-active {
		background: color-mix(in srgb, var(--color-dark, #000) 8%, transparent);
		color: var(--color-dark);
	}
	.canvas-tab-inactive {
		background: transparent;
		color: var(--color-dark, #000);
		opacity: 0.45;
	}
	.canvas-tab-inactive:hover {
		background: color-mix(in srgb, var(--color-dark, #000) 5%, transparent);
		opacity: 0.75;
	}
</style>
