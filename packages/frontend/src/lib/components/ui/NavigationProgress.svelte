<script lang="ts">
	import { navigating } from '$app/stores';
</script>

{#if $navigating}
	<div
		class="fixed inset-x-0 top-0 z-[9999] h-0.5"
		role="progressbar"
		aria-label="Page loading"
		aria-busy="true"
	>
		<div class="nav-progress-bar h-full bg-accent"></div>
	</div>
{/if}

<style>
	@keyframes nav-progress {
		0% {
			width: 0%;
		}
		50% {
			width: 80%;
		}
		100% {
			width: 100%;
		}
	}

	.nav-progress-bar {
		animation: nav-progress 1.5s ease-in-out infinite;
	}
</style>
