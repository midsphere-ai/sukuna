<script lang="ts">
	interface Props {
		onselect: (prompt: string) => void;
	}

	let { onselect }: Props = $props();

	const suggestions = [
		{
			label: 'Write',
			prompt: 'Help me write a clear technical brief',
			icon: `<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>`
		},
		{
			label: 'Learn',
			prompt: 'Teach me this concept step by step',
			icon: `<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>`
		},
		{
			label: 'Code',
			prompt: 'Implement this feature with production-quality code',
			icon: `<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>`
		},
		{
			label: 'Life stuff',
			prompt: 'Help me plan this real-life decision',
			icon: `<path d="M20 13c0 5-3.5 7-8 7s-8-2-8-7a8 8 0 1 1 16 0"/><path d="M8 13h8"/>`
		},
		{
			label: "Jatayu AI's choice",
			prompt: 'Suggest the best way to tackle this task',
			icon: `<path d="m12 3 1.8 3.6L18 8.4l-3 2.9.7 4.2L12 13.8 8.3 15.5 9 11.3 6 8.4l4.2-.8Z"/>`
		}
	];
</script>

<div class="mt-4 flex flex-wrap items-center justify-center gap-2">
	{#each suggestions as suggestion (suggestion.label)}
		<button
			onclick={() => onselect(suggestion.prompt)}
			class="flex items-center gap-2 rounded-[10px] border border-border-subtle bg-transparent px-3 py-1.5 text-[14px] font-medium text-muted transition-all duration-150 hover:bg-surface-2 hover:text-foreground"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="15"
				height="15"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.75"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="shrink-0 text-subtle"
			>
				<!-- eslint-disable-next-line svelte/no-at-html-tags -- trusted static SVG path data -->
				{@html suggestion.icon}
			</svg>
			{suggestion.label}
		</button>
	{/each}
</div>
