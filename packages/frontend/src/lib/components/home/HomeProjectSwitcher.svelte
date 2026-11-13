<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { projects, activeProject, setActiveProject, fetchProjects } from '$stores/projects';
	import { currentUser } from '$stores/auth';
	import type { ProjectListItem } from '$api/types';
	import { onMount } from 'svelte';

	let open = $state(false);
	let projectList: ProjectListItem[] = $state([]);
	let selectedProject = $state<ProjectListItem | null>(null);
	let userName = $state('');

	const unsubProjects = projects.subscribe((v) => (projectList = v));
	const unsubActive = activeProject.subscribe((v) => (selectedProject = v));
	const unsubUser = currentUser.subscribe((u) => {
		if (u) userName = u.name?.split(' ')[0] || '';
	});

	onMount(() => {
		fetchProjects();
		return () => {
			unsubProjects();
			unsubActive();
			unsubUser();
		};
	});

	function select(project: ProjectListItem | null): void {
		open = false;
		if (project) {
			setActiveProject(project.id);
			goto(resolve(`/projects/${project.id}/chat`));
		} else {
			setActiveProject(null);
			goto(resolve('/'));
		}
	}
</script>

<svelte:window
	onclick={(e) => {
		if (open && !(e.target as HTMLElement).closest('[data-home-project-selector]')) {
			open = false;
		}
	}}
/>

<div class="relative inline-flex" data-home-project-selector>
	<button
		onclick={() => (open = !open)}
		class="flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-[13px] text-subtle transition-colors duration-150 hover:bg-surface-2 hover:text-foreground"
	>
		{#if selectedProject?.icon}
			<span class="shrink-0 text-sm leading-none">{selectedProject.icon}</span>
		{:else if selectedProject}
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
				class="shrink-0"
			>
				<path
					d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"
				/>
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
				class="shrink-0"
			>
				<circle cx="12" cy="12" r="10" />
				<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
				<path d="M2 12h20" />
			</svg>
		{/if}
		<span class="max-w-[220px] truncate">
			{selectedProject?.title ??
				(userName ? `${userName}'s default workspace` : 'Default workspace')}
		</span>
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
			class="shrink-0 text-muted"
		>
			<path d="M6 9l6 6 6-6" />
		</svg>
	</button>

	{#if open}
		<div
			class="absolute left-1/2 z-50 mt-1 w-56 -translate-x-1/2 animate-[dropdownIn_0.12s_ease-out] rounded-xl border border-border-subtle bg-surface-2 py-1 shadow-xl"
			style="top: 100%"
		>
			<button
				onclick={() => select(null)}
				class="flex w-full items-center gap-2.5 px-3 py-2 text-[13px] transition-colors hover:bg-surface-2
					{selectedProject === null ? 'font-medium text-foreground' : 'text-subtle'}"
			>
				<div class="flex h-6 w-6 items-center justify-center rounded bg-surface-2 text-muted">
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
						<circle cx="12" cy="12" r="10" />
						<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
						<path d="M2 12h20" />
					</svg>
				</div>
				{userName ? `${userName}'s default workspace` : 'Default workspace'}
			</button>

			{#each projectList as project (project.id)}
				<button
					onclick={() => select(project)}
					class="flex w-full items-center gap-2.5 px-3 py-2 text-[13px] transition-colors hover:bg-surface-2
						{selectedProject?.id === project.id ? 'font-medium text-foreground' : 'text-subtle'}"
				>
					<div class="flex h-6 w-6 items-center justify-center rounded bg-surface-2 text-[11px]">
						{project.icon || project.title.charAt(0).toUpperCase()}
					</div>
					<span class="truncate">{project.title}</span>
				</button>
			{/each}

			<div class="mt-1 border-t border-border-subtle pt-1">
				<a
					href={resolve('/projects')}
					onclick={() => (open = false)}
					class="flex w-full items-center gap-2.5 px-3 py-2 text-[13px] text-subtle transition-colors hover:bg-surface-2 hover:text-accent"
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
						class="ml-1"
					>
						<path d="M12 5v14" />
						<path d="M5 12h14" />
					</svg>
					New project
				</a>
			</div>
		</div>
	{/if}
</div>
