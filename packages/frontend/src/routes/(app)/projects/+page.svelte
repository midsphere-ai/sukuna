<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { fade, fly } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { cubicOut } from 'svelte/easing';
	import { Skeleton, EmptyState } from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { projects, projectsLoading, ensureProjects, removeProjectLocal } from '$stores/projects';
	import { deleteProject } from '$api/projects';
	import { createTemplateFromProject } from '$api/organizations';
	import { activeOrg } from '$stores/activeOrg';
	import { formatRelativeTime } from '$stores/conversations';
	import { toasts } from '$stores/toast';
	import { ConfirmationDialog } from '$components/ui';
	import type { ProjectListItem } from '$api/types';
	import { get } from 'svelte/store';

	let projectList: ProjectListItem[] = $state([]);
	// Only show loading skeleton when store is empty (no cached projects)
	let loading = $state(false);

	// Filter
	let showSharedOnly = $state(false);
	let filteredProjects = $derived(
		showSharedOnly ? projectList.filter((p) => p.is_shared) : projectList
	);
	let sharedCount = $derived(projectList.filter((p) => p.is_shared).length);

	// Delete confirmation
	let deleteConfirmId: string | null = $state(null);
	let deleteConfirmTitle = $state('');

	// Dropdown
	let activeDropdownId: string | null = $state(null);

	// Template creation
	let creatingTemplateFromId: string | null = $state(null);

	projects.subscribe((v) => {
		projectList = v;
		// When we have data, never show the loading skeleton
		if (v.length > 0) loading = false;
	});
	projectsLoading.subscribe((v) => {
		// Only show loading when the list is still empty
		if (projectList.length === 0) loading = v;
	});

	onMount(() => {
		pageTitle.set('Projects');
		showHeaderTitle.set(true);
		ensureProjects();
	});

	function handleProjectClick(project: ProjectListItem): void {
		goto(resolve(`/projects/${project.id}/chat`));
	}

	function toggleDropdown(projectId: string, e: MouseEvent): void {
		e.stopPropagation();
		activeDropdownId = activeDropdownId === projectId ? null : projectId;
	}

	function closeDropdowns(): void {
		activeDropdownId = null;
	}

	function handleSettings(project: ProjectListItem): void {
		activeDropdownId = null;
		goto(resolve(`/projects/${project.id}`));
	}

	function handleDeleteClick(project: ProjectListItem): void {
		activeDropdownId = null;
		deleteConfirmId = project.id;
		deleteConfirmTitle = project.title;
	}

	async function confirmDelete(): Promise<void> {
		if (!deleteConfirmId) return;
		const id = deleteConfirmId;
		try {
			await deleteProject(id);
			removeProjectLocal(id);
			toasts.success('Project deleted');
		} catch {
			toasts.error('Failed to delete project');
		} finally {
			deleteConfirmId = null;
		}
	}

	async function handleCreateTemplate(project: ProjectListItem): Promise<void> {
		activeDropdownId = null;
		const org = get(activeOrg);
		if (!org?.organization_id) {
			toasts.error('No active organization');
			return;
		}
		creatingTemplateFromId = project.id;
		try {
			await createTemplateFromProject(org.organization_id, project.id);
			toasts.success(`Template created from "${project.title}"`);
		} catch {
			toasts.error('Failed to create template');
		} finally {
			creatingTemplateFromId = null;
		}
	}
</script>

<svelte:window onclick={closeDropdowns} />

<div class="mx-auto flex w-full max-w-6xl flex-col px-4 pt-16 pb-6 sm:px-6 lg:px-8" role="main">
	<!-- Header + Toolbar -->
	<div class="mb-6 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<svg
				class="text-foreground"
				xmlns="http://www.w3.org/2000/svg"
				width="24"
				height="24"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path
					d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"
				/>
			</svg>
			<h1 class="text-2xl font-normal tracking-tight text-foreground">Projects</h1>
			{#if sharedCount > 0}
				<button
					onclick={() => (showSharedOnly = !showSharedOnly)}
					class="inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition-colors {showSharedOnly
						? 'bg-accent/10 text-accent'
						: 'text-muted hover:bg-surface-2 hover:text-foreground'}"
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
						><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle
							cx="9"
							cy="7"
							r="4"
						/><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg
					>
					Shared with you ({sharedCount})
				</button>
			{/if}
		</div>
		<button
			onclick={() => goto(resolve('/projects/new'))}
			class="inline-flex h-9 items-center gap-2 rounded-xl border border-border px-3.5 text-sm font-medium text-foreground transition-colors hover:border-border-strong"
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
				<path d="M12 5v14" /><path d="M5 12h14" />
			</svg>
			New project
		</button>
	</div>

	<!-- Loading -->
	{#if loading && projectList.length === 0}
		<div class="flex flex-col" out:fade={{ duration: 80 }}>
			{#each [0, 1, 2, 3] as i (i)}
				<div class="flex items-center gap-4 rounded-lg px-3 py-3.5">
					<Skeleton class="shrink-0 rounded-lg" width="36px" height="36px" stagger={i} />
					<div class="min-w-0 flex-1">
						<Skeleton class="rounded" width="40%" height="14px" stagger={i} />
						<div class="mt-1 flex items-center gap-2">
							<Skeleton class="rounded" width="48px" height="11px" stagger={i + 1} />
							<Skeleton class="rounded" width="6px" height="6px" stagger={i + 1} />
							<Skeleton class="rounded" width="64px" height="11px" stagger={i + 2} />
						</div>
					</div>
				</div>
			{/each}
		</div>

		<!-- Empty state -->
	{:else if projectList.length === 0}
		<EmptyState
			icon="📁"
			title="No projects yet"
			description="Projects help you organize conversations and files around a specific goal."
		>
			<button
				onclick={() => goto(resolve('/projects/new'))}
				class="mt-4 inline-flex items-center gap-2 rounded-xl bg-foreground px-4 py-2.5 text-sm font-medium text-background transition-colors hover:bg-foreground/90"
			>
				Create your first project
			</button>
		</EmptyState>

		<!-- Project list -->
	{:else}
		<div class="flex flex-col" in:fade={{ duration: 150, delay: 50 }}>
			{#each filteredProjects as project, i (project.id)}
				<div
					role="button"
					tabindex="0"
					onclick={() => handleProjectClick(project)}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') {
							e.preventDefault();
							handleProjectClick(project);
						}
					}}
					class="card-hover group flex -mx-2 cursor-pointer items-center gap-4 rounded-lg px-3 py-3.5"
					in:fly={{ y: 8, duration: 150, delay: i * 30, easing: cubicOut }}
					out:fly={{ x: -20, duration: 150 }}
					animate:flip={{ duration: 150, easing: cubicOut }}
				>
					<span
						class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-base"
					>
						{project.icon || '📁'}
					</span>

					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<h3 class="truncate text-sm font-medium text-foreground">{project.title}</h3>
							{#if project.is_shared}
								<span
									class="inline-flex shrink-0 items-center gap-1 rounded-md bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent"
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										width="10"
										height="10"
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2.5"
										stroke-linecap="round"
										stroke-linejoin="round"
										><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle
											cx="9"
											cy="7"
											r="4"
										/><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path
											d="M16 3.13a4 4 0 0 1 0 7.75"
										/></svg
									>
									Shared
								</span>
							{/if}
						</div>
						<div class="mt-0.5 flex items-center gap-2 text-xs text-muted">
							<span
								>{project.conversation_count}
								{project.conversation_count === 1 ? 'chat' : 'chats'}</span
							>
							<span class="text-muted">·</span>
							<span>{formatRelativeTime(project.date_updated)}</span>
							{#if project.description}
								<span class="text-muted">·</span>
								<span class="truncate">{project.description}</span>
							{/if}
						</div>
					</div>

					<!-- Dropdown trigger -->
					<div class="relative shrink-0">
						<button
							onclick={(e) => toggleDropdown(project.id, e)}
							class="flex h-7 w-7 items-center justify-center rounded-lg text-muted opacity-0 transition-all hover:bg-surface-2 hover:text-foreground group-hover:opacity-100"
							aria-label="Project options"
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
								<circle cx="12" cy="12" r="1" /><circle cx="12" cy="5" r="1" /><circle
									cx="12"
									cy="19"
									r="1"
								/>
							</svg>
						</button>
						{#if activeDropdownId === project.id}
							<div
								class="absolute right-0 z-50 mt-1 w-36 animate-[fadeInUp_100ms_ease-out] rounded-xl border border-border-subtle bg-surface-2 p-1 shadow-sm"
							>
								<button
									onclick={(e) => {
										e.stopPropagation();
										handleSettings(project);
									}}
									class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-surface-2"
								>
									Settings
								</button>
								{#if get(activeOrg)?.organization_id}
									<button
										onclick={(e) => {
											e.stopPropagation();
											handleCreateTemplate(project);
										}}
										disabled={creatingTemplateFromId === project.id}
										class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-surface-2 disabled:opacity-50"
									>
										{creatingTemplateFromId === project.id ? 'Saving...' : 'Save as Template'}
									</button>
								{/if}
								<button
									onclick={(e) => {
										e.stopPropagation();
										handleDeleteClick(project);
									}}
									class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-red-600 transition-colors hover:bg-red-50"
								>
									Delete
								</button>
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<ConfirmationDialog
	open={!!deleteConfirmId}
	title="Delete project"
	message="Are you sure you want to delete &quot;{deleteConfirmTitle}&quot;? This cannot be undone."
	confirmLabel="Delete"
	destructive
	onconfirm={confirmDelete}
	oncancel={() => (deleteConfirmId = null)}
/>
