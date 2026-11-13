<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		ArrowUp,
		ArrowRight,
		Paperclip,
		Globe,
		TerminalSquare,
		Search,
		Users,
		TrendingUp,
		FileSpreadsheet,
		ShieldCheck,
		FileText
	} from '@lucide/svelte';
	import { LoadingSpinner } from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { currentUser } from '$stores/auth';
	import { toasts } from '$stores/toast';
	import { startRun } from '$api/run';
	import { acquireSession } from '$stores/sandboxSession';
	import { uploadFile } from '$api/files';
	import { getUserAddons } from '$api/addons';
	import { getMCPConfigs } from '$api/mcp';
	import { getInstalledSkills, type SkillCatalog } from '$api/skills';
	import { subscription as subscriptionStore, ensureSubscription } from '$stores/subscription';
	import { isSessionFresh, markSessionFetched } from '$stores/freshness';
	import { fetchConversations, conversations } from '$stores/conversations';
	import { noteSubmissionStart, setPendingPrompt } from '$services/sse';
	import type { UserAddon, UserMCPConfig, Conversation } from '$api/types';
	import ToolsPopover from '$components/home/ToolsPopover.svelte';
	import MentionAutocomplete from '$components/chat/MentionAutocomplete.svelte';

	const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
	const PASTE_TEXT_THRESHOLD = 5000;

	let userName = $state('');
	let recentConversations: Conversation[] = $state([]);

	const unsubCurrentUser = currentUser.subscribe((u) => {
		if (u) {
			userName = u.name?.split(' ')[0] || '';
		}
	});
	onDestroy(unsubCurrentUser);

	const unsubConversations = conversations.subscribe((items) => {
		recentConversations = items.slice(0, 5);
	});
	onDestroy(unsubConversations);

	function greetingPrefix(): string {
		const h = new Date().getHours();
		if (h < 5) return 'Hello';
		if (h < 12) return 'Good morning';
		if (h < 18) return 'Good afternoon';
		return 'Good evening';
	}

	interface StarterPrompt {
		icon: typeof Search;
		title: string;
		prompt: string;
	}

	const STARTER_PROMPTS: StarterPrompt[] = [
		{
			icon: Search,
			title: 'Research a market or industry',
			prompt: 'Research the market and industry for '
		},
		{
			icon: Users,
			title: 'Analyze competitors',
			prompt: 'Analyze the main competitors for '
		},
		{
			icon: TrendingUp,
			title: 'Create a go-to-market strategy',
			prompt: 'Create a go-to-market strategy for '
		},
		{
			icon: FileSpreadsheet,
			title: 'Build a financial model',
			prompt: 'Build a financial model for '
		},
		{
			icon: ShieldCheck,
			title: 'Audit a product or website',
			prompt: 'Audit the product or website at '
		}
	];

	interface AttachedFile {
		id: string;
		file: File;
		previewUrl: string | null;
		uploading: boolean;
		uploadedId: string | null;
	}

	let prompt = $state('');
	let loading = $state(false);
	let textareaEl: HTMLTextAreaElement | undefined = $state(undefined);
	let attachedFiles: AttachedFile[] = $state([]);
	let dragOver = $state(false);
	let dragCounter = $state(0);

	function loadSessionCache<T>(key: string): T | null {
		try {
			const raw = sessionStorage.getItem(key);
			if (raw) return JSON.parse(raw) as T;
		} catch {
			/* ignore */
		}
		return null;
	}
	function setSessionCache(key: string, data: unknown): void {
		try {
			sessionStorage.setItem(key, JSON.stringify(data));
		} catch {
			/* ignore */
		}
	}

	let availableAddons: UserAddon[] = $state(
		loadSessionCache<UserAddon[]>('midsphere-home-addons') ?? []
	);
	let selectedAddonIds = new SvelteSet<string>();
	let addonLoading = $state(false);

	let availableMCPs: UserMCPConfig[] = $state(
		loadSessionCache<UserMCPConfig[]>('midsphere-home-mcps') ?? []
	);
	let selectedMCPIds = new SvelteSet<string>();
	let mcpLoading = $state(false);

	let availableSkills: SkillCatalog[] = $state(
		loadSessionCache<SkillCatalog[]>('midsphere-home-skills') ?? []
	);
	let selectedSkillIds = new SvelteSet<string>();
	let skillLoading = $state(false);

	let planName = $state('Free');

	subscriptionStore.subscribe((sub) => {
		if (sub) {
			planName = sub.plan?.name ?? 'Free';
		}
	});

	let urlMode: string | null = null;

	onMount(() => {
		pageTitle.set('Jatayu AI');
		showHeaderTitle.set(true);
		textareaEl?.focus();
		if (!isSessionFresh('midsphere-home-addons', 120_000)) loadAddons();
		if (!isSessionFresh('midsphere-home-mcps', 120_000)) loadMCPs();
		if (!isSessionFresh('midsphere-home-skills', 120_000)) loadSkills();
		ensureSubscription();
		fetchConversations();

		// Handle ?prompt=, ?mode=, ?autosubmit=
		const params = page.url.searchParams;
		const urlPrompt = params.get('prompt');
		if (urlPrompt) {
			prompt = urlPrompt;
			urlMode = params.get('mode');

			const cleanUrl = page.url.pathname;
			history.replaceState(history.state, '', cleanUrl);

			requestAnimationFrame(() => {
				if (textareaEl) autoResize(textareaEl);
				textareaEl?.focus();

				if (params.get('autosubmit') === 'true') {
					submitPrompt(urlMode ?? undefined);
				}
			});
		}

		// ⌘K / Ctrl+K focuses the input
		const onKeydown = (e: KeyboardEvent) => {
			if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
				e.preventDefault();
				textareaEl?.focus();
			}
		};
		window.addEventListener('keydown', onKeydown);
		return () => window.removeEventListener('keydown', onKeydown);
	});

	// --- Data loading ---

	async function loadAddons(): Promise<void> {
		if (availableAddons.length === 0) addonLoading = true;
		try {
			const response = await getUserAddons();
			availableAddons = response.items.filter((a) => a.auth_complete);
			setSessionCache('midsphere-home-addons', availableAddons);
			markSessionFetched('midsphere-home-addons');
		} catch {
			// silent
		} finally {
			addonLoading = false;
		}
	}

	async function loadMCPs(): Promise<void> {
		if (availableMCPs.length === 0) mcpLoading = true;
		try {
			const response = await getMCPConfigs();
			availableMCPs = response.items;
			setSessionCache('midsphere-home-mcps', availableMCPs);
			markSessionFetched('midsphere-home-mcps');
		} catch {
			// silent
		} finally {
			mcpLoading = false;
		}
	}

	async function loadSkills(): Promise<void> {
		if (availableSkills.length === 0) skillLoading = true;
		try {
			const response = await getInstalledSkills();
			availableSkills = response.items;
			setSessionCache('midsphere-home-skills', availableSkills);
			markSessionFetched('midsphere-home-skills');
		} catch {
			// silent
		} finally {
			skillLoading = false;
		}
	}

	// --- Input ---

	function autoResize(el: HTMLTextAreaElement): void {
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 240) + 'px';
	}

	function handleInput(e: Event): void {
		const target = e.target as HTMLTextAreaElement;
		autoResize(target);
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submitPrompt();
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

	// --- Files ---

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

	function handleFileSelect(files: FileList): void {
		addFiles(Array.from(files));
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

	// --- Submit ---

	async function submitPrompt(mode?: string): Promise<void> {
		const text = prompt.trim();
		if ((!text && attachedFiles.length === 0) || loading) return;

		const stillUploading = attachedFiles.some((f) => f.uploading);
		if (stillUploading) {
			toasts.warning('Please wait for files to finish uploading.');
			return;
		}

		loading = true;
		try {
			const fileIds = attachedFiles
				.map((f) => f.uploadedId)
				.filter((id): id is string => id !== null);

			const addonIds = Array.from(selectedAddonIds);
			const mcpIds = Array.from(selectedMCPIds);
			const skillIds = Array.from(selectedSkillIds);
			const taskText = mode ? `[${mode}] ${text}` : text;
			noteSubmissionStart();
			setPendingPrompt(taskText);

			const session = await acquireSession({ promptPreview: taskText });

			const metadata: Record<string, unknown> = { is_new_conversation: true };
			if (fileIds.length > 0) metadata.files = fileIds;
			if (addonIds.length > 0) metadata.addons = addonIds;
			if (mcpIds.length > 0) metadata.mcp_configs = mcpIds;
			if (skillIds.length > 0) metadata.skill_ids = skillIds;

			await startRun(session.conversationId, {
				task: taskText,
				conversationId: session.conversationId,
				metadata
			});

			fetchConversations();
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto(`/chat/${session.conversationId}`);
		} catch (err) {
			console.error('[home] submitPrompt failed:', err);
			const detail =
				err instanceof Error ? err.message : typeof err === 'string' ? err : 'Unknown error';
			toasts.error(`Failed to start task: ${detail}`);
		} finally {
			loading = false;
		}
	}

	function handleStarterSelect(starter: StarterPrompt): void {
		prompt = starter.prompt;
		if (textareaEl) {
			autoResize(textareaEl);
			textareaEl.focus();
			// Move cursor to end
			const len = textareaEl.value.length;
			textareaEl.setSelectionRange(len, len);
		}
	}

	function formatRelativeTime(iso: string): string {
		const d = new Date(iso);
		const now = new Date();
		const sameDay =
			d.getFullYear() === now.getFullYear() &&
			d.getMonth() === now.getMonth() &&
			d.getDate() === now.getDate();
		if (sameDay) {
			return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
		}
		const yesterday = new Date(now);
		yesterday.setDate(now.getDate() - 1);
		const isYesterday =
			d.getFullYear() === yesterday.getFullYear() &&
			d.getMonth() === yesterday.getMonth() &&
			d.getDate() === yesterday.getDate();
		if (isYesterday) return 'Yesterday';
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	function statusLabel(c: Conversation): string {
		switch (c.status) {
			case 'running':
			case 'provisioning':
			case 'queued':
				return 'Running';
			case 'completed':
				return 'Completed';
			case 'failed':
				return 'Failed';
			case 'cancelled':
				return 'Cancelled';
			default:
				return 'Idle';
		}
	}

	function statusColorClass(c: Conversation): string {
		switch (c.status) {
			case 'running':
			case 'provisioning':
			case 'queued':
				return 'text-accent';
			case 'failed':
				return 'text-error';
			case 'cancelled':
				return 'text-muted';
			default:
				return 'text-muted';
		}
	}

	let hasFiles = $derived(attachedFiles.length > 0);
	let canSubmit = $derived((prompt.trim().length > 0 || hasFiles) && !loading);
	let fileInputEl: HTMLInputElement | undefined = $state(undefined);

	function onPaperclipClick(): void {
		fileInputEl?.click();
	}
	function onFileInputChange(e: Event): void {
		const input = e.target as HTMLInputElement;
		if (input.files?.length) handleFileSelect(input.files);
		input.value = '';
	}
</script>

<svelte:head>
	<title>Home — Jatayu AI</title>
</svelte:head>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="min-h-[100dvh] px-4 pb-24 pt-10 sm:px-6 lg:pt-16"
	ondragenter={handleDragEnter}
	ondragleave={handleDragLeave}
	ondragover={handleDragOver}
	ondrop={handleDrop}
>
	<!-- Drag overlay -->
	{#if dragOver}
		<div
			class="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-background/80"
		>
			<div
				class="flex flex-col items-center gap-3 rounded-xl border border-accent bg-surface px-12 py-10"
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

	<!-- Hidden file input -->
	<input bind:this={fileInputEl} type="file" multiple class="hidden" onchange={onFileInputChange} />

	<div class="mx-auto w-full max-w-3xl">
		<!-- Greeting -->
		<h1 class="text-3xl font-medium tracking-tight text-foreground">
			{greetingPrefix()}{userName ? `, ${userName}` : ''}.
		</h1>
		<p class="mt-2 text-lg text-muted">What shall we build or research today?</p>

		<!-- Task input card -->
		<div
			class="mt-6 rounded-xl border border-border bg-surface transition-colors focus-within:border-border-strong"
		>
			{#if hasFiles}
				<div class="flex flex-wrap gap-2 px-4 pt-4">
					{#each attachedFiles as file (file.id)}
						<div
							class="group relative flex items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm"
						>
							{#if file.previewUrl}
								<img
									src={file.previewUrl}
									alt={file.file.name}
									class="h-7 w-7 rounded object-cover"
								/>
							{:else}
								<FileText class="h-4 w-4 text-muted" />
							{/if}
							<div class="flex flex-col">
								<span class="max-w-[140px] truncate text-xs font-medium text-foreground"
									>{file.file.name}</span
								>
								<span class="text-[10px] text-subtle">{formatFileSize(file.file.size)}</span>
							</div>
							{#if file.uploading}
								<LoadingSpinner />
							{/if}
							<button
								onclick={() => removeFile(file.id)}
								class="ml-1 flex h-4 w-4 items-center justify-center rounded-full text-subtle transition-colors hover:text-foreground"
								aria-label="Remove {file.file.name}"
							>
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
									<path d="M18 6 6 18" />
									<path d="m6 6 12 12" />
								</svg>
							</button>
						</div>
					{/each}
				</div>
			{/if}

			<textarea
				bind:this={textareaEl}
				bind:value={prompt}
				oninput={handleInput}
				onkeydown={handleKeydown}
				onpaste={handlePaste}
				placeholder="Describe your task or goal…"
				rows="3"
				disabled={loading}
				class="w-full resize-none bg-transparent px-5 pt-5 pb-3 text-[15px] leading-relaxed text-foreground outline-none placeholder:text-subtle disabled:opacity-60"
			></textarea>

			<div class="flex items-center justify-between px-3 pb-3">
				<div class="flex items-center gap-1">
					<!-- Paperclip / file attach -->
					<button
						type="button"
						onclick={onPaperclipClick}
						class="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
						aria-label="Attach file"
					>
						<Paperclip class="h-4 w-4" />
					</button>

					<!-- Globe = web search (hint / future toggle) -->
					<button
						type="button"
						class="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
						aria-label="Web search"
						title="Web search"
					>
						<Globe class="h-4 w-4" />
					</button>

					<!-- Terminal = tools/skills/mcp popover -->
					<ToolsPopover
						{loading}
						{availableAddons}
						{selectedAddonIds}
						{addonLoading}
						{availableMCPs}
						{selectedMCPIds}
						{mcpLoading}
						{availableSkills}
						{selectedSkillIds}
						{skillLoading}
						onfileselect={handleFileSelect}
					/>

					<!-- Mention autocomplete (hidden trigger, stays mounted for @-mentions) -->
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
				</div>

				<button
					onclick={() => submitPrompt()}
					disabled={!canSubmit}
					class="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-2 text-muted transition-colors duration-200 hover:bg-accent hover:text-[var(--on-accent)] disabled:opacity-30 disabled:hover:bg-surface-2 disabled:hover:text-muted"
					aria-label="Send"
				>
					{#if loading}
						<LoadingSpinner />
					{:else}
						<ArrowUp class="h-4 w-4" />
					{/if}
				</button>
			</div>
		</div>

		<!-- Try starting with -->
		<div class="mt-8">
			<p class="mb-3 text-sm font-medium text-muted">Try starting with</p>
			<ul class="border-y border-border">
				{#each STARTER_PROMPTS as starter, i}
					{@const StarterIcon = starter.icon}
					<li class={i > 0 ? 'border-t border-border' : ''}>
						<button
							type="button"
							onclick={() => handleStarterSelect(starter)}
							class="group flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-surface"
						>
							<span class="flex items-center gap-3">
								<StarterIcon class="h-4 w-4 text-muted" />
								<span class="text-[15px] text-foreground">{starter.title}</span>
							</span>
							<ArrowRight
								class="h-4 w-4 text-subtle transition-colors group-hover:text-foreground"
							/>
						</button>
					</li>
				{/each}
			</ul>
		</div>

		<!-- Recent tasks -->
		{#if recentConversations.length > 0}
			<div class="mt-10">
				<div class="mb-3 flex items-center justify-between">
					<p class="text-sm font-medium text-foreground">Recent tasks</p>
					<a href="/library" class="text-sm text-muted transition-colors hover:text-foreground">
						View all tasks
					</a>
				</div>
				<ul class="border-y border-border">
					{#each recentConversations as conv, i (conv.id)}
						<li class={i > 0 ? 'border-t border-border' : ''}>
							<a
								href="/chat/{conv.id}"
								class="flex items-center justify-between px-4 py-3 transition-colors hover:bg-surface"
							>
								<span class="flex min-w-0 items-center gap-3">
									<FileText class="h-4 w-4 flex-shrink-0 text-muted" />
									<span class="truncate text-[15px] text-foreground">
										{conv.title || 'Untitled'}
									</span>
								</span>
								<span class="flex flex-shrink-0 items-center gap-6 text-sm">
									<span class={statusColorClass(conv)}>{statusLabel(conv)}</span>
									<span class="w-20 text-right text-muted">
										{formatRelativeTime(conv.date_updated || conv.date_created)}
									</span>
								</span>
							</a>
						</li>
					{/each}
				</ul>
			</div>
		{/if}

		<!-- Footer hint -->
		<p class="mt-12 text-center text-xs text-muted">
			Press
			<kbd
				class="mx-1 inline-flex items-center rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[11px] text-foreground"
			>
				⌘K
			</kbd>
			to create a new task
		</p>
	</div>
</div>
