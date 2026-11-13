<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { get } from 'svelte/store';
	import {
		toolCalls as toolCallsStore,
		messages as messagesStore,
		runStatus as runStatusStore,
		isThinking as isThinkingStore,
		planState as planStateStore,
		type Message
	} from '$services/sse';
	import { conversations as conversationsStore } from '$stores/conversations';
	import type { Conversation } from '$api/types';
	import {
		openPanelTabs as openPanelTabsStore,
		activePanelTab as activePanelTabStore,
		newTabPageActive as newTabPageActiveStore,
		type PanelTab
	} from '$stores/panelTabs';
	import { computerPanelPinned, computerPanelToolIndex } from '$stores/computerPanel';

	import UserMessage from '$components/chat/UserMessage.svelte';
	import AgentMessage from '$components/chat/AgentMessage.svelte';
	import ToolCallMessage from '$components/chat/ToolCallMessage.svelte';
	import ErrorMessage from '$components/chat/ErrorMessage.svelte';
	import HitlMessage from '$components/chat/HitlMessage.svelte';
	import HitlInputBar from '$components/chat/HitlInputBar.svelte';
	import ChatMessageList from '$components/chat/ChatMessageList.svelte';
	import ChatHeader from '$components/chat/ChatHeader.svelte';
	import ActiveChatInput from '$components/chat/ActiveChatInput.svelte';
	import WorkspaceLayout from '$components/chat/WorkspaceLayout.svelte';
	import CodeEditorPanel from '$components/chat/CodeEditorPanel.svelte';
	import MessageActionBar from '$components/chat/MessageActionBar.svelte';
	import BranchPointIndicator from '$components/chat/BranchPointIndicator.svelte';
	import AgentActivityIndicator from '$components/chat/AgentActivityIndicator.svelte';
	import InjectionQueueBanner from '$components/chat/InjectionQueueBanner.svelte';
	import ToolCanvas from '$components/toolRenderers/ToolCanvas.svelte';

	import { ENTRIES, CATEGORY_LABELS, CATEGORY_ORDER, DEFAULT_ENTRY_ID } from './registry';
	import * as m from './mocks';

	let selectedId = $state(DEFAULT_ENTRY_ID);

	const MOCK_CONVERSATION_ID = 'pg-simulated-chat';

	// Tool calls for the SSE store + CodeEditorPanel. Pulled directly from
	// the simulated thread so clicking any tool call row in the chat pins
	// its canvas in the computer panel on the right — which is how the real
	// app works.
	const mockToolCallsArray = m.threadToolCalls;

	const mockConversation: Conversation = {
		id: MOCK_CONVERSATION_ID,
		title: 'Audit tool → canvas routing',
		summary: 'Playground simulated conversation',
		error: null,
		date_created: '2026-04-15T09:00:00Z',
		date_updated: '2026-04-15T09:42:00Z',
		metadata: {},
		status: 'running'
	};

	// ─── Store snapshot/restore ─────────────────────────────────────────────
	//
	// The simulated chat seeds real SSE + workspace stores so every component
	// (ChatHeader, CodeEditorPanel, AgentActivityIndicator, etc.) sees the
	// same data it would during a live run. Snapshots are captured on mount
	// and restored on destroy so leaving the playground doesn't leak state
	// into other pages.

	type Snapshot = {
		toolCalls: Map<string, import('$services/sse').ToolCallMessage>;
		messages: Message[];
		runStatus: import('$services/sse').RunStatus;
		isThinking: boolean;
		planState: import('$services/sse').PlanState | null;
		conversations: Conversation[];
		openPanelTabs: PanelTab[];
		activePanelTab: PanelTab;
		newTabPageActive: boolean;
		computerPanelPinned: boolean;
		computerPanelToolIndex: number;
	};

	let snapshot: Snapshot | null = null;

	onMount(() => {
		snapshot = {
			toolCalls: new Map(get(toolCallsStore)),
			messages: [...get(messagesStore)],
			runStatus: get(runStatusStore),
			isThinking: get(isThinkingStore),
			planState: get(planStateStore),
			conversations: [...get(conversationsStore)],
			openPanelTabs: [...get(openPanelTabsStore)],
			activePanelTab: get(activePanelTabStore),
			newTabPageActive: get(newTabPageActiveStore),
			computerPanelPinned: get(computerPanelPinned),
			computerPanelToolIndex: get(computerPanelToolIndex)
		};

		// Seed SSE stores
		const seededMap = new Map(snapshot.toolCalls);
		for (const tc of mockToolCallsArray) seededMap.set(tc.callId, tc);
		toolCallsStore.set(seededMap);

		messagesStore.set(m.conversationThread);
		runStatusStore.set('running');
		isThinkingStore.set(false);
		planStateStore.set(m.planStateExample);

		// Seed the conversations list so ChatHeader can find it
		conversationsStore.update((existing) => {
			if (existing.some((c) => c.id === MOCK_CONVERSATION_ID)) return existing;
			return [mockConversation, ...existing];
		});

		// Seed the panel tabs the sandbox agent can actually populate.
		// 'artifact' is dropped — no sandbox tool emits an artifact result,
		// so the tab would render permanently empty.
		openPanelTabsStore.set(['preview', 'code', 'database', 'files']);
		activePanelTabStore.set('preview');
		newTabPageActiveStore.set(false);

		// Pin the computer panel to the database query so the preview tab
		// shows a meaningful canvas on first load instead of an empty state.
		const pinIdx = mockToolCallsArray.findIndex((tc) => tc.toolName === 'mcp_execute_sql_query');
		computerPanelToolIndex.set(pinIdx >= 0 ? pinIdx : 0);
		computerPanelPinned.set(true);
	});

	onDestroy(() => {
		if (!snapshot) return;
		toolCallsStore.set(snapshot.toolCalls);
		messagesStore.set(snapshot.messages);
		runStatusStore.set(snapshot.runStatus);
		isThinkingStore.set(snapshot.isThinking);
		planStateStore.set(snapshot.planState);
		conversationsStore.set(snapshot.conversations);
		openPanelTabsStore.set(snapshot.openPanelTabs);
		activePanelTabStore.set(snapshot.activePanelTab);
		newTabPageActiveStore.set(snapshot.newTabPageActive);
		computerPanelPinned.set(snapshot.computerPanelPinned);
		computerPanelToolIndex.set(snapshot.computerPanelToolIndex);
	});

	const groupedEntries = CATEGORY_ORDER.map((cat) => ({
		cat,
		label: CATEGORY_LABELS[cat],
		items: ENTRIES.filter((e) => e.category === cat)
	}));

	let selectedEntry = $derived(ENTRIES.find((e) => e.id === selectedId) ?? ENTRIES[0]);
	let isSimulatedChat = $derived(selectedId === 'chat-message-list');

	function noop(): void {}
	function noopHitl(_id: string, _r: string): void {}

	const dummyActions = [
		{ id: 'copy', label: 'Copy', icon: 'copy' as const, action: noop },
		{ id: 'edit', label: 'Edit', icon: 'edit' as const, action: noop },
		{ id: 'branch', label: 'Branch', icon: 'branch' as const, action: noop }
	];
</script>

<svelte:head>
	<title>Chat UI Playground</title>
</svelte:head>

<div class="flex h-full w-full flex-col overflow-hidden">
	<!-- ────────────── View picker (always visible) ────────────── -->
	<div
		class="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface px-4 py-2 sm:px-5 md:px-6"
	>
		<span
			class="rounded-full border border-border-subtle bg-background px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-wider text-muted"
		>
			Playground
		</span>
		<span class="text-[12.5px] text-subtle">{selectedEntry.label}</span>
		<div class="ml-auto flex items-center gap-2">
			<label class="text-[12px] text-muted" for="pg-view">View</label>
			<select
				id="pg-view"
				bind:value={selectedId}
				class="rounded-md border border-border bg-background px-2.5 py-1 text-[13px] text-foreground focus:border-border-strong focus:outline-none"
			>
				{#each groupedEntries as group (group.cat)}
					<optgroup label={group.label}>
						{#each group.items as entry (entry.id)}
							<option value={entry.id}>{entry.label}</option>
						{/each}
					</optgroup>
				{/each}
			</select>
		</div>
	</div>

	<!-- ────────────── Content ────────────── -->
	{#if isSimulatedChat}
		<!-- Real chat layout: WorkspaceLayout (split) + ChatHeader + messages + input -->
		<div class="min-h-0 flex-1 overflow-hidden">
			<WorkspaceLayout>
				{#snippet editor()}
					<CodeEditorPanel toolCalls={mockToolCallsArray} conversationId={MOCK_CONVERSATION_ID} />
				{/snippet}
				{#snippet chat()}
					<ChatHeader conversationId={MOCK_CONVERSATION_ID} messages={m.conversationThread} />
					<div class="chat-main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
						<ChatMessageList
							messages={m.conversationThread}
							runStatus="running"
							isThinking={false}
							conversationId={MOCK_CONVERSATION_ID}
						/>
						<InjectionQueueBanner position={null} />
						<ActiveChatInput conversationId={MOCK_CONVERSATION_ID} runStatus="running" />
					</div>
				{/snippet}
			</WorkspaceLayout>
		</div>
	{:else}
		<!-- Individual component preview, rendered inside a chat-style column -->
		<div class="flex-1 overflow-y-auto">
			<div class="flex flex-col gap-2 px-4 py-6 sm:px-5 md:px-6 lg:px-8">
				{#snippet divider(label: string, note: string | null = null)}
					<div class="my-3 flex items-center gap-2 first:mt-1">
						<div class="h-px flex-1 bg-border-subtle"></div>
						<span
							class="rounded-full border border-border-subtle bg-surface px-2.5 py-0.5 text-[10.5px] font-medium uppercase tracking-wider text-muted"
						>
							{label}
						</span>
						{#if note}
							<span class="text-[11.5px] text-muted">— {note}</span>
						{/if}
						<div class="h-px flex-1 bg-border-subtle"></div>
					</div>
				{/snippet}

				<!-- ══════════ Messages ══════════ -->
				{#if selectedId === 'user-message'}
					{@render divider('Short text')}
					<UserMessage message={m.userMessageShort} />
					{@render divider('With file attachments')}
					<UserMessage message={m.userMessageWithFiles} />
					{@render divider('Long markdown')}
					<UserMessage message={m.userMessageLongMarkdown} />
				{:else if selectedId === 'agent-message'}
					{@render divider('Short plain text')}
					<AgentMessage message={m.agentMessageShort} />
					{@render divider('Rich markdown', 'headings, lists, code, tables, quotes')}
					<AgentMessage message={m.agentMessageMarkdown} />
					{@render divider('Streaming', 'isStreaming: true')}
					<AgentMessage message={m.agentMessageStreaming} />
					{@render divider('Muted', 'used inside delegate sub-agent groups')}
					<AgentMessage message={m.agentMessageMuted} muted />
					{@render divider('Started-by header')}
					<AgentMessage
						message={m.agentMessageStartedBy}
						startedByName={m.agentMessageStartedBy.started_by_name}
					/>
				{:else if selectedId === 'tool-call-message'}
					{@render divider('Running')}
					<ToolCallMessage message={m.toolCallRunning} />
					{@render divider('Success')}
					<ToolCallMessage message={m.toolCallSuccess} />
					{@render divider('Error')}
					<ToolCallMessage message={m.toolCallError} />
					{@render divider('Muted', 'used inside delegate groups')}
					<ToolCallMessage message={m.toolCallSuccess} muted />
				{:else if selectedId === 'error-message'}
					{@render divider('Plain')}
					<ErrorMessage message={m.errorMessageNetwork} />
					{@render divider('With retry')}
					<ErrorMessage message={m.errorMessageAuth} onRetry={noop} />
				{:else if selectedId === 'hitl-message'}
					{@render divider('Multiple choice (inline)')}
					<HitlMessage message={m.hitlPending} />
					{@render divider('Free text (inline)')}
					<HitlMessage message={m.hitlFreeText} />
					{@render divider('Answered', 'response: "Deploy"')}
					<HitlMessage message={m.hitlAnswered} />
					{@render divider('Input bar — choices', 'bottom-anchored')}
					<HitlInputBar
						hitlRequest={{
							requestId: 'demo-1',
							prompt: m.hitlPending.prompt,
							choices: m.hitlPending.choices
						}}
						onSubmit={noopHitl}
					/>
					{@render divider('Input bar — free text', 'bottom-anchored')}
					<HitlInputBar
						hitlRequest={{ requestId: 'demo-2', prompt: m.hitlFreeText.prompt }}
						onSubmit={noopHitl}
					/>
				{:else if selectedId === 'message-action-bar'}
					{@render divider('Always visible')}
					<div class="group/msg">
						<AgentMessage message={m.agentMessageShort} />
						<MessageActionBar items={dummyActions} alwaysVisible />
					</div>
					{@render divider('Hover-only', 'hover the message to reveal')}
					<div class="group/msg">
						<AgentMessage message={m.agentMessageStartedBy} />
						<MessageActionBar items={dummyActions} />
					</div>
				{:else if selectedId === 'branch-point-indicator'}
					<UserMessage message={m.userMessageShort} />
					{@render divider('Branch point')}
					<BranchPointIndicator />
					<AgentMessage message={m.agentMessageShort} />
					<!-- ══════════ Tool renderers ══════════ -->
				{:else if selectedId === 'canvas-terminal'}
					{@render divider('Shell success (with ANSI colors)')}
					<div class="h-96 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcTerminalShell} />
					</div>
					{@render divider('Error (exit_code 1)')}
					<div class="h-64 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.toolCallError} />
					</div>
				{:else if selectedId === 'canvas-diff'}
					{@render divider('Unified diff')}
					<div class="h-96 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcDiff} />
					</div>
				{:else if selectedId === 'canvas-code-viewer'}
					{@render divider('TypeScript file')}
					<div class="h-96 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcCodeViewer} />
					</div>
				{:else if selectedId === 'canvas-file-tree'}
					{@render divider('Directory listing')}
					<div class="h-96 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcFileTree} />
					</div>
				{:else if selectedId === 'canvas-file-status'}
					{@render divider('Save success')}
					<div class="h-40 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcFileStatusSave} />
					</div>
				{:else if selectedId === 'canvas-search'}
					{@render divider('Web search results')}
					<div class="h-[520px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcSearchWeb} />
					</div>
				{:else if selectedId === 'canvas-search-images'}
					{@render divider('Image search (masonry)')}
					<div class="h-[640px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcSearchImages} />
					</div>
				{:else if selectedId === 'canvas-browser'}
					{@render divider('Browser task', 'screenshots come from MCP progress events')}
					<div class="h-96 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcBrowser} />
					</div>
				{:else if selectedId === 'canvas-database'}
					{@render divider('SELECT results')}
					<div class="h-96 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcDatabase} />
					</div>
				{:else if selectedId === 'canvas-media'}
					{@render divider('Generated image')}
					<div class="h-[480px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcMedia} />
					</div>
				{:else if selectedId === 'canvas-audio'}
					{@render divider('Transcription')}
					<div class="h-64 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcAudio} />
					</div>
				{:else if selectedId === 'canvas-vision'}
					{@render divider('Visual Q&A')}
					<div class="h-[480px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcVision} />
					</div>
				{:else if selectedId === 'canvas-dev-server'}
					{@render divider('Started')}
					<div class="h-64 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcDevServer} />
					</div>
				{:else if selectedId === 'canvas-download'}
					{@render divider('Success')}
					<div class="h-64 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcDownload} />
					</div>
				{:else if selectedId === 'canvas-reasoning'}
					{@render divider('Analysis')}
					<div class="h-72 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcReasoning} />
					</div>
				{:else if selectedId === 'canvas-settings'}
					{@render divider('Env variable set')}
					<div class="h-32 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcSettings} />
					</div>
				{:else if selectedId === 'canvas-checkpoint'}
					{@render divider('Git checkpoint saved')}
					<div class="h-40 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcCheckpoint} />
					</div>
				{:else if selectedId === 'canvas-artifact'}
					{@render divider('Markdown artifact')}
					<div class="h-[520px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcArtifact} />
					</div>
				{:else if selectedId === 'canvas-preview'}
					{@render divider('Exposed port preview')}
					<div class="h-[520px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcPreview} />
					</div>
				{:else if selectedId === 'canvas-project'}
					{@render divider('Project setup')}
					<div class="h-72 overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcProject} />
					</div>
				{:else if selectedId === 'canvas-km'}
					{@render divider('Knowledge Manager read')}
					<div class="h-[520px] overflow-hidden rounded-lg border border-border-subtle bg-surface">
						<ToolCanvas toolCall={m.tcKm} />
					</div>

					<!-- ══════════ Input & header ══════════ -->
				{:else if selectedId === 'agent-activity-indicator'}
					{@render divider('Thinking')}
					<AgentActivityIndicator runStatus="running" isThinking={true} />
					{@render divider(
						'Executing tool',
						'picks latest running tool from the seeded toolCalls store'
					)}
					<AgentActivityIndicator runStatus="running" isThinking={false} />
					{@render divider('Connecting')}
					<AgentActivityIndicator runStatus="connecting" isThinking={false} />
					{@render divider('Reconnecting')}
					<AgentActivityIndicator runStatus="running" isThinking={false} isReconnecting />
				{:else if selectedId === 'injection-queue-banner'}
					{@render divider('Position 2')}
					<InjectionQueueBanner position={2} />
					{@render divider('Position 1')}
					<InjectionQueueBanner position={1} />
					{@render divider('Null (hidden)')}
					<p class="text-[13px] text-muted">
						The banner renders nothing when <code>position</code> is null or 0.
					</p>
					<InjectionQueueBanner position={null} />
				{/if}
			</div>
		</div>
	{/if}
</div>
