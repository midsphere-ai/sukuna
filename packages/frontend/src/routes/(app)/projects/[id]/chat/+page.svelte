<script lang="ts">
	import { page } from '$app/state';
	import { onMount, onDestroy } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Skeleton, LoadingSpinner } from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { setActiveProject } from '$stores/projects';
	import { toasts } from '$stores/toast';
	import { startRun } from '$api/run';
	import { acquireSession } from '$stores/sandboxSession';
	import { uploadFile } from '$api/files';
	import { getProject, listProjectFiles } from '$api/projects';
	import { getUserAddons } from '$api/addons';
	import { getMCPConfigs } from '$api/mcp';
	import { getInstalledSkills, type SkillCatalog } from '$api/skills';
	import { subscription as subscriptionStore, ensureSubscription } from '$stores/subscription';
	import { isSessionFresh, markSessionFetched } from '$stores/freshness';
	import { noteSubmissionStart, setPendingPrompt } from '$services/sse';
	import { fetchConversations } from '$stores/conversations';
	import type { ProjectDetail, ProjectFile, UserAddon, UserMCPConfig } from '$api/types';
	import HomeProjectSwitcher from '$components/home/HomeProjectSwitcher.svelte';
	import ToolsPopover from '$components/home/ToolsPopover.svelte';
	import MentionAutocomplete from '$components/chat/MentionAutocomplete.svelte';
	import ExamplePrompts from '$components/home/ExamplePrompts.svelte';
	import CreditBadge from '$components/layout/CreditBadge.svelte';
	import ProjectSettingsPanel from '$components/projects/ProjectSettingsPanel.svelte';

	const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB
	const PASTE_TEXT_THRESHOLD = 5000;

	let projectId = $derived(page.params.id ?? '');

	// Project state
	let project: ProjectDetail | null = $state(null);
	let projectLoading = $state(true);
	let projectFiles: ProjectFile[] = $state([]);
	let accessDenied = $state(false);

	// Settings drawer
	let settingsDrawerOpen = $state(false);

	function handleProjectSettingsUpdated(updated: ProjectDetail): void {
		if (project) {
			project = {
				...project,
				title: updated.title,
				description: updated.description,
				icon: updated.icon,
				custom_instructions: updated.custom_instructions
			};
			pageTitle.set(updated.title);
		}
		loadFiles();
	}

	function handleProjectSettingsDeleted(): void {
		settingsDrawerOpen = false;
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- internal route
		goto('/');
	}

	function handleSettingsKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			settingsDrawerOpen = false;
		}
	}

	// Composer state — mirrors home page
	let prompt = $state('');
	let loading = $state(false);
	let textareaEl: HTMLTextAreaElement | undefined = $state(undefined);

	interface AttachedFile {
		id: string;
		file: File;
		previewUrl: string | null;
		uploading: boolean;
		uploadedId: string | null;
	}

	let attachedFiles: AttachedFile[] = $state([]);
	let dragOver = $state(false);
	let dragCounter = $state(0);

	// Addon/MCP selector state — mirrors home sessionStorage caching
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

	// Voice input
	let isRecording = $state(false);
	let recognition: SpeechRecognition | null = null;
	let voiceSupported = $state(false);

	let planName = $state('Free');

	subscriptionStore.subscribe((sub) => {
		if (sub) {
			planName = sub.plan?.name ?? 'Free';
		}
	});

	async function loadProject(): Promise<void> {
		projectLoading = true;
		accessDenied = false;
		try {
			const detail = await getProject(projectId);
			project = detail;
			pageTitle.set(detail.title);
		} catch (err: unknown) {
			const status = (err as { status?: number })?.status;
			if (status === 403 || status === 404) {
				accessDenied = true;
			} else {
				toasts.error('Failed to load project');
			}
		} finally {
			projectLoading = false;
		}
	}

	async function loadFiles(): Promise<void> {
		try {
			projectFiles = await listProjectFiles(projectId);
		} catch {
			// silently fail — files are optional context
		}
	}

	async function loadAddons(): Promise<void> {
		if (availableAddons.length === 0) addonLoading = true;
		try {
			const response = await getUserAddons();
			availableAddons = response.items.filter((a) => a.auth_complete);
			setSessionCache('midsphere-home-addons', availableAddons);
			markSessionFetched('midsphere-home-addons');
		} catch {
			/* optional */
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
			/* optional */
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
			/* optional */
		} finally {
			skillLoading = false;
		}
	}

	function timeAgo(dateStr: string): string {
		const diff = Date.now() - new Date(dateStr).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h ago`;
		const days = Math.floor(hrs / 24);
		return `${days}d ago`;
	}

	onMount(() => {
		pageTitle.set('Project');
		showHeaderTitle.set(true);
		if (projectId) {
			setActiveProject(projectId);
			loadProject();
			loadFiles();
		}
		if (!isSessionFresh('midsphere-home-addons', 120_000)) loadAddons();
		if (!isSessionFresh('midsphere-home-mcps', 120_000)) loadMCPs();
		if (!isSessionFresh('midsphere-home-skills', 120_000)) loadSkills();
		ensureSubscription();
		initVoice();
		textareaEl?.focus();
	});

	// Re-load when navigating between projects (same component reused by SvelteKit)
	let prevProjectId = projectId;
	$effect(() => {
		if (projectId && projectId !== prevProjectId) {
			prevProjectId = projectId;
			project = null;
			projectFiles = [];
			setActiveProject(projectId);
			loadProject();
			loadFiles();
		}
	});

	onDestroy(() => {
		setActiveProject(null);
		if (recognition) {
			recognition.abort();
			recognition = null;
		}
	});

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

	// --- File handling ---

	function autoResize(el: HTMLTextAreaElement): void {
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 200) + 'px';
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

	async function submitPrompt(): Promise<void> {
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
			noteSubmissionStart();
			setPendingPrompt(text);

			const session = await acquireSession({
				projectId,
				promptPreview: text
			});

			const metadata: Record<string, unknown> = {
				is_new_conversation: true,
				project_id: projectId
			};
			if (fileIds.length > 0) metadata.files = fileIds;
			if (addonIds.length > 0) metadata.addons = addonIds;
			if (mcpIds.length > 0) metadata.mcp_configs = mcpIds;
			if (skillIds.length > 0) metadata.skill_ids = skillIds;

			await startRun(session.conversationId, {
				task: text,
				conversationId: session.conversationId,
				metadata
			});

			fetchConversations();
			goto(resolve(`/chat/${session.conversationId}`));
		} catch {
			toasts.error('Failed to start conversation. Please try again.');
		} finally {
			loading = false;
		}
	}

	function handleExampleSelect(example: string): void {
		prompt = example;
		if (textareaEl) {
			autoResize(textareaEl);
			textareaEl.focus();
		}
	}

	const mobileExamples = [
		'Build a SaaS dashboard',
		'Design a signup flow',
		'Create a portfolio site'
	];

	let hasFiles = $derived(attachedFiles.length > 0);
	let canSubmit = $derived((prompt.trim().length > 0 || hasFiles) && !loading);
	let showMobileExamples = $derived(!prompt.trim() && !loading);
</script>

<svelte:head>
	<title>{project?.title ?? 'Project'} - Jatayu AI</title>
</svelte:head>

<svelte:window onkeydown={handleSettingsKeydown} />

<!-- Outer flex row: main content + right settings sidebar (behaves like the left sidebar) -->
<div class="flex h-full min-h-0 overflow-hidden">
	<!-- Drop zone covers entire page -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="relative flex h-full min-w-0 flex-1 flex-col overflow-hidden"
		ondragenter={handleDragEnter}
		ondragleave={handleDragLeave}
		ondragover={handleDragOver}
		ondrop={handleDrop}
	>
		<!-- Drag overlay -->
		{#if dragOver}
			<div
				class="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-background"
			>
				<div
					class="flex flex-col items-center gap-3 rounded-2xl border border-border bg-background px-12 py-10 shadow-lg"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="48"
						height="48"
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
					<p class="text-lg font-medium text-foreground">Drop files here</p>
					<p class="text-sm text-subtle">Files up to 50MB</p>
				</div>
			</div>
		{/if}

		<!-- Top-right quick links — desktop only -->
		<div
			class="pointer-events-none absolute inset-x-0 top-0 z-10 hidden justify-end px-5 py-3 lg:flex"
		>
			<div class="pointer-events-auto flex items-center gap-1">
				<a
					href="https://discord.gg/midsphere"
					target="_blank"
					rel="noopener noreferrer"
					class="flex h-8 w-8 items-center justify-center rounded-lg text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
					aria-label="Join Discord"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
						<path
							d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"
						/>
					</svg>
				</a>
				<a
					href="https://midsphere.ai"
					target="_blank"
					rel="noopener noreferrer"
					class="flex h-8 w-8 items-center justify-center rounded-lg text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
					aria-label="Documentation"
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
						<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
					</svg>
				</a>
				<div class="ml-2 rounded-lg border border-border-subtle bg-surface/70 px-1 py-0.5">
					<CreditBadge />
				</div>
				<!-- Project settings toggle -->
				<button
					onclick={() => (settingsDrawerOpen = !settingsDrawerOpen)}
					disabled={!project}
					class="ml-1 flex h-8 w-8 items-center justify-center rounded-lg transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-40 {settingsDrawerOpen
						? 'bg-surface-2 text-foreground'
						: 'text-subtle'}"
					aria-label="Project settings"
					aria-pressed={settingsDrawerOpen}
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
							d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"
						/>
						<circle cx="12" cy="12" r="3" />
					</svg>
				</button>
			</div>
		</div>

		<!-- Scrollable inner content (independent from the right settings sidebar) -->
		<div
			class="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[220px] lg:justify-start lg:pb-0 lg:pt-[18vh]"
		>
			{#if projectLoading}
				<div class="mb-5 hidden lg:block">
					<Skeleton variant="text" width="180px" height="32px" />
				</div>
				<div class="mb-6 lg:mb-10">
					<Skeleton variant="text" width="320px" height="40px" />
				</div>
				<div class="hidden w-full max-w-3xl lg:block">
					<Skeleton variant="text" width="100%" height="120px" />
				</div>
			{:else if project}
				<!-- Project switcher — desktop only -->
				<div class="mb-5 hidden lg:block">
					<HomeProjectSwitcher />
				</div>

				<!-- Heading — matches home h1 scale -->
				<h1
					class="mb-2 text-center text-xl font-normal tracking-tight lg:text-4xl"
					style="color: var(--ms-heading)"
				>
					<span class="mr-2 align-middle" aria-hidden="true">{project.icon || '📁'}</span
					>{project.title}
				</h1>

				<!-- Context chips -->
				<div class="mb-6 flex flex-col items-center gap-3 lg:mb-10">
					<div class="hidden items-center justify-center gap-2 lg:flex">
						{#if projectFiles.length > 0}
							<span
								class="inline-flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-[11.5px] text-muted"
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
									><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
										d="M14 2v4a2 2 0 0 0 2 2h4"
									/></svg
								>
								{projectFiles.length} file{projectFiles.length !== 1 ? 's' : ''}
							</span>
						{/if}
					</div>
				</div>

				<!-- Desktop: full input + extras — identical to home -->
				<div class="hidden w-full max-w-3xl lg:block">
					<div
						class="relative rounded-[26px] border border-border-subtle bg-surface-2 shadow-sm transition-all duration-200 focus-within:border-border-strong focus-within:shadow-md"
					>
						<!-- File previews above input -->
						{#if hasFiles}
							<div class="flex flex-wrap gap-2 px-4 pt-3">
								{#each attachedFiles as file (file.id)}
									<div
										class="group relative flex items-center gap-2 rounded-lg border border-border-subtle bg-surface-2/60 px-3 py-1.5 text-sm"
									>
										{#if file.previewUrl}
											<img
												src={file.previewUrl}
												alt={file.file.name}
												class="h-8 w-8 rounded-md object-cover"
											/>
										{:else}
											<span class="text-base">{getFileIcon(file.file)}</span>
										{/if}
										<div class="flex flex-col">
											<span class="max-w-[120px] truncate text-xs font-medium text-foreground">
												{file.file.name}
											</span>
											<span class="text-[10px] text-muted">
												{formatFileSize(file.file.size)}
											</span>
										</div>
										{#if file.uploading}
											<svg
												class="h-3.5 w-3.5 animate-spin text-muted"
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
										{/if}
										<button
											onclick={() => removeFile(file.id)}
											class="ml-1 flex h-4 w-4 items-center justify-center rounded-full bg-surface-2 text-subtle opacity-0 transition-opacity hover:bg-surface-2 hover:text-foreground group-hover:opacity-100"
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
							placeholder="How can I help you today?"
							rows="3.5"
							disabled={loading}
							class="w-full resize-none bg-transparent px-5 py-3.5 text-base text-foreground outline-none placeholder:text-subtle disabled:opacity-60"
						></textarea>

						<!-- Bottom toolbar -->
						<div class="flex items-center justify-between px-3 pb-2.5">
							<!-- Left: tools popover + voice -->
							<div class="flex items-center gap-0.5">
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
								{#if voiceSupported}
									<button
										onclick={toggleVoice}
										disabled={loading}
										class="flex h-8 w-8 items-center justify-center rounded-lg transition-colors disabled:opacity-50 {isRecording
											? 'animate-pulse bg-error/15 text-error'
											: 'text-muted hover:bg-active hover:text-foreground'}"
										aria-label={isRecording ? 'Stop recording' : 'Voice input'}
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
							</div>

							<!-- Right: Plan badge + submit button -->
							<div class="flex items-center gap-2">
								<span class="text-xs font-medium text-muted">{planName}</span>
								<button
									onclick={() => submitPrompt()}
									disabled={!canSubmit}
									class="flex h-8 w-8 items-center justify-center rounded-[10px] border border-border-subtle bg-surface-2 text-muted transition-colors duration-200 hover:bg-active hover:text-foreground disabled:opacity-25"
									aria-label="Send message"
								>
									{#if loading}
										<LoadingSpinner />
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

					<ExamplePrompts onselect={handleExampleSelect} />

					<!-- Recent conversations -->
					{#if project.conversations.length > 0}
						<div class="mt-12 w-full">
							<div class="mb-3 flex items-center justify-between px-3">
								<h2 class="text-sm font-medium text-muted">Recent</h2>
								<a
									href={resolve(`/projects/${projectId}`)}
									class="text-xs text-muted transition-colors hover:text-foreground"
								>
									View all
								</a>
							</div>
							<div class="flex flex-col gap-0.5">
								{#each project.conversations.slice(0, 5) as conv (conv.id)}
									<a
										href={resolve(`/chat/${conv.id}`)}
										class="group flex items-center justify-between rounded-lg px-3 py-2 transition-colors hover:bg-surface-2"
									>
										<span
											class="min-w-0 truncate text-[15px] text-foreground group-hover:text-foreground"
										>
											{conv.title || 'Untitled'}
										</span>
										<span class="shrink-0 pl-4 text-xs text-muted">
											{timeAgo(conv.date_updated)}
										</span>
									</a>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			{:else if accessDenied}
				<div class="flex h-full flex-col items-center justify-center gap-4 p-8">
					<div class="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="28"
							height="28"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-muted"
						>
							<rect width="18" height="11" x="3" y="11" rx="2" ry="2" /><path
								d="M7 11V7a5 5 0 0 1 10 0v4"
							/>
						</svg>
					</div>
					<div class="text-center">
						<h1 class="text-lg font-normal text-foreground">Request Access</h1>
						<p class="mt-1 text-[14px] text-muted">You don't have access to this project</p>
					</div>
					<button
						onclick={() => toasts.info('Access request sent')}
						class="rounded-xl bg-foreground px-4 py-2.5 text-sm font-medium text-background transition-colors hover:bg-foreground/90"
					>
						Request Invite
					</button>
				</div>
			{:else}
				<div class="flex h-full flex-col items-center justify-center gap-4 p-8">
					<div class="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="28"
							height="28"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-muted"
						>
							<circle cx="12" cy="12" r="10" />
							<path d="M12 16v-4" />
							<path d="M12 8h.01" />
						</svg>
					</div>
					<div class="text-center">
						<h1 class="text-lg font-normal text-foreground">Project not found</h1>
						<p class="mt-1 text-[14px] text-muted">This project may have been deleted</p>
					</div>
				</div>
			{/if}
		</div>
	</div>

	{#if settingsDrawerOpen && project}
		<!-- Right settings sidebar — pushes content like the left sidebar -->
		<aside
			class="hidden shrink-0 flex-col border-l border-border-subtle bg-background lg:flex lg:w-[480px] xl:w-[540px]"
			aria-label="Project settings"
		>
			<div
				class="flex shrink-0 items-center justify-between border-b border-border-subtle px-5 py-3"
			>
				<h2 class="text-sm font-medium text-foreground">Project settings</h2>
				<button
					onclick={() => (settingsDrawerOpen = false)}
					class="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
					aria-label="Close settings"
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
						<path d="M18 6 6 18" />
						<path d="m6 6 12 12" />
					</svg>
				</button>
			</div>
			<div class="flex-1 overflow-y-auto px-5 py-6">
				<ProjectSettingsPanel
					{projectId}
					onProjectUpdated={handleProjectSettingsUpdated}
					onDeleted={handleProjectSettingsDeleted}
				/>
			</div>
		</aside>
	{/if}
</div>

<!-- Mobile bottom area: example prompts + composer — identical to home -->
{#if project}
	<div
		class="fixed inset-x-0 z-20 px-3 lg:hidden"
		style="bottom: calc(env(safe-area-inset-bottom, 0px) + 16px)"
	>
		{#if showMobileExamples}
			<div class="mb-1.5">
				{#each mobileExamples as example, i}
					{#if i > 0}
						<div class="mx-3 border-t border-border"></div>
					{/if}
					<button
						onclick={() => {
							prompt = example;
						}}
						class="w-full px-4 py-2.5 text-left text-[13px] text-muted transition-colors active:bg-surface-2"
					>
						{example}
					</button>
				{/each}
			</div>
		{/if}

		<div
			class="flex items-end gap-2 rounded-[20px] border border-border-subtle bg-surface p-1.5 shadow-lg"
		>
			<div class="shrink-0 pb-0.5">
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
			</div>

			<textarea
				bind:value={prompt}
				oninput={(e) => {
					const el = e.target as HTMLTextAreaElement;
					el.style.height = 'auto';
					el.style.height = Math.min(el.scrollHeight, 120) + 'px';
				}}
				onkeydown={(e) => {
					if (e.key === 'Enter' && !e.shiftKey) {
						e.preventDefault();
						submitPrompt();
					}
				}}
				onpaste={handlePaste}
				placeholder="Ask anything"
				rows="1"
				disabled={loading}
				class="min-w-0 flex-1 resize-none bg-transparent py-2 text-[15px] text-foreground outline-none placeholder:text-subtle"
				style="max-height: 120px;"
			></textarea>

			{#if prompt.trim() || loading}
				<button
					onclick={() => submitPrompt()}
					disabled={!canSubmit}
					class="flex h-9 shrink-0 items-center justify-center rounded-[10px] border border-border-subtle bg-surface-2 px-4 text-muted transition-colors hover:bg-active hover:text-foreground disabled:opacity-25"
					aria-label="Send"
				>
					{#if loading}
						<LoadingSpinner />
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
					class="flex h-9 shrink-0 items-center gap-1.5 rounded-[10px] px-3 text-muted transition-colors active:bg-active
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
						<line x1="4" y1="8" x2="4" y2="16" />
						<line x1="8" y1="5" x2="8" y2="19" />
						<line x1="12" y1="3" x2="12" y2="21" />
						<line x1="16" y1="5" x2="16" y2="19" />
						<line x1="20" y1="8" x2="20" y2="16" />
					</svg>
					<span class="text-xs font-medium">Voice</span>
				</button>
			{/if}
		</div>
	</div>
{/if}
