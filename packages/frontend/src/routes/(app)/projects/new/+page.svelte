<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { createProject, uploadProjectFile } from '$api/projects';
	import { addProjectLocal, fetchProjects } from '$stores/projects';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import type { ProjectListItem } from '$api/types';

	let title = $state('');
	let description = $state('');
	let icon = $state('');
	let saving = $state(false);
	let showEmojiPicker = $state(false);
	let titleEl: HTMLInputElement | undefined = $state();
	let fileInputEl: HTMLInputElement | undefined = $state();
	let dragOver = $state(false);

	// Pending files to upload after project creation
	type PendingFile = { id: string; file: File };
	let pendingFiles: PendingFile[] = $state([]);

	const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
	const ALLOWED_TYPES = [
		'text/plain',
		'text/csv',
		'text/markdown',
		'application/pdf',
		'application/json',
		'image/jpeg',
		'image/png',
		'image/webp',
		'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
		'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
	];

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

	function selectEmoji(emoji: string): void {
		icon = emoji;
		showEmojiPicker = false;
	}

	function addFiles(fileList: FileList | null): void {
		if (!fileList) return;
		for (const file of fileList) {
			if (file.size > MAX_FILE_SIZE) {
				toasts.error(`${file.name} exceeds 10MB limit`);
				continue;
			}
			if (ALLOWED_TYPES.length > 0 && !ALLOWED_TYPES.includes(file.type) && file.type !== '') {
				toasts.error(`${file.name}: unsupported file type`);
				continue;
			}
			// Avoid duplicates by name
			if (pendingFiles.some((p) => p.file.name === file.name)) continue;
			pendingFiles = [...pendingFiles, { id: crypto.randomUUID(), file }];
		}
	}

	function removeFile(id: string): void {
		pendingFiles = pendingFiles.filter((f) => f.id !== id);
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function handleDrop(e: DragEvent): void {
		e.preventDefault();
		dragOver = false;
		addFiles(e.dataTransfer?.files ?? null);
	}

	async function handleSubmit(): Promise<void> {
		if (!title.trim() || saving) return;

		saving = true;
		try {
			const result = await createProject({
				title: title.trim(),
				description: description.trim(),
				icon: icon || '📁'
			});

			const projectId = result.project_id;

			// Upload pending files
			if (pendingFiles.length > 0) {
				const uploadResults = await Promise.allSettled(
					pendingFiles.map((pf) => uploadProjectFile(projectId, pf.file))
				);
				const failed = uploadResults.filter((r) => r.status === 'rejected').length;
				if (failed > 0) {
					toasts.warning(`${failed} file${failed > 1 ? 's' : ''} failed to upload`);
				}
			}

			const newProject: ProjectListItem = {
				id: projectId,
				title: title.trim(),
				description: description.trim(),
				icon: icon || '📁',
				custom_instructions: '',
				user: 0,
				sandbox: null,
				date_created: new Date().toISOString(),
				date_updated: new Date().toISOString(),
				conversation_count: 0
			};
			addProjectLocal(newProject);
			toasts.success('Project created');

			// eslint-disable-next-line svelte/no-navigation-without-resolve -- internal route
			goto(`/projects/${projectId}`);

			fetchProjects();
		} catch {
			toasts.error('Failed to create project');
		} finally {
			saving = false;
		}
	}

	function handleBack(): void {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto('/projects');
	}

	onMount(() => {
		pageTitle.set('New Project');
		showHeaderTitle.set(false);
		titleEl?.focus();
	});
</script>

<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (showEmojiPicker && !target.closest('[data-emoji-picker]')) {
			showEmojiPicker = false;
		}
	}}
/>

<svelte:head>
	<title>New Project - Jatayu AI</title>
</svelte:head>

<div class="mx-auto flex w-full max-w-xl flex-col px-4 pt-16 pb-6 sm:px-6">
	<!-- Back -->
	<button
		onclick={handleBack}
		class="mb-8 flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-foreground"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="15"
			height="15"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<path d="M19 12H5" /><polyline points="12 19 5 12 12 5" />
		</svg>
		Projects
	</button>

	<h1 class="text-2xl font-normal tracking-tight text-foreground">New Project</h1>
	<p class="mt-1 text-sm text-muted">Projects group conversations and files around a goal.</p>

	<form
		onsubmit={(e) => {
			e.preventDefault();
			handleSubmit();
		}}
		class="mt-8 flex flex-col gap-5"
	>
		<!-- Icon + Title -->
		<div class="flex items-start gap-3">
			<div class="relative" data-emoji-picker>
				<button
					type="button"
					onclick={() => (showEmojiPicker = !showEmojiPicker)}
					class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border text-lg transition-colors hover:border-border-strong"
					aria-label="Choose icon"
				>
					{icon || '📁'}
				</button>
				{#if showEmojiPicker}
					<div
						class="absolute top-full left-0 z-10 mt-1.5 grid w-[208px] grid-cols-8 gap-0.5 rounded-xl border border-border-subtle bg-surface-2 p-2 shadow-sm"
					>
						{#each EMOJI_OPTIONS as emoji (emoji)}
							<button
								type="button"
								onclick={() => selectEmoji(emoji)}
								class="flex h-6 w-6 items-center justify-center rounded-md text-sm transition-colors hover:bg-surface-2 {icon ===
								emoji
									? 'bg-surface-2'
									: ''}"
							>
								{emoji}
							</button>
						{/each}
					</div>
				{/if}
			</div>
			<div class="flex flex-1 flex-col gap-1">
				<label for="project-title" class="text-xs font-medium text-subtle">Title</label>
				<input
					bind:this={titleEl}
					id="project-title"
					bind:value={title}
					placeholder="My project"
					required
					class="h-9 w-full rounded-xl border border-border bg-transparent px-3.5 text-sm text-foreground outline-none transition-all placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				/>
			</div>
		</div>

		<!-- Description -->
		<div class="flex flex-col gap-1">
			<label for="project-desc" class="text-xs font-medium text-subtle"
				>Custom Prompt Extension</label
			>
			<textarea
				id="project-desc"
				bind:value={description}
				placeholder="Add custom instructions for the AI agent when working in this project..."
				rows="3"
				class="w-full resize-none rounded-xl border border-border bg-transparent px-3.5 py-2.5 text-sm text-foreground outline-none transition-all placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
			></textarea>
		</div>

		<!-- Files -->
		<div class="flex flex-col gap-1">
			<label class="text-xs font-medium text-subtle">Sandbox files</label>
			<p class="text-xs text-muted">
				These files will be preloaded into every sandbox for this project.
			</p>

			<!-- Drop zone -->
			<div
				role="button"
				tabindex="0"
				class="mt-1.5 flex min-h-[72px] cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed transition-colors {dragOver
					? 'border-border-strong bg-surface'
					: 'border-border-strong hover:border-border-strong'}"
				onclick={() => fileInputEl?.click()}
				onkeydown={(e) => {
					if (e.key === 'Enter' || e.key === ' ') {
						e.preventDefault();
						fileInputEl?.click();
					}
				}}
				ondragover={(e) => {
					e.preventDefault();
					dragOver = true;
				}}
				ondragleave={() => (dragOver = false)}
				ondrop={handleDrop}
			>
				<div class="flex items-center gap-2 text-xs text-muted">
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
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
						<polyline points="17 8 12 3 7 8" />
						<line x1="12" y1="3" x2="12" y2="15" />
					</svg>
					Drop files here or click to browse
				</div>
				<span class="mt-0.5 text-[10px] text-muted"
					>PDF, text, images, JSON, CSV — up to 10MB each</span
				>
			</div>
			<input
				bind:this={fileInputEl}
				type="file"
				multiple
				class="hidden"
				onchange={(e) => {
					const target = e.currentTarget as HTMLInputElement;
					addFiles(target.files);
					target.value = '';
				}}
			/>

			<!-- File list -->
			{#if pendingFiles.length > 0}
				<div class="mt-1 flex flex-col">
					{#each pendingFiles as pf (pf.id)}
						<div class="flex items-center gap-3 border-b border-border-subtle py-2 last:border-0">
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
								class="shrink-0 text-muted"
							>
								<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
								<polyline points="14 2 14 8 20 8" />
							</svg>
							<span class="min-w-0 flex-1 truncate text-sm text-foreground">{pf.file.name}</span>
							<span class="shrink-0 text-xs text-muted">{formatSize(pf.file.size)}</span>
							<button
								type="button"
								onclick={() => removeFile(pf.id)}
								class="shrink-0 rounded-md p-0.5 text-muted transition-colors hover:text-subtle"
								aria-label="Remove {pf.file.name}"
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
									<path d="M18 6L6 18" /><path d="M6 6l12 12" />
								</svg>
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Actions -->
		<div class="flex items-center gap-2.5 pt-2">
			<button
				type="submit"
				disabled={!title.trim() || saving}
				class="inline-flex h-9 items-center gap-2 rounded-xl bg-foreground px-4 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
			>
				{#if saving}
					Creating{pendingFiles.length > 0 ? ' & uploading...' : '...'}
				{:else}
					Create Project{pendingFiles.length > 0
						? ` with ${pendingFiles.length} file${pendingFiles.length > 1 ? 's' : ''}`
						: ''}
				{/if}
			</button>
			<button
				type="button"
				onclick={handleBack}
				class="inline-flex h-9 items-center rounded-xl border border-border px-3.5 text-sm font-medium text-foreground transition-colors hover:border-border-strong"
			>
				Cancel
			</button>
		</div>
	</form>
</div>
