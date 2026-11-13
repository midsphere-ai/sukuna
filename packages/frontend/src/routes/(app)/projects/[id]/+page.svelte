<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { pageTitle } from '$stores/page';
	import { setActiveProject } from '$stores/projects';
	import type { ProjectDetail } from '$api/types';
	import ProjectSettingsPanel from '$components/projects/ProjectSettingsPanel.svelte';

	let projectId = $derived(page.params.id ?? '');

	onMount(() => {
		pageTitle.set('Project');
		if (projectId) {
			setActiveProject(projectId);
		}
		return () => {
			setActiveProject(null);
		};
	});

	function handleProjectUpdated(project: ProjectDetail): void {
		pageTitle.set(project.title);
	}

	function handleDeleted(): void {
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- internal route
		goto('/');
	}
</script>

<div class="mx-auto w-full max-w-2xl p-6">
	<ProjectSettingsPanel
		{projectId}
		onProjectUpdated={handleProjectUpdated}
		onDeleted={handleDeleted}
	/>
</div>
