<script lang="ts">
	type Props = {
		content: string;
		language?: string;
		readonly?: boolean;
		wordWrap?: boolean;
		onchange?: (content: string) => void;
		onsave?: () => void;
	};

	let {
		content,
		language = 'text',
		readonly = true,
		wordWrap = false,
		onchange,
		onsave
	}: Props = $props();

	const editorPromise = import('./CodeMirrorEditor.svelte');
</script>

{#await editorPromise}
	<div
		class="flex h-full w-full items-center justify-center bg-background"
		data-testid="codemirror-loading"
	>
		<div class="flex flex-col items-center gap-3">
			<div
				class="h-6 w-6 animate-spin rounded-full border-2 border-border-subtle border-t-dark"
			></div>
			<p class="text-xs text-muted">Loading editor…</p>
		</div>
	</div>
{:then module}
	<module.default {content} {language} {readonly} {wordWrap} {onchange} {onsave} />
{:catch}
	<div class="flex h-full w-full items-center justify-center bg-background">
		<p class="text-xs text-red-500">Failed to load editor</p>
	</div>
{/await}
