<script lang="ts">
	import TauriWindowControls from './TauriWindowControls.svelte';
	import { initTauriWindow } from '$stores/tauri';
	import { onMount } from 'svelte';

	onMount(() => {
		initTauriWindow();
	});
</script>

<!-- Minimal title bar for pages without an integrated header (login, signup, etc.) -->
<div
	data-tauri-drag-region
	class="flex h-[var(--header-height)] shrink-0 items-center justify-end bg-background select-none"
>
	<TauriWindowControls />
</div>
