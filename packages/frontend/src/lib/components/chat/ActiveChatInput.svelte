<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import { chatInputPrefill, chatInputAutoSubmit } from '$stores/chatInput';
	import { activeSelectorSelection, clearSelectorSelection } from '$stores/selectorSelection';
	import type { Selection as SelectorSelection } from '$lib/components/toolRenderers/selector/types';
	import { getFriendlyElementLabel } from '$lib/components/toolRenderers/selector/labels';
	import MousePointer from '@lucide/svelte/icons/mouse-pointer';
	import { get } from 'svelte/store';
	import { startRun, cancelRun as cancelRunSandbox } from '$api/run';
	import { uploadFile } from '$api/files';
	import { getUserAddons } from '$api/addons';
	import { getMCPConfigs } from '$api/mcp';
	import { getInstalledSkills, type SkillCatalog } from '$api/skills';
	import { acquireSession } from '$stores/sandboxSession';
	import MentionAutocomplete from '$components/chat/MentionAutocomplete.svelte';
	import {
		addUserMessage,
		confirmUserMessage,
		addErrorMessage,
		messages as messagesStore,
		getCurrentConversationId,
		getCurrentRunId,
		connectToRun,
		noteSubmissionStart
	} from '$services/sse';
	import { ApiClientError } from '$api/client';
	import { detectLimitError, usageLimitModal } from '$stores/usageLimit';
	import type { UserAddon, UserMCPConfig } from '$api/types';
	import type { RunStatus } from '$services/sse';
	import { tooltip } from '$lib/actions/tooltip';
	import { flagEnabled } from '$stores/featureFlags';

	const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
	const PASTE_TEXT_THRESHOLD = 5000;

	interface AttachedFile {
		id: string;
		file: File;
		previewUrl: string | null;
		uploading: boolean;
		uploadedId: string | null;
	}

	interface SandboxBusyInfo {
		conversationId: string | null;
		conversationTitle: string | null;
	}

	interface Props {
		conversationId: string;
		runStatus: RunStatus;
		readOnly?: boolean;
		sandboxBusyConversation?: SandboxBusyInfo | null;
		viewOnlyMessage?: string;
	}

	let {
		conversationId,
		runStatus,
		readOnly = false,
		sandboxBusyConversation = null,
		viewOnlyMessage
	}: Props = $props();

	let isSandboxBusy = $derived(sandboxBusyConversation !== null);

	let prompt = $state('');
	let submitting = $state(false);
	let cancelling = $state(false);
	let hasMessages = $state(false);
	let textareaEl: HTMLTextAreaElement | undefined = $state(undefined);
	let fileInputEl: HTMLInputElement | undefined = $state(undefined);
	let attachedFiles: AttachedFile[] = $state([]);
	let dragOver = $state(false);
	let dragCounter = $state(0);

	// Active element selection from the in-preview component selector.
	// When present, a chip renders above the textarea and the selection
	// metadata is prepended to the next outgoing message.
	let activeSelection: SelectorSelection | null = $state(null);
	const unsubSelectorSelection = activeSelectorSelection.subscribe((v) => {
		activeSelection = v;
	});

	function selectionChipLabel(sel: SelectorSelection): string {
		return `Selected: ${getFriendlyElementLabel(sel)}`;
	}

	function buildSelectionContextLine(sel: SelectorSelection): string {
		if (sel.sourceLoc) {
			const { fileName, lineNumber, columnNumber } = sel.sourceLoc;
			return `[Selected: <${sel.tagName.toLowerCase()}> in ${fileName}:${lineNumber}:${columnNumber}] `;
		}
		return `[Selected: <${sel.tagName.toLowerCase()}>] `;
	}

	// Vim mode (feature flag: keyboard-vim-mode)
	const vimFlag = flagEnabled('keyboard-vim-mode');
	let vimEnabled = $state(false);
	let vimMode: 'normal' | 'insert' = $state('insert');
	const unsubVim = vimFlag.subscribe((v) => {
		vimEnabled = v;
		if (!v) vimMode = 'insert';
	});

	// Addon selector state
	let availableAddons: UserAddon[] = $state([]);
	let selectedAddonIds = new SvelteSet<string>();
	let addonPopoverOpen = $state(false);
	let addonLoading = $state(false);

	// MCP selector state
	let availableMCPs: UserMCPConfig[] = $state([]);
	let selectedMCPIds = new SvelteSet<string>();
	let mcpPopoverOpen = $state(false);
	let mcpLoading = $state(false);

	// Skills selector state
	let availableSkills: SkillCatalog[] = $state([]);
	let selectedSkillIds = new SvelteSet<string>();
	let skillLoading = $state(false);

	// Voice input state
	let isRecording = $state(false);
	let recognition: SpeechRecognition | null = $state(null);
	let voiceSupported = $state(false);

	// Tools popover (combines addons + MCPs)
	let toolsPopoverOpen = $state(false);

	let isRunActive = $derived(
		runStatus === 'running' ||
			runStatus === 'connecting' ||
			runStatus === 'queued' ||
			runStatus === 'provisioning' ||
			runStatus === 'waiting_for_input'
	);
	let isSubmitBlocked = $derived(
		runStatus === 'connecting' ||
			runStatus === 'queued' ||
			runStatus === 'provisioning' ||
			runStatus === 'waiting_for_input'
	);
	let canSubmit = $derived(
		(prompt.trim().length > 0 || attachedFiles.length > 0) && !submitting && !isSubmitBlocked
	);

	let selectedAddonCount = $derived(selectedAddonIds.size);
	let selectedMCPCount = $derived(selectedMCPIds.size);
	let selectedSkillCount = $derived(selectedSkillIds.size);
	let totalToolCount = $derived(selectedAddonCount + selectedMCPCount + selectedSkillCount);

	// Subscribe to chatInputPrefill
	const unsubPrefill = chatInputPrefill.subscribe((prefill) => {
		if (prefill) {
			prompt = prefill;
			chatInputPrefill.set('');
			requestAnimationFrame(() => {
				if (textareaEl) {
					textareaEl.focus();
					autoResize(textareaEl);
				}
				if (get(chatInputAutoSubmit)) {
					chatInputAutoSubmit.set(false);
					requestAnimationFrame(() => submitMessage());
				}
			});
		}
	});

	const unsubMessages = messagesStore.subscribe((items) => {
		hasMessages = items.length > 0;
	});

	onMount(() => {
		loadAddons();
		loadMCPs();
		loadSkills();
		initVoice();
	});

	onDestroy(() => {
		unsubPrefill();
		unsubMessages();
		unsubVim();
		unsubSelectorSelection();
		if (recognition) {
			recognition.abort();
			recognition = null;
		}
		for (const file of attachedFiles) {
			if (file.previewUrl) {
				URL.revokeObjectURL(file.previewUrl);
			}
		}
	});

	// --- Addon/MCP loading ---

	async function loadAddons(): Promise<void> {
		addonLoading = true;
		try {
			const response = await getUserAddons();
			availableAddons = response.items.filter((a) => a.auth_complete);
		} catch {
			// Silently fail
		} finally {
			addonLoading = false;
		}
	}

	async function loadMCPs(): Promise<void> {
		mcpLoading = true;
		try {
			const response = await getMCPConfigs();
			availableMCPs = response.items;
		} catch {
			// Silently fail
		} finally {
			mcpLoading = false;
		}
	}

	async function loadSkills(): Promise<void> {
		skillLoading = true;
		try {
			const response = await getInstalledSkills();
			availableSkills = response.items;
		} catch {
			// Silently fail
		} finally {
			skillLoading = false;
		}
	}

	function toggleSkill(slug: string): void {
		if (selectedSkillIds.has(slug)) {
			selectedSkillIds.delete(slug);
		} else {
			selectedSkillIds.add(slug);
		}
	}

	function toggleAddon(addonId: string): void {
		if (selectedAddonIds.has(addonId)) {
			selectedAddonIds.delete(addonId);
		} else {
			selectedAddonIds.add(addonId);
		}
	}

	function toggleMCP(mcpId: string): void {
		if (selectedMCPIds.has(mcpId)) {
			selectedMCPIds.delete(mcpId);
		} else {
			selectedMCPIds.add(mcpId);
		}
	}

	// --- Voice input ---

	function initVoice(): void {
		const SpeechRecognition =
			typeof window !== 'undefined'
				? window.SpeechRecognition || window.webkitSpeechRecognition
				: null;
		if (SpeechRecognition) {
			voiceSupported = true;
		}
	}

	function toggleVoice(): void {
		if (isRecording) {
			stopRecording();
		} else {
			startRecording();
		}
	}

	function startRecording(): void {
		const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!SpeechRecognition) return;

		recognition = new SpeechRecognition();
		recognition.continuous = true;
		recognition.interimResults = true;
		recognition.lang = 'en-US';

		recognition.onresult = (event: SpeechRecognitionEvent) => {
			let transcript = '';
			for (let i = 0; i < event.results.length; i++) {
				transcript += event.results[i][0].transcript;
			}
			prompt = transcript;
			if (textareaEl) {
				autoResize(textareaEl);
			}
		};

		recognition.onerror = () => {
			isRecording = false;
			recognition = null;
			toasts.error('Voice input failed. Please try again.');
		};

		recognition.onend = () => {
			isRecording = false;
		};

		recognition.start();
		isRecording = true;
	}

	function stopRecording(): void {
		if (recognition) {
			recognition.stop();
		}
		isRecording = false;
	}

	// --- Close popovers on outside click ---

	function handleWindowClick(e: MouseEvent): void {
		const target = e.target as HTMLElement;
		if (addonPopoverOpen && !target.closest('[data-addon-popover]')) {
			addonPopoverOpen = false;
		}
		if (mcpPopoverOpen && !target.closest('[data-mcp-popover]')) {
			mcpPopoverOpen = false;
		}
		if (toolsPopoverOpen && !target.closest('[data-tools-popover]')) {
			toolsPopoverOpen = false;
		}
	}

	// --- File handling ---

	function autoResize(el: HTMLTextAreaElement): void {
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 200) + 'px';
	}

	function handleInput(e: Event): void {
		const target = e.target as HTMLTextAreaElement;
		autoResize(target);
	}

	function handleVimKeydown(e: KeyboardEvent): boolean {
		if (e.key === 'Escape') {
			vimMode = 'normal';
			e.preventDefault();
			return true;
		}
		if (vimMode === 'insert') return false;

		e.preventDefault();
		const ta = textareaEl;
		if (!ta) return true;
		const pos = ta.selectionStart;
		const val = ta.value;

		switch (e.key) {
			case 'i':
				vimMode = 'insert';
				break;
			case 'a':
				vimMode = 'insert';
				ta.selectionStart = ta.selectionEnd = Math.min(pos + 1, val.length);
				break;
			case 'A':
				vimMode = 'insert';
				{
					const nl = val.indexOf('\n', pos);
					ta.selectionStart = ta.selectionEnd = nl === -1 ? val.length : nl;
				}
				break;
			case 'I':
				vimMode = 'insert';
				ta.selectionStart = ta.selectionEnd = val.lastIndexOf('\n', pos - 1) + 1;
				break;
			case 'o':
				vimMode = 'insert';
				{
					const nl = val.indexOf('\n', pos);
					const insertAt = nl === -1 ? val.length : nl;
					prompt = val.slice(0, insertAt) + '\n' + val.slice(insertAt);
					ta.selectionStart = ta.selectionEnd = insertAt + 1;
				}
				break;
			case 'h':
				ta.selectionStart = ta.selectionEnd = Math.max(0, pos - 1);
				break;
			case 'l':
				ta.selectionStart = ta.selectionEnd = Math.min(val.length, pos + 1);
				break;
			case 'w': {
				const m = val.slice(pos).match(/\S+\s*/);
				ta.selectionStart = ta.selectionEnd = pos + (m ? m[0].length : 0);
				break;
			}
			case 'b': {
				const before = val.slice(0, pos);
				const m = before.match(/\S+\s*$/);
				ta.selectionStart = ta.selectionEnd = pos - (m ? m[0].length : 0);
				break;
			}
			case 'e': {
				const m = val.slice(pos + 1).match(/\S+/);
				ta.selectionStart = ta.selectionEnd = m ? pos + 1 + m.index! + m[0].length - 1 : val.length;
				break;
			}
			case '0':
				ta.selectionStart = ta.selectionEnd = val.lastIndexOf('\n', pos - 1) + 1;
				break;
			case '$': {
				const nl = val.indexOf('\n', pos);
				ta.selectionStart = ta.selectionEnd = nl === -1 ? val.length : nl;
				break;
			}
			case 'g':
				if (e.shiftKey) {
					ta.selectionStart = ta.selectionEnd = val.length;
				} else {
					ta.selectionStart = ta.selectionEnd = 0;
				}
				break;
			case 'x':
				if (pos < val.length) {
					prompt = val.slice(0, pos) + val.slice(pos + 1);
					ta.selectionStart = ta.selectionEnd = pos;
				}
				break;
			default:
				break;
		}
		return true;
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (vimEnabled) {
			const handled = handleVimKeydown(e);
			if (handled) return;
		}
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submitMessage();
		}
	}

	function handlePaste(e: ClipboardEvent): void {
		const clipboardData = e.clipboardData;
		if (!clipboardData) return;

		if (clipboardData.files.length > 0) {
			e.preventDefault();
			addFiles(Array.from(clipboardData.files));
			return;
		}

		const pastedText = clipboardData.getData('text/plain');
		if (pastedText && pastedText.length > PASTE_TEXT_THRESHOLD) {
			e.preventDefault();
			const blob = new Blob([pastedText], { type: 'text/plain' });
			const file = new File([blob], 'pasted-text.txt', { type: 'text/plain' });
			addFiles([file]);
			toasts.info('Long text converted to a .txt file attachment.');
		}
	}

	function validateFile(file: File): boolean {
		if (file.size > MAX_FILE_SIZE) {
			toasts.error(`File "${file.name}" exceeds the 50MB limit.`);
			return false;
		}
		return true;
	}

	function generateFileId(): string {
		return `file-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
	}

	function getFilePreviewUrl(file: File): string | null {
		if (file.type.startsWith('image/')) {
			return URL.createObjectURL(file);
		}
		return null;
	}

	function getFileIcon(file: File): string {
		const type = file.type;
		if (type.startsWith('image/')) return '🖼️';
		if (type.startsWith('video/')) return '🎬';
		if (type.startsWith('audio/')) return '🎵';
		if (type === 'application/pdf') return '📄';
		if (type.includes('spreadsheet') || type.includes('excel')) return '📊';
		if (type.includes('presentation') || type.includes('powerpoint')) return '📊';
		if (type.includes('document') || type.includes('word')) return '📝';
		if (type.startsWith('text/') || type.includes('json') || type.includes('javascript'))
			return '📋';
		return '📎';
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function addFiles(files: File[]): void {
		for (const file of files) {
			if (!validateFile(file)) continue;

			const attached: AttachedFile = {
				id: generateFileId(),
				file,
				previewUrl: getFilePreviewUrl(file),
				uploading: false,
				uploadedId: null
			};

			attachedFiles = [...attachedFiles, attached];
			uploadAttachedFile(attached.id);
		}
	}

	async function uploadAttachedFile(fileId: string): Promise<void> {
		const idx = attachedFiles.findIndex((f) => f.id === fileId);
		if (idx === -1) return;

		attachedFiles = attachedFiles.map((f) => (f.id === fileId ? { ...f, uploading: true } : f));

		try {
			const response = await uploadFile(attachedFiles[idx].file);
			attachedFiles = attachedFiles.map((f) =>
				f.id === fileId ? { ...f, uploading: false, uploadedId: response.file_id } : f
			);
		} catch {
			toasts.error(`Failed to upload "${attachedFiles[idx].file.name}".`);
			attachedFiles = attachedFiles.filter((f) => f.id !== fileId);
		}
	}

	function removeFile(fileId: string): void {
		const file = attachedFiles.find((f) => f.id === fileId);
		if (file?.previewUrl) {
			URL.revokeObjectURL(file.previewUrl);
		}
		attachedFiles = attachedFiles.filter((f) => f.id !== fileId);
	}

	function handleFileInputChange(e: Event): void {
		const input = e.target as HTMLInputElement;
		if (input.files) {
			addFiles(Array.from(input.files));
		}
		input.value = '';
	}

	function handleDragEnter(e: DragEvent): void {
		e.preventDefault();
		dragCounter++;
		if (e.dataTransfer?.types.includes('Files')) {
			dragOver = true;
		}
	}

	function handleDragLeave(e: DragEvent): void {
		e.preventDefault();
		dragCounter--;
		if (dragCounter <= 0) {
			dragOver = false;
			dragCounter = 0;
		}
	}

	function handleDragOver(e: DragEvent): void {
		e.preventDefault();
		if (e.dataTransfer) {
			e.dataTransfer.dropEffect = 'copy';
		}
	}

	function handleDrop(e: DragEvent): void {
		e.preventDefault();
		dragOver = false;
		dragCounter = 0;
		if (e.dataTransfer?.files.length) {
			addFiles(Array.from(e.dataTransfer.files));
		}
	}

	// --- Submit & Cancel ---

	async function submitMessage(): Promise<void> {
		let text = prompt.trim();
		// Auto-inject selector context (idempotently — if the user already
		// has a `[Selected:` marker in their message, don't add another).
		if (activeSelection && !text.includes('[Selected:')) {
			const ctx = buildSelectionContextLine(activeSelection);
			text = text.length > 0 ? `${ctx}${text}` : ctx.trim();
		}
		if ((!text && attachedFiles.length === 0) || submitting || isSubmitBlocked) return;

		const stillUploading = attachedFiles.some((f) => f.uploading);
		if (stillUploading) {
			toasts.warning('Please wait for files to finish uploading.');
			return;
		}

		submitting = true;
		let optimisticMessageId: string | null = null;
		try {
			const fileIds = attachedFiles
				.map((f) => f.uploadedId)
				.filter((id): id is string => id !== null);

			const addonIds = Array.from(selectedAddonIds);
			const mcpIds = Array.from(selectedMCPIds);
			const skillIds = Array.from(selectedSkillIds);

			optimisticMessageId =
				typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
					? crypto.randomUUID()
					: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;

			addUserMessage(
				text,
				fileIds.length > 0 ? fileIds : undefined,
				addonIds.length > 0 ? addonIds : undefined,
				mcpIds.length > 0 ? mcpIds : undefined,
				optimisticMessageId
			);
			noteSubmissionStart();

			await acquireSession({ conversationId });

			const metadata: Record<string, unknown> = {};
			if (fileIds.length > 0) metadata.files = fileIds;
			if (addonIds.length > 0) metadata.addons = addonIds;
			if (mcpIds.length > 0) metadata.mcp_configs = mcpIds;
			if (skillIds.length > 0) metadata.skill_ids = skillIds;

			const result = await startRun(conversationId, {
				task: text,
				conversationId,
				metadata: Object.keys(metadata).length > 0 ? metadata : undefined
			});

			const { injectionQueuePosition } = await import('$services/sse');
			injectionQueuePosition.set(null);

			if (result.status === 'message_injected') {
				// Sandbox absorbed the message into the running agent; SSE is
				// already connected (chat page acquired the session on mount).
				if (result.run_id && getCurrentConversationId() !== conversationId) {
					try {
						connectToRun(conversationId, result.run_id, true);
					} catch (err) {
						console.warn('[ActiveChatInput] failed to reconnect SSE:', err);
					}
				}
			} else if (result.run_id) {
				// status === 'running' — new run; connect SSE.
				try {
					connectToRun(conversationId, result.run_id, true);
				} catch (err) {
					console.warn('[ActiveChatInput] failed to start SSE:', err);
				}
			}

			prompt = '';
			attachedFiles = [];
			if (textareaEl) {
				textareaEl.style.height = 'auto';
			}
		} catch (err) {
			if (optimisticMessageId) {
				confirmUserMessage(optimisticMessageId);
			}
			const errorMsg =
				err instanceof ApiClientError ? err.message : 'Failed to send message. Please try again.';
			addErrorMessage(errorMsg);

			const limitInfo = detectLimitError(errorMsg);
			if (limitInfo) {
				usageLimitModal.show(limitInfo);
			}

			prompt = '';
			attachedFiles = [];
			if (textareaEl) {
				textareaEl.style.height = 'auto';
			}
		} finally {
			submitting = false;
		}
	}

	async function handleCancelRun(): Promise<void> {
		const convId = conversationId || getCurrentConversationId();
		if (!convId) {
			toasts.error('Cannot stop: no active connection.');
			return;
		}
		const runId = getCurrentRunId();
		if (!runId) {
			toasts.error('Cannot stop: no active run.');
			return;
		}

		cancelling = true;
		try {
			await cancelRunSandbox(convId, runId);
			toasts.info('Agent stopped.');
		} catch {
			toasts.error('Failed to stop the agent. Please try again.');
		} finally {
			cancelling = false;
		}
	}
</script>

<svelte:window onclick={handleWindowClick} />

{#if readOnly}
	<!-- Read-only banner -->
	<div class="flex items-center justify-center gap-2.5 border-t border-border-subtle px-4 py-3">
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
			class="text-muted"
		>
			<rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
			<path d="M7 11V7a5 5 0 0 1 10 0v4" />
		</svg>
		<span class="text-[14px] tracking-wide text-muted">This conversation is in read-only mode.</span
		>
	</div>
{:else}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="px-1.5 pt-1.5 sm:px-2"
		style={`padding-bottom: calc(env(safe-area-inset-bottom, 0px) + ${hasMessages ? 12 : 4}px); ${
			hasMessages ? 'padding-left: 12px; padding-right: 12px;' : ''
		}`}
		ondragenter={handleDragEnter}
		ondragleave={handleDragLeave}
		ondragover={handleDragOver}
		ondrop={handleDrop}
	>
		<!-- Drag overlay -->
		{#if dragOver}
			<div
				class="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-foreground/10"
				transition:fade={{ duration: 150 }}
			>
				<div
					class="border-pulse flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-accent bg-background/95 px-12 py-10"
					style="animation: scaleIn 0.2s var(--ease-spring) both, borderPulse 1.2s ease-in-out infinite"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="40"
						height="40"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="text-accent"
					>
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
						<polyline points="17 8 12 3 7 8" />
						<line x1="12" y1="3" x2="12" y2="15" />
					</svg>
					<p class="text-base font-medium text-foreground">Drop files here</p>
					<p class="text-sm text-subtle">Files up to 50MB</p>
				</div>
			</div>
		{/if}

		<!-- Hidden file input (shared between mobile + desktop) -->
		<input
			bind:this={fileInputEl}
			type="file"
			multiple
			class="hidden"
			onchange={handleFileInputChange}
			aria-label="File input"
		/>

		<!-- Active selector element chip (above file previews / composer) -->
		{#if activeSelection}
			<div class="mb-1.5 flex flex-wrap gap-1.5">
				<div
					class="inline-flex max-w-[280px] items-center gap-1.5 rounded border border-accent/30 bg-accent/10 px-2 py-1 font-sans text-xs text-accent"
					data-testid="active-selection-chip"
					title={selectionChipLabel(activeSelection)}
				>
					<MousePointer size={12} strokeWidth={2} aria-hidden="true" />
					<span class="truncate">{selectionChipLabel(activeSelection)}</span>
					<button
						type="button"
						onclick={() => clearSelectorSelection()}
						class="ml-0.5 flex h-4 w-4 items-center justify-center rounded-full text-accent/70 hover:bg-accent/20 hover:text-accent"
						aria-label="Clear selected element"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="8"
							height="8"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="3"
							stroke-linecap="round"
							stroke-linejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg
						>
					</button>
				</div>
			</div>
		{/if}

		<!-- Mobile file previews (above pill) -->
		{#if attachedFiles.length > 0}
			<div class="mb-1.5 flex flex-wrap gap-1.5 lg:hidden">
				{#each attachedFiles as file (file.id)}
					<div
						class="group relative flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-2 px-2.5 py-1 text-xs"
					>
						{#if file.previewUrl}
							<img
								src={file.previewUrl}
								alt={file.file.name}
								class="h-6 w-6 rounded object-cover"
							/>
						{:else}
							<span class="text-sm">{getFileIcon(file.file)}</span>
						{/if}
						<span class="max-w-[80px] truncate text-[11.5px] font-medium text-foreground"
							>{file.file.name}</span
						>
						<button
							onclick={() => removeFile(file.id)}
							class="ml-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-border-strong text-subtle"
							aria-label="Remove {file.file.name}"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="8"
								height="8"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="3"
								stroke-linecap="round"
								stroke-linejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg
							>
						</button>
					</div>
				{/each}
			</div>
		{/if}

		<!-- Main input container: pill on mobile, box on desktop -->
		<div
			data-active-chat-composer
			class="relative flex items-end gap-2 rounded-[28px] border border-border bg-surface p-1.5 shadow-lg
				lg:block lg:rounded-xl lg:p-0 lg:shadow-none lg:transition-all lg:duration-200 lg:focus-within:border-accent lg:focus-within:ring-3 lg:focus-within:ring-accent/12"
		>
			<!-- Mobile: + button (left of textarea) -->
			<button
				onclick={() => fileInputEl?.click()}
				disabled={submitting || isSubmitBlocked}
				class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted disabled:opacity-40 lg:hidden"
				aria-label="Attach file"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"><path d="M12 5v14" /><path d="M5 12h14" /></svg
				>
			</button>

			<!-- Desktop: file previews inside container -->
			{#if attachedFiles.length > 0}
				<div class="hidden flex-wrap gap-1.5 px-3 pt-3 lg:flex">
					{#each attachedFiles as file (file.id)}
						<div
							class="group relative flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-2 px-2.5 py-1 text-xs"
						>
							{#if file.previewUrl}
								<img
									src={file.previewUrl}
									alt={file.file.name}
									class="h-6 w-6 rounded object-cover"
								/>
							{:else}
								<span class="text-sm">{getFileIcon(file.file)}</span>
							{/if}
							<div class="flex flex-col">
								<span class="max-w-[100px] truncate text-[11.5px] font-medium text-foreground"
									>{file.file.name}</span
								>
								<span class="text-[10.5px] text-muted">{formatFileSize(file.file.size)}</span>
							</div>
							{#if file.uploading}
								<svg
									class="h-3 w-3 animate-spin text-muted"
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									><circle
										class="opacity-25"
										cx="12"
										cy="12"
										r="10"
										stroke="currentColor"
										stroke-width="4"
									></circle><path
										class="opacity-75"
										fill="currentColor"
										d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
									></path></svg
								>
							{/if}
							<button
								onclick={() => removeFile(file.id)}
								class="ml-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-border-strong text-subtle opacity-0 transition-opacity hover:bg-border hover:text-foreground group-hover:opacity-100"
								aria-label="Remove {file.file.name}"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="8"
									height="8"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="3"
									stroke-linecap="round"
									stroke-linejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg
								>
							</button>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Desktop: sandbox busy indicator -->
			{#if isSandboxBusy}
				<div class="hidden items-center gap-2 px-3.5 pt-2.5 pb-0 lg:flex">
					<span class="relative flex h-2 w-2">
						<span
							class="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75"
						></span>
						<span class="relative inline-flex h-2 w-2 rounded-full bg-amber-500"></span>
					</span>
					<span class="text-[11.5px] text-amber-600 dark:text-amber-400">
						Sandbox busy
						{#if sandboxBusyConversation?.conversationTitle}
							&mdash; used by <span class="font-medium"
								>{sandboxBusyConversation.conversationTitle}</span
							>
						{/if}
					</span>
				</div>
			{/if}

			<!-- Textarea -->
			<textarea
				bind:this={textareaEl}
				bind:value={prompt}
				oninput={handleInput}
				onkeydown={handleKeydown}
				onpaste={handlePaste}
				placeholder={viewOnlyMessage
					? viewOnlyMessage
					: isSandboxBusy
						? 'Waiting for sandbox... type to queue'
						: isRunActive
							? 'Send a message to queue...'
							: 'Ask anything'}
				rows="1"
				disabled={submitting || runStatus === 'waiting_for_input' || !!viewOnlyMessage}
				class="min-w-0 flex-1 resize-none bg-transparent py-2 text-sm text-foreground outline-none placeholder:text-muted disabled:opacity-50
					lg:w-full lg:flex-none lg:px-5 lg:py-2.5 lg:text-[15px]"
				style="max-height: 120px;"
			></textarea>

			<MentionAutocomplete
				bind:prompt
				{textareaEl}
				addons={availableAddons}
				mcps={availableMCPs}
				skills={availableSkills}
				{selectedAddonIds}
				{selectedMCPIds}
				{selectedSkillIds}
			/>

			<!-- Vim mode indicator (feature flag: keyboard-vim-mode) -->
			{#if vimEnabled}
				<div
					class="pointer-events-none absolute bottom-1 left-3 font-mono text-[10px] lg:left-5 {vimMode ===
					'normal'
						? 'text-accent'
						: 'text-muted/50'}"
				>
					{vimMode === 'normal' ? '-- NORMAL --' : '-- INSERT --'}
				</div>
			{/if}

			<!-- Mobile: send/stop/voice button (right of textarea) -->
			<div class="shrink-0 lg:hidden">
				{#if isRunActive}
					<button
						onclick={handleCancelRun}
						disabled={cancelling}
						class="flex h-9 items-center gap-1.5 rounded-full bg-error/15 px-3 text-error"
						aria-label="Stop agent"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="12"
							height="12"
							viewBox="0 0 24 24"
							fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg
						>
					</button>
				{:else if prompt.trim() || submitting}
					<button
						onclick={submitMessage}
						disabled={!canSubmit}
						class="flex h-9 shrink-0 items-center justify-center rounded-full bg-foreground px-4 text-background transition-all disabled:opacity-25"
						aria-label="Send"
					>
						{#if submitting}
							<svg
								class="h-4 w-4 animate-spin"
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								><circle
									class="opacity-25"
									cx="12"
									cy="12"
									r="10"
									stroke="currentColor"
									stroke-width="4"
								></circle><path
									class="opacity-75"
									fill="currentColor"
									d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
								></path></svg
							>
						{:else}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="16"
								height="16"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></svg
							>
						{/if}
					</button>
				{:else if voiceSupported}
					<button
						onclick={toggleVoice}
						class="flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-muted
							{isRecording ? 'animate-pulse bg-error/15 text-error' : 'bg-surface-2'}"
						aria-label={isRecording ? 'Stop recording' : 'Voice input'}
					>
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
						>
							<line x1="4" y1="8" x2="4" y2="16" /><line x1="8" y1="5" x2="8" y2="19" /><line
								x1="12"
								y1="3"
								x2="12"
								y2="21"
							/><line x1="16" y1="5" x2="16" y2="19" /><line x1="20" y1="8" x2="20" y2="16" />
						</svg>
						<span class="text-xs font-medium">Voice</span>
					</button>
				{/if}
			</div>

			<!-- Desktop: bottom toolbar -->
			<div class="hidden items-center justify-between px-3 pb-2.5 lg:flex">
				<!-- Left: + attach, tools, voice -->
				<div class="flex items-center gap-0.5">
					<!-- Attach file (+ button) -->
					<button
						onclick={() => fileInputEl?.click()}
						disabled={submitting || isSubmitBlocked}
						class="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors duration-100 hover:bg-surface hover:text-subtle disabled:opacity-40"
						aria-label="Attach file"
						use:tooltip={'Attach file'}
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
							<path d="M12 5v14" />
							<path d="M5 12h14" />
						</svg>
					</button>

					<!-- Tools popover (addons + MCPs combined) -->
					<div class="relative" data-tools-popover>
						<button
							onclick={() => {
								toolsPopoverOpen = !toolsPopoverOpen;
							}}
							disabled={submitting || isSubmitBlocked}
							class="flex h-8 items-center gap-1 rounded-lg px-1.5 text-muted transition-colors duration-100 hover:bg-surface hover:text-subtle disabled:opacity-40 {totalToolCount >
							0
								? 'text-accent'
								: ''}"
							aria-label="Select tools"
							use:tooltip={'Tools'}
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
								<path
									d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
								/>
							</svg>
							{#if totalToolCount > 0}
								<span class="text-[11.5px] font-medium">{totalToolCount}</span>
							{/if}
						</button>

						{#if toolsPopoverOpen}
							<!-- svelte-ignore a11y_no_static_element_interactions -->
							<!-- svelte-ignore a11y_click_events_have_key_events -->
							<div
								transition:fade={{ duration: 140 }}
								class="absolute bottom-full left-0 z-50 mb-2 w-72 rounded-xl border border-border-subtle bg-surface-2 shadow-xl"
								onclick={(e) => e.stopPropagation()}
							>
								<!-- Addons section -->
								<div class="border-b border-border-subtle px-3 py-2.5">
									<h3 class="text-[14px] font-medium uppercase tracking-wide text-muted">Addons</h3>
								</div>
								<div class="max-h-40 overflow-y-auto px-2 py-1.5">
									{#if addonLoading}
										<div class="flex items-center justify-center py-3">
											<svg
												class="h-4 w-4 animate-spin text-muted"
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
									{:else if availableAddons.length === 0}
										<p class="py-3 text-center text-[11.5px] text-muted">No authorized addons</p>
									{:else}
										<div class="flex flex-wrap gap-1.5">
											{#each availableAddons as addon (addon.id)}
												<button
													onclick={() => toggleAddon(addon.id)}
													class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-all duration-100 {selectedAddonIds.has(
														addon.id
													)
														? 'border-accent/30 bg-accent/10 text-accent'
														: 'border-border-subtle text-subtle hover:border-border hover:text-foreground'}"
													aria-pressed={selectedAddonIds.has(addon.id)}
												>
													{#if addon.enabled_addon.logo}
														<img
															src={addon.enabled_addon.logo}
															alt=""
															class="h-3.5 w-3.5 rounded-sm"
														/>
													{/if}
													{addon.enabled_addon.name}
													{#if selectedAddonIds.has(addon.id)}
														<svg
															xmlns="http://www.w3.org/2000/svg"
															width="10"
															height="10"
															viewBox="0 0 24 24"
															fill="none"
															stroke="currentColor"
															stroke-width="3"
															stroke-linecap="round"
															stroke-linejoin="round"
														>
															<polyline points="20 6 9 17 4 12" />
														</svg>
													{/if}
												</button>
											{/each}
										</div>
									{/if}
								</div>

								<!-- MCPs section -->
								<div class="border-y border-border-subtle px-3 py-2.5">
									<h3 class="text-[14px] font-medium uppercase tracking-wide text-muted">
										MCP Servers
									</h3>
								</div>
								<div class="max-h-40 overflow-y-auto px-1.5 py-1.5">
									{#if mcpLoading}
										<div class="flex items-center justify-center py-3">
											<svg
												class="h-4 w-4 animate-spin text-muted"
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
									{:else if availableMCPs.length === 0}
										<p class="py-3 text-center text-[11.5px] text-muted">
											No custom MCPs configured
										</p>
									{:else}
										<div class="flex flex-col gap-0.5">
											{#each availableMCPs as mcp (mcp.id)}
												<button
													onclick={() => toggleMCP(mcp.id)}
													class="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-all duration-100 {selectedMCPIds.has(
														mcp.id
													)
														? 'bg-accent/8'
														: 'hover:bg-surface-2'}"
													aria-pressed={selectedMCPIds.has(mcp.id)}
												>
													<div
														class="flex h-6 w-6 shrink-0 items-center justify-center rounded {selectedMCPIds.has(
															mcp.id
														)
															? 'bg-accent/15 text-accent'
															: 'bg-surface-2 text-muted'}"
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
															<path
																d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"
															/>
														</svg>
													</div>
													<div class="min-w-0 flex-1">
														<div
															class="truncate text-[11.5px] font-medium {selectedMCPIds.has(mcp.id)
																? 'text-accent'
																: 'text-foreground'}"
														>
															{mcp.server_name}
														</div>
														{#if mcp.description}
															<div class="truncate text-[10.5px] text-muted">
																{mcp.description}
															</div>
														{/if}
													</div>
													{#if selectedMCPIds.has(mcp.id)}
														<svg
															xmlns="http://www.w3.org/2000/svg"
															width="12"
															height="12"
															viewBox="0 0 24 24"
															fill="none"
															stroke="currentColor"
															stroke-width="3"
															stroke-linecap="round"
															stroke-linejoin="round"
															class="shrink-0 text-accent"
														>
															<polyline points="20 6 9 17 4 12" />
														</svg>
													{/if}
												</button>
											{/each}
										</div>
									{/if}
								</div>

								<!-- Skills section -->
								<div class="border-y border-border-subtle px-3 py-2.5">
									<h3 class="text-[14px] font-medium uppercase tracking-wide text-muted">Skills</h3>
								</div>
								<div class="max-h-40 overflow-y-auto px-1.5 py-1.5">
									{#if skillLoading}
										<div class="flex items-center justify-center py-3">
											<svg
												class="h-4 w-4 animate-spin text-muted"
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
									{:else if availableSkills.length === 0}
										<p class="py-3 text-center text-[11.5px] text-muted">No installed skills</p>
									{:else}
										<div class="flex flex-col gap-0.5">
											{#each availableSkills as skill (skill.slug)}
												<button
													onclick={() => toggleSkill(skill.slug)}
													class="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-all duration-100 {selectedSkillIds.has(
														skill.slug
													)
														? 'bg-accent/8'
														: 'hover:bg-surface-2'}"
													aria-pressed={selectedSkillIds.has(skill.slug)}
												>
													<div
														class="flex h-6 w-6 shrink-0 items-center justify-center rounded {selectedSkillIds.has(
															skill.slug
														)
															? 'bg-accent/15 text-accent'
															: 'bg-surface-2 text-muted'}"
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
															<path
																d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"
															/>
														</svg>
													</div>
													<div class="min-w-0 flex-1">
														<div
															class="truncate text-[11.5px] font-medium {selectedSkillIds.has(
																skill.slug
															)
																? 'text-accent'
																: 'text-foreground'}"
														>
															{skill.name}
														</div>
														{#if skill.description}
															<div class="truncate text-[10.5px] text-muted">
																{skill.description}
															</div>
														{/if}
													</div>
													{#if selectedSkillIds.has(skill.slug)}
														<svg
															xmlns="http://www.w3.org/2000/svg"
															width="12"
															height="12"
															viewBox="0 0 24 24"
															fill="none"
															stroke="currentColor"
															stroke-width="3"
															stroke-linecap="round"
															stroke-linejoin="round"
															class="shrink-0 text-accent"
														>
															<polyline points="20 6 9 17 4 12" />
														</svg>
													{/if}
												</button>
											{/each}
										</div>
									{/if}
								</div>
							</div>
						{/if}
					</div>

					<!-- Voice input -->
					{#if voiceSupported}
						<button
							onclick={toggleVoice}
							disabled={submitting || isSubmitBlocked}
							class="flex h-8 w-8 items-center justify-center rounded-lg transition-colors duration-100 disabled:opacity-40 {isRecording
								? 'animate-pulse bg-error/12 text-error'
								: 'text-muted hover:bg-surface hover:text-subtle'}"
							aria-label={isRecording ? 'Stop recording' : 'Voice input'}
							use:tooltip={isRecording ? 'Stop recording' : 'Voice input'}
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
								{#if isRecording}
									<rect x="6" y="4" width="4" height="16" rx="1" />
									<rect x="14" y="4" width="4" height="16" rx="1" />
								{:else}
									<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
									<path d="M19 10v2a7 7 0 0 1-14 0v-2" />
									<line x1="12" x2="12" y1="19" y2="22" />
								{/if}
							</svg>
						</button>
					{/if}

					<!-- Recording indicator -->
					{#if isRecording}
						<span
							in:fade={{ duration: 150 }}
							out:fade={{ duration: 100 }}
							class="ml-1 text-[11.5px] font-medium text-error"
						>
							Recording...
						</span>
					{/if}

					<!-- Tool selection indicator -->
					{#if totalToolCount > 0 && !isRecording}
						<span
							in:fade={{ duration: 150 }}
							out:fade={{ duration: 100 }}
							class="ml-1 text-[11.5px] text-accent"
						>
							{totalToolCount} tool{totalToolCount > 1 ? 's' : ''} selected
						</span>
					{/if}
				</div>

				<!-- Right: stop + send -->
				<div class="flex items-center gap-1.5">
					{#if isRunActive}
						<button
							onclick={handleCancelRun}
							disabled={cancelling}
							class="flex h-7 items-center gap-1.5 rounded-lg bg-error/8 px-2.5 text-error transition-colors duration-100 hover:bg-error/15 disabled:opacity-50"
							aria-label="Stop agent"
							use:tooltip={'Stop'}
						>
							{#if cancelling}
								<svg
									class="h-3.5 w-3.5 animate-spin"
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
							{:else}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="12"
									height="12"
									viewBox="0 0 24 24"
									fill="currentColor"
								>
									<rect x="6" y="6" width="12" height="12" rx="2" />
								</svg>
							{/if}
							<span class="text-[11.5px] font-medium">Stop</span>
						</button>
					{/if}

					<!-- Send button — dark square like Replit -->
					<button
						onclick={submitMessage}
						disabled={!canSubmit}
						class="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-25 disabled:hover:opacity-25"
						aria-label="Send message"
						use:tooltip={'Send'}
					>
						{#if submitting}
							<svg
								class="h-3.5 w-3.5 animate-spin"
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
						{:else}
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
							>
								<path d="M5 12h14" />
								<path d="m12 5 7 7-7 7" />
							</svg>
						{/if}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
