<script lang="ts">
	import { tooltip } from '$lib/actions/tooltip';

	type ActionItem = {
		id: string;
		label: string;
		icon: 'copy' | 'edit' | 'branch' | 'export';
		action: () => void;
	};

	type Props = {
		items: ActionItem[];
		position?: 'left' | 'right';
		alwaysVisible?: boolean;
	};

	let { items, position = 'right', alwaysVisible = false }: Props = $props();
</script>

<div
	class="{alwaysVisible
		? 'grid grid-rows-[1fr]'
		: 'hidden sm:grid grid-rows-[0fr] group-hover/msg:grid-rows-[1fr]'} transition-[grid-template-rows] duration-200 ease-out"
>
	<div class="overflow-hidden">
		<div
			class="flex items-center gap-0.5 pt-1 transition-opacity duration-150 {alwaysVisible
				? 'opacity-100'
				: 'opacity-0 group-hover/msg:opacity-100'} {position === 'left'
				? 'justify-start'
				: 'justify-end'}"
		>
			{#each items as item (item.id)}
				<button
					onclick={item.action}
					class="rounded-md p-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
					use:tooltip={item.label}
					aria-label={item.label}
				>
					{#if item.icon === 'copy'}
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
							<rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
							<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
						</svg>
					{:else if item.icon === 'edit'}
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
							<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
							<path d="m15 5 4 4" />
						</svg>
					{:else if item.icon === 'branch'}
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
							<circle cx="12" cy="18" r="3" />
							<circle cx="6" cy="6" r="3" />
							<circle cx="18" cy="6" r="3" />
							<path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9" />
							<path d="M12 12v3" />
						</svg>
					{:else if item.icon === 'export'}
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
							<polyline points="7 10 12 15 17 10" />
							<line x1="12" x2="12" y1="15" y2="3" />
						</svg>
					{/if}
				</button>
			{/each}
		</div>
	</div>
</div>
