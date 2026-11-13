<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import SkillEditor from '$components/skills/SkillEditor.svelte';
	import { LoadingSpinner } from '$components/ui';
	import { getMySkill, type UserSkillDetail } from '$api/user_skills';
	import { toasts } from '$stores/toast';

	let skill: UserSkillDetail | null = $state(null);
	let loading = $state(true);

	onMount(async () => {
		const id = $page.params.id;
		if (!id) {
			await goto('/skills');
			return;
		}
		try {
			skill = await getMySkill(id);
		} catch {
			toasts.error('Skill not found');
			await goto('/skills');
			return;
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>{skill?.name ?? 'Edit skill'} - Jatayu AI</title>
</svelte:head>

{#if loading}
	<div class="flex min-h-[60vh] items-center justify-center">
		<LoadingSpinner />
	</div>
{:else if skill}
	<SkillEditor existing={skill} />
{/if}
