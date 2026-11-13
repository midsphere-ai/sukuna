<script lang="ts">
	import { onMount } from 'svelte';
	import { updateProjectLocal, removeProjectLocal } from '$stores/projects';
	import { toasts } from '$stores/toast';
	import { Input, Textarea, Skeleton, ConfirmationDialog } from '$components/ui';
	import {
		getProject,
		updateProject,
		deleteProject,
		uploadProjectFile,
		listProjectFiles,
		deleteProjectFile,
		getProjectToolkit,
		addProjectSkill,
		removeProjectSkill,
		addProjectMCPConfig,
		deleteProjectMCPConfig
	} from '$api/projects';
	import { searchSkills } from '$api/skills';
	import type {
		ProjectDetail,
		ProjectFile,
		ProjectToolkit,
		ProjectSkillEntry,
		ProjectMCPConfigEntry
	} from '$api/types';
	import type { SkillCatalog } from '$api/skills';
	import { getNotificationPreferences, updateNotificationPreferences } from '$api/notifications';
	import MoveProjectDialog from '$components/projects/MoveProjectDialog.svelte';
	import ShareProjectDialog from '$components/projects/ShareProjectDialog.svelte';
	import { enterpriseMode } from '$stores/enterprise';

	interface Props {
		projectId: string;
		onProjectUpdated?: (project: ProjectDetail) => void;
		onDeleted?: () => void;
	}

	let { projectId, onProjectUpdated, onDeleted }: Props = $props();

	let project: ProjectDetail | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);
	let deleteConfirmOpen = $state(false);
	let deleting = $state(false);
	let moveDialogOpen = $state(false);
	let shareDialogOpen = $state(false);

	// Editable fields
	let title = $state('');
	let description = $state('');
	let icon = $state('');
	let customInstructions = $state('');
	let showEmojiPicker = $state(false);

	// Files
	let files: ProjectFile[] = $state([]);
	let filesLoading = $state(false);
	let uploading = $state(false);
	let fileInput: HTMLInputElement | undefined = $state();

	// Toolkit
	let toolkit: ProjectToolkit | null = $state(null);
	let toolkitLoading = $state(false);
	let isolatedToolkit = $state(false);
	let showSkillPicker = $state(false);
	let skillSearchQuery = $state('');
	let skillResults: SkillCatalog[] = $state([]);
	let skillSearching = $state(false);
	let showMCPForm = $state(false);
	let mcpFormName = $state('');
	let mcpFormType = $state<'stdio' | 'sse' | 'streamable-http'>('stdio');
	let mcpFormCommand = $state('');
	let mcpFormUrl = $state('');
	let mcpFormDescription = $state('');
	let mcpSaving = $state(false);

	// Notification mute
	let projectMuted = $state(false);
	let muteLoading = $state(true);
	let muteToggling = $state(false);

	const EMOJI_OPTIONS = [
		'📁',
		'🚀',
		'💡',
		'🎨',
		'🔧',
		'📊',
		'🌐',
		'📝',
		'⚡',
		'🎯',
		'🔬',
		'🏗️',
		'📱',
		'🤖',
		'🎮',
		'📚',
		'🔥',
		'💻',
		'🛠️',
		'✨',
		'🧪',
		'🎵',
		'📸',
		'🌟',
		'🏠',
		'🔒',
		'📈',
		'🎬',
		'🧩',
		'💎',
		'🌿',
		'🎪'
	];

	let hasChanges = $derived.by(() => {
		const p = project;
		if (!p) return false;
		return (
			title !== p.title ||
			description !== p.description ||
			icon !== p.icon ||
			customInstructions !== p.custom_instructions
		);
	});

	async function loadProject(): Promise<void> {
		loading = true;
		try {
			const detail = await getProject(projectId);
			project = detail;
			title = detail.title;
			description = detail.description;
			icon = detail.icon;
			customInstructions = detail.custom_instructions;
		} catch {
			toasts.error('Failed to load project');
		} finally {
			loading = false;
		}
	}

	async function loadFiles(): Promise<void> {
		filesLoading = true;
		try {
			files = await listProjectFiles(projectId);
		} catch {
			// silently fail — files may not be available
		} finally {
			filesLoading = false;
		}
	}

	async function handleSave(): Promise<void> {
		if (!hasChanges || saving) return;

		saving = true;
		try {
			await updateProject(projectId, {
				title: title.trim(),
				description: description.trim(),
				icon: icon || '📁',
				custom_instructions: customInstructions.trim()
			});

			updateProjectLocal(projectId, {
				title: title.trim(),
				description: description.trim(),
				icon: icon || '📁',
				custom_instructions: customInstructions.trim()
			});

			if (project) {
				project = {
					...project,
					title: title.trim(),
					description: description.trim(),
					icon: icon || '📁',
					custom_instructions: customInstructions.trim()
				};
				onProjectUpdated?.(project);
			}

			toasts.success('Project updated');
		} catch {
			toasts.error('Failed to update project');
		} finally {
			saving = false;
		}
	}

	async function handleDelete(): Promise<void> {
		deleting = true;
		try {
			await deleteProject(projectId);
			removeProjectLocal(projectId);
			toasts.success('Project deleted');
			onDeleted?.();
		} catch {
			toasts.error('Failed to delete project');
		} finally {
			deleting = false;
			deleteConfirmOpen = false;
		}
	}

	async function handleFileUpload(e: Event): Promise<void> {
		const input = e.target as HTMLInputElement;
		const fileList = input.files;
		if (!fileList || fileList.length === 0) return;

		uploading = true;
		try {
			for (const file of fileList) {
				await uploadProjectFile(projectId, file);
			}
			toasts.success(`${fileList.length} file${fileList.length > 1 ? 's' : ''} uploaded`);
			await loadFiles();
		} catch {
			toasts.error('Failed to upload file');
		} finally {
			uploading = false;
			if (input) input.value = '';
		}
	}

	async function handleDeleteFile(fileId: string, filename: string): Promise<void> {
		try {
			await deleteProjectFile(projectId, fileId);
			files = files.filter((f) => f.id !== fileId);
			toasts.success(`Deleted ${filename}`);
		} catch {
			toasts.error('Failed to delete file');
		}
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function selectEmoji(emoji: string): void {
		icon = emoji;
		showEmojiPicker = false;
	}

	async function loadToolkit(): Promise<void> {
		toolkitLoading = true;
		try {
			toolkit = await getProjectToolkit(projectId);
			isolatedToolkit = toolkit.isolated_toolkit;
		} catch {
			// silently fail
		} finally {
			toolkitLoading = false;
		}
	}

	async function handleIsolatedToggle(checked: boolean): Promise<void> {
		isolatedToolkit = checked;
		try {
			await updateProject(projectId, { isolated_toolkit: checked });
		} catch {
			isolatedToolkit = !checked;
			toasts.error('Failed to update toolkit mode');
		}
	}

	async function handleSearchSkills(): Promise<void> {
		if (!skillSearchQuery.trim()) return;
		skillSearching = true;
		try {
			const resp = await searchSkills(skillSearchQuery.trim());
			const addedSlugs = new Set(toolkit?.skills.map((s) => s.skill.slug) ?? []);
			skillResults = resp.items.filter((s) => !addedSlugs.has(s.slug));
		} catch {
			toasts.error('Failed to search skills');
		} finally {
			skillSearching = false;
		}
	}

	async function handleAddSkill(skill: SkillCatalog): Promise<void> {
		try {
			await addProjectSkill(projectId, skill.id);
			showSkillPicker = false;
			skillSearchQuery = '';
			skillResults = [];
			await loadToolkit();
			toasts.success(`Added ${skill.name}`);
		} catch {
			toasts.error('Failed to add skill');
		}
	}

	async function handleRemoveSkill(entry: ProjectSkillEntry): Promise<void> {
		try {
			await removeProjectSkill(projectId, entry.id);
			await loadToolkit();
			toasts.success(`Removed ${entry.skill.name}`);
		} catch {
			toasts.error('Failed to remove skill');
		}
	}

	async function handleAddMCPConfig(): Promise<void> {
		if (!mcpFormName.trim()) return;
		mcpSaving = true;
		try {
			await addProjectMCPConfig(projectId, {
				server_name: mcpFormName.trim(),
				server_type: mcpFormType,
				command: mcpFormType === 'stdio' ? mcpFormCommand.trim() : undefined,
				url: mcpFormType !== 'stdio' ? mcpFormUrl.trim() : undefined,
				description: mcpFormDescription.trim()
			});
			showMCPForm = false;
			mcpFormName = '';
			mcpFormCommand = '';
			mcpFormUrl = '';
			mcpFormDescription = '';
			await loadToolkit();
			toasts.success('MCP server added');
		} catch {
			toasts.error('Failed to add MCP server');
		} finally {
			mcpSaving = false;
		}
	}

	async function handleDeleteMCPConfig(config: ProjectMCPConfigEntry): Promise<void> {
		try {
			await deleteProjectMCPConfig(projectId, config.id);
			await loadToolkit();
			toasts.success(`Removed ${config.server_name}`);
		} catch {
			toasts.error('Failed to remove MCP server');
		}
	}

	async function loadMuteState(): Promise<void> {
		muteLoading = true;
		try {
			const resp = await getNotificationPreferences();
			projectMuted = resp.preferences.some((p) => (p.muted_project_ids || []).includes(projectId));
		} catch {
			// Silently fail
		} finally {
			muteLoading = false;
		}
	}

	async function handleMuteToggle(checked: boolean): Promise<void> {
		muteToggling = true;
		const oldValue = projectMuted;
		projectMuted = checked;
		try {
			const resp = await getNotificationPreferences();
			const updates = resp.preferences.map((p) => {
				const mutedIds = [...(p.muted_project_ids || [])];
				if (checked && !mutedIds.includes(projectId)) {
					mutedIds.push(projectId);
				} else if (!checked) {
					const idx = mutedIds.indexOf(projectId);
					if (idx >= 0) mutedIds.splice(idx, 1);
				}
				return { notification_type: p.notification_type, muted_project_ids: mutedIds };
			});
			await updateNotificationPreferences(updates);
		} catch {
			projectMuted = oldValue;
			toasts.error('Failed to update mute setting.');
		} finally {
			muteToggling = false;
		}
	}

	onMount(() => {
		if (projectId) {
			loadProject();
			loadFiles();
			loadToolkit();
			loadMuteState();
		}
	});
</script>

{#if loading}
	<div class="flex items-center gap-4 pb-6">
		<Skeleton variant="rect" width="48px" height="48px" />
		<div class="flex-1 space-y-2">
			<Skeleton variant="text" width="40%" height="20px" />
			<Skeleton variant="text" width="60%" height="14px" />
		</div>
	</div>
	<div class="space-y-4">
		<Skeleton variant="text" width="100%" height="40px" />
		<Skeleton variant="text" width="100%" height="80px" />
		<Skeleton variant="text" width="100%" height="120px" />
	</div>
{:else if project}
	<!-- Icon picker -->
	<div class="relative mb-6">
		<button
			onclick={() => (showEmojiPicker = !showEmojiPicker)}
			class="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-border-subtle bg-surface-2 text-2xl transition-colors hover:bg-surface"
			aria-label="Change project icon"
		>
			{icon || '📁'}
		</button>
		{#if showEmojiPicker}
			<div
				class="absolute top-full left-0 z-10 mt-1 grid w-[200px] grid-cols-8 gap-0.5 rounded-xl border border-border-subtle bg-surface-2 p-2 shadow-xl"
			>
				{#each EMOJI_OPTIONS as emoji (emoji)}
					<button
						onclick={() => selectEmoji(emoji)}
						class="flex h-7 w-7 items-center justify-center rounded-md text-sm transition-colors hover:bg-surface-2 {icon ===
						emoji
							? 'bg-accent/10 ring-1 ring-accent/30'
							: ''}"
					>
						{emoji}
					</button>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Settings form -->
	<div class="space-y-6">
		<Input label="Title" bind:value={title} placeholder="Project name" required />

		<Textarea
			label="Custom Prompt Extension"
			bind:value={description}
			placeholder="Add custom instructions for the AI agent when working in this project..."
			rows={2}
		/>

		<Textarea
			label="Custom Instructions"
			bind:value={customInstructions}
			placeholder="Add custom instructions for the AI agent when working in this project..."
			rows={4}
		/>
	</div>

	<!-- Divider -->
	<div class="my-8 border-t border-border-subtle"></div>

	<!-- File uploads -->
	<div>
		<div class="mb-4 flex items-center justify-between">
			<div>
				<h2 class="text-sm font-medium text-foreground">Preloaded Files</h2>
				<p class="mt-0.5 text-xs text-muted">
					Files uploaded here will be available in the project sandbox
				</p>
			</div>
			<button
				onclick={() => fileInput?.click()}
				disabled={uploading}
				class="rounded-lg border border-border-strong px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
			>
				{uploading ? 'Uploading...' : 'Upload Files'}
			</button>
			<input
				bind:this={fileInput}
				type="file"
				multiple
				onchange={handleFileUpload}
				class="hidden"
			/>
		</div>

		<div class="rounded-xl border-2 border-dashed border-border bg-surface transition-colors">
			{#if filesLoading}
				<div class="space-y-2 p-4">
					{#each [0, 1] as i (i)}
						<div class="flex items-center gap-3 rounded-lg p-2">
							<Skeleton variant="rect" width="32px" height="32px" />
							<div class="flex-1 space-y-1">
								<Skeleton variant="text" width="50%" height="12px" />
								<Skeleton variant="text" width="30%" height="10px" />
							</div>
						</div>
					{/each}
				</div>
			{:else if files.length === 0}
				<button
					onclick={() => fileInput?.click()}
					class="flex w-full flex-col items-center gap-2 p-8 text-center"
					disabled={uploading}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="24"
						height="24"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="text-muted"
					>
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
						<polyline points="17 8 12 3 7 8" />
						<line x1="12" x2="12" y1="3" y2="15" />
					</svg>
					<p class="text-xs text-muted">Click to upload or drag files here</p>
				</button>
			{:else}
				<div class="divide-y divide-border-subtle p-2">
					{#each files as file (file.id)}
						<div
							class="flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-surface-2"
						>
							<div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface">
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
									<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
									<path d="M14 2v4a2 2 0 0 0 2 2h4" />
								</svg>
							</div>
							<div class="min-w-0 flex-1">
								<p class="truncate text-xs font-medium text-foreground">{file.filename}</p>
								<p class="text-[10px] text-muted">{formatFileSize(file.size_bytes)}</p>
							</div>
							<button
								onclick={() => handleDeleteFile(file.id, file.filename)}
								class="rounded-md p-1 text-muted transition-colors hover:bg-surface hover:text-red-500"
								aria-label="Delete {file.filename}"
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
									<path d="M18 6L6 18" />
									<path d="M6 6l12 12" />
								</svg>
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<!-- Divider -->
	<div class="my-8 border-t border-border-subtle"></div>

	<!-- Toolkit -->
	<div>
		<div class="mb-4 flex items-center justify-between">
			<div>
				<h2 class="text-sm font-medium text-foreground">Toolkit</h2>
				<p class="mt-0.5 text-xs text-muted">
					Skills and MCP servers available in every conversation in this project
				</p>
			</div>
		</div>

		<div class="mb-4 rounded-xl border border-border p-4">
			<label for="isolated-toolkit" class="flex cursor-pointer items-center justify-between gap-4">
				<div>
					<p class="text-sm font-medium text-foreground">Isolated mode</p>
					<p class="text-xs text-subtle">
						Only use project-level toolkit; ignore user's global installations
					</p>
				</div>
				<div class="relative shrink-0">
					<input
						id="isolated-toolkit"
						type="checkbox"
						role="switch"
						checked={isolatedToolkit}
						disabled={toolkitLoading}
						onchange={(e: Event) => handleIsolatedToggle((e.target as HTMLInputElement).checked)}
						aria-checked={isolatedToolkit}
						class="peer sr-only"
					/>
					<div
						class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
					></div>
					<div
						class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
					></div>
				</div>
			</label>
		</div>

		<div class="mb-4">
			<div class="mb-2 flex items-center justify-between">
				<p class="text-xs font-medium text-subtle">Skills</p>
				<button
					onclick={() => (showSkillPicker = !showSkillPicker)}
					class="rounded-lg border border-border-strong px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
				>
					{showSkillPicker ? 'Cancel' : '+ Add Skill'}
				</button>
			</div>

			{#if showSkillPicker}
				<div class="mb-3 rounded-xl border border-border-subtle bg-surface p-3">
					<div class="flex gap-2">
						<input
							type="text"
							bind:value={skillSearchQuery}
							placeholder="Search skills..."
							onkeydown={(e: KeyboardEvent) => e.key === 'Enter' && handleSearchSkills()}
							class="flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
						/>
						<button
							onclick={handleSearchSkills}
							disabled={skillSearching || !skillSearchQuery.trim()}
							class="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
						>
							{skillSearching ? '...' : 'Search'}
						</button>
					</div>
					{#if skillResults.length > 0}
						<div class="mt-2 max-h-48 space-y-1 overflow-y-auto">
							{#each skillResults as skill (skill.slug)}
								<button
									onclick={() => handleAddSkill(skill)}
									class="flex w-full items-center gap-2 rounded-lg p-2 text-left transition-colors hover:bg-surface-2"
								>
									<span class="text-sm">{skill.icon || '🔧'}</span>
									<div class="min-w-0 flex-1">
										<p class="truncate text-xs font-medium text-foreground">{skill.name}</p>
										<p class="truncate text-[10px] text-muted">{skill.description}</p>
									</div>
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<div class="rounded-xl border border-border-subtle bg-surface">
				{#if toolkitLoading}
					<div class="p-4">
						<Skeleton variant="text" width="60%" height="12px" />
					</div>
				{:else if !toolkit?.skills.length}
					<p class="p-4 text-center text-xs text-muted">No skills added</p>
				{:else}
					<div class="divide-y divide-border-subtle p-2">
						{#each toolkit.skills as entry (entry.id)}
							<div
								class="flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-surface-2"
							>
								<span class="text-sm">{entry.skill.icon || '🔧'}</span>
								<div class="min-w-0 flex-1">
									<p class="truncate text-xs font-medium text-foreground">{entry.skill.name}</p>
									<p class="truncate text-[10px] text-muted">{entry.skill.category}</p>
								</div>
								<button
									onclick={() => handleRemoveSkill(entry)}
									class="rounded-md p-1 text-muted transition-colors hover:bg-surface hover:text-red-500"
									aria-label="Remove {entry.skill.name}"
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
										stroke-linejoin="round"><path d="M18 6L6 18" /><path d="M6 6l12 12" /></svg
									>
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<div>
			<div class="mb-2 flex items-center justify-between">
				<p class="text-xs font-medium text-subtle">MCP Servers</p>
				<button
					onclick={() => (showMCPForm = !showMCPForm)}
					class="rounded-lg border border-border-strong px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
				>
					{showMCPForm ? 'Cancel' : '+ Add MCP Server'}
				</button>
			</div>

			{#if showMCPForm}
				<div class="mb-3 space-y-3 rounded-xl border border-border-subtle bg-surface p-3">
					<div class="grid grid-cols-2 gap-2">
						<input
							type="text"
							bind:value={mcpFormName}
							placeholder="Server name"
							class="rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
						/>
						<select
							bind:value={mcpFormType}
							class="rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground focus:border-accent focus:outline-none"
						>
							<option value="stdio">Stdio</option>
							<option value="sse">SSE</option>
							<option value="streamable-http">Streamable HTTP</option>
						</select>
					</div>
					{#if mcpFormType === 'stdio'}
						<input
							type="text"
							bind:value={mcpFormCommand}
							placeholder="Command (e.g., npx -y @modelcontextprotocol/server-github)"
							class="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
						/>
					{:else}
						<input
							type="text"
							bind:value={mcpFormUrl}
							placeholder="URL (e.g., https://mcp.example.com/sse)"
							class="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
						/>
					{/if}
					<input
						type="text"
						bind:value={mcpFormDescription}
						placeholder="Description (optional)"
						class="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:border-accent focus:outline-none"
					/>
					<button
						onclick={handleAddMCPConfig}
						disabled={mcpSaving || !mcpFormName.trim()}
						class="rounded-lg bg-accent px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
					>
						{mcpSaving ? 'Adding...' : 'Add Server'}
					</button>
				</div>
			{/if}

			<div class="rounded-xl border border-border-subtle bg-surface">
				{#if toolkitLoading}
					<div class="p-4">
						<Skeleton variant="text" width="60%" height="12px" />
					</div>
				{:else if !toolkit?.mcp_configs.length}
					<p class="p-4 text-center text-xs text-muted">No MCP servers added</p>
				{:else}
					<div class="divide-y divide-border-subtle p-2">
						{#each toolkit.mcp_configs as config (config.id)}
							<div
								class="flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-surface-2"
							>
								<div
									class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface text-[10px] font-medium text-muted uppercase"
								>
									{config.server_type === 'stdio'
										? 'IO'
										: config.server_type === 'sse'
											? 'SE'
											: 'HT'}
								</div>
								<div class="min-w-0 flex-1">
									<p class="truncate text-xs font-medium text-foreground">{config.server_name}</p>
									<p class="truncate text-[10px] text-muted">
										{config.server_type}{config.description ? ` — ${config.description}` : ''}
									</p>
								</div>
								<button
									onclick={() => handleDeleteMCPConfig(config)}
									class="rounded-md p-1 text-muted transition-colors hover:bg-surface hover:text-red-500"
									aria-label="Remove {config.server_name}"
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
										stroke-linejoin="round"><path d="M18 6L6 18" /><path d="M6 6l12 12" /></svg
									>
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- Divider -->
	<div class="my-8 border-t border-border-subtle"></div>

	<!-- Notification mute -->
	<div>
		<h2 class="mb-2 text-sm font-medium text-foreground">Notifications</h2>
		<div class="rounded-xl border border-border p-4">
			<label for="project-mute" class="flex cursor-pointer items-center justify-between gap-4">
				<div>
					<p class="text-sm font-medium text-foreground">Mute notifications</p>
					<p class="text-xs text-subtle">Silence all notifications from this project.</p>
				</div>
				<div class="relative shrink-0">
					<input
						id="project-mute"
						type="checkbox"
						role="switch"
						checked={projectMuted}
						disabled={muteLoading || muteToggling}
						onchange={(e: Event) => handleMuteToggle((e.target as HTMLInputElement).checked)}
						aria-checked={projectMuted}
						class="peer sr-only"
					/>
					<div
						class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
					></div>
					<div
						class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
					></div>
				</div>
			</label>
		</div>
	</div>

	<!-- Divider -->
	<div class="my-8 border-t border-border-subtle"></div>

	<!-- Share project (enterprise only) -->
	{#if $enterpriseMode}
		<div>
			<h2 class="mb-2 text-sm font-medium text-foreground">Sharing</h2>
			<div class="rounded-xl border border-border p-4">
				<div class="flex items-center justify-between gap-4">
					<div>
						<p class="text-sm font-medium text-foreground">Share project</p>
						<p class="text-xs text-subtle">
							Share this project with team members or organizations.
						</p>
					</div>
					<button
						onclick={() => (shareDialogOpen = true)}
						class="shrink-0 rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
					>
						Share
					</button>
				</div>
			</div>
		</div>

		<div class="my-8 border-t border-border-subtle"></div>
	{/if}

	<!-- Move to organization -->
	<div>
		<h2 class="mb-2 text-sm font-medium text-foreground">Organization</h2>
		<div class="rounded-xl border border-border p-4">
			<div class="flex items-center justify-between gap-4">
				<div>
					<p class="text-sm font-medium text-foreground">Move to organization</p>
					<p class="text-xs text-subtle">
						Transfer this project to an organization so team members can access it.
					</p>
				</div>
				<button
					onclick={() => (moveDialogOpen = true)}
					class="shrink-0 rounded-lg border border-border-strong px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
				>
					Move
				</button>
			</div>
		</div>
	</div>

	<div class="my-8 border-t border-border-subtle"></div>

	<!-- Danger zone -->
	<div>
		<h2 class="mb-2 text-sm font-medium text-red-600">Danger Zone</h2>
		<div
			class="rounded-xl border border-red-200 bg-red-50/50 p-4 dark:border-red-500/20 dark:bg-red-500/5"
		>
			<div class="flex items-center justify-between gap-4">
				<div>
					<p class="text-sm font-medium text-foreground">Delete this project</p>
					<p class="text-xs text-subtle">
						This will permanently delete the project and all associated data.
					</p>
				</div>
				<button
					onclick={() => (deleteConfirmOpen = true)}
					class="shrink-0 rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600"
				>
					Delete
				</button>
			</div>
		</div>
	</div>

	{#if hasChanges}
		<!-- Sticky save bar — pinned to the bottom of the scroll container -->
		<div
			class="sticky bottom-0 z-10 mt-8 flex items-center justify-between gap-3 border-t border-border-subtle bg-background/95 py-3 backdrop-blur"
		>
			<span class="text-xs text-muted">You have unsaved changes</span>
			<button
				onclick={handleSave}
				disabled={saving}
				class="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
			>
				{saving ? 'Saving...' : 'Save Changes'}
			</button>
		</div>
	{/if}

	<ConfirmationDialog
		open={deleteConfirmOpen}
		title="Delete Project"
		message="Are you sure you want to delete &quot;{project.title}&quot;? This action cannot be undone."
		confirmLabel={deleting ? 'Deleting...' : 'Delete'}
		destructive
		onconfirm={handleDelete}
		oncancel={() => (deleteConfirmOpen = false)}
	/>

	<MoveProjectDialog
		bind:open={moveDialogOpen}
		{projectId}
		projectTitle={project.title}
		currentOrgId={null}
		onclose={() => (moveDialogOpen = false)}
		onmoved={() => loadProject()}
	/>

	{#if $enterpriseMode}
		<ShareProjectDialog
			bind:open={shareDialogOpen}
			{projectId}
			projectTitle={project.title}
			onclose={() => (shareDialogOpen = false)}
		/>
	{/if}
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
			<p class="mt-1 text-[13px] text-muted">This project may have been deleted</p>
		</div>
	</div>
{/if}
