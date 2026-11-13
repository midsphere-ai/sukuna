<script lang="ts">
	type Props = {
		position: number | null;
	};

	let { position }: Props = $props();
</script>

{#if position !== null && position > 0}
	<div
		class="mx-4 mb-2 flex items-center gap-2 rounded-lg border border-border-subtle bg-surface px-3 py-2 sm:mx-5 md:mx-6 lg:mx-8"
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
			class="shrink-0 text-muted"
		>
			<circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
		</svg>
		<span class="text-[14px] text-subtle">
			Your message is queued (position {position})
		</span>
	</div>
{/if}
