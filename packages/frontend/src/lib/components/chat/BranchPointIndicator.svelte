<script lang="ts">
	// Visual indicator shown at the branch point in a branched conversation
</script>

<div class="my-2 flex items-center gap-2 px-1" data-testid="branch-point-indicator">
	<div class="h-px flex-1 bg-accent/22"></div>
	<span
		class="flex items-center gap-1.5 rounded-full border border-accent/25 bg-accent/8 px-2.5 py-1 text-[11.5px] font-medium text-accent/85"
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
		>
			<circle cx="12" cy="18" r="3" />
			<circle cx="6" cy="6" r="3" />
			<circle cx="18" cy="6" r="3" />
			<path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9" />
			<path d="M12 12v3" />
		</svg>
		Branch created from this point
	</span>
	<div class="h-px flex-1 bg-accent/22"></div>
</div>
