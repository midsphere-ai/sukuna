<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { getCanvasType } from '$lib/utils/toolLabels';
	import TerminalCanvas from './TerminalCanvas.svelte';
	import DiffCanvas from './DiffCanvas.svelte';
	import CodeViewerCanvas from './CodeViewerCanvas.svelte';
	import BrowserCanvas from './BrowserCanvas.svelte';
	import SearchCanvas from './SearchCanvas.svelte';
	import FileTreeCanvas from './FileTreeCanvas.svelte';
	import FileStatusCanvas from './FileStatusCanvas.svelte';
	import DatabaseCanvas from './DatabaseCanvas.svelte';
	import DevServerCanvas from './DevServerCanvas.svelte';
	import MediaCanvas from './MediaCanvas.svelte';
	import VisionCanvas from './VisionCanvas.svelte';
	import AudioCanvas from './AudioCanvas.svelte';
	import DownloadCanvas from './DownloadCanvas.svelte';
	import ReasoningCanvas from './ReasoningCanvas.svelte';
	import SettingsCanvas from './SettingsCanvas.svelte';
	import CheckpointCanvas from './CheckpointCanvas.svelte';
	import ArtifactCanvas from './ArtifactCanvas.svelte';
	import PreviewCanvas from './PreviewCanvas.svelte';
	import ProjectCanvas from './ProjectCanvas.svelte';
	import KmCanvas from './KmCanvas.svelte';

	type Props = {
		toolCall: ToolCallMessage;
	};

	let { toolCall }: Props = $props();
	let canvasType = $derived(getCanvasType(toolCall.toolName, toolCall.args));
</script>

<div class="h-full overflow-hidden">
	{#if canvasType === 'terminal'}
		<TerminalCanvas {toolCall} />
	{:else if canvasType === 'diff'}
		<DiffCanvas {toolCall} />
	{:else if canvasType === 'code-viewer'}
		<CodeViewerCanvas {toolCall} />
	{:else if canvasType === 'browser'}
		<BrowserCanvas {toolCall} />
	{:else if canvasType === 'search'}
		<SearchCanvas {toolCall} />
	{:else if canvasType === 'file-tree'}
		<FileTreeCanvas {toolCall} />
	{:else if canvasType === 'file-status'}
		<FileStatusCanvas {toolCall} />
	{:else if canvasType === 'database'}
		<DatabaseCanvas {toolCall} />
	{:else if canvasType === 'dev-server'}
		<DevServerCanvas {toolCall} />
	{:else if canvasType === 'media'}
		<MediaCanvas {toolCall} />
	{:else if canvasType === 'vision'}
		<VisionCanvas {toolCall} />
	{:else if canvasType === 'audio'}
		<AudioCanvas {toolCall} />
	{:else if canvasType === 'download'}
		<DownloadCanvas {toolCall} />
	{:else if canvasType === 'reasoning'}
		<ReasoningCanvas {toolCall} />
	{:else if canvasType === 'settings'}
		<SettingsCanvas {toolCall} />
	{:else if canvasType === 'checkpoint'}
		<CheckpointCanvas {toolCall} />
	{:else if canvasType === 'artifact'}
		<ArtifactCanvas {toolCall} />
	{:else if canvasType === 'preview'}
		<PreviewCanvas {toolCall} />
	{:else if canvasType === 'project'}
		<ProjectCanvas {toolCall} />
	{:else if canvasType === 'km'}
		<KmCanvas {toolCall} />
	{/if}
</div>
