<script lang="ts">
	import { marked } from 'marked';
	import { extensionMap as sharedExtensionMap } from '$lib/utils/fileCategories';
	import { tooltip } from '$lib/actions/tooltip';

	type Props = {
		open: boolean;
		filename: string;
		fileUrl: string;
		onclose?: () => void;
	};

	let { open = $bindable(false), filename, fileUrl, onclose }: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let zoomed = $state(false);
	let closing = $state(false);
	let textContent = $state('');
	let textLoading = $state(false);
	let textError = $state('');

	// --- File type detection (extended with markdown/text for preview rendering) ---

	type FileCategory =
		'image' | 'pdf' | 'video' | 'audio' | 'code' | 'markdown' | 'text' | 'archive' | 'unknown';

	const extensionMap: Record<string, FileCategory> = {
		...sharedExtensionMap,
		// Override shared categories for preview-specific handling
		md: 'markdown',
		txt: 'text',
		log: 'text',
		csv: 'text',
		rtf: 'text'
	};

	const languageLabels: Record<string, string> = {
		js: 'JavaScript',
		ts: 'TypeScript',
		jsx: 'JSX',
		tsx: 'TSX',
		py: 'Python',
		rb: 'Ruby',
		go: 'Go',
		rs: 'Rust',
		java: 'Java',
		cpp: 'C++',
		c: 'C',
		h: 'C Header',
		css: 'CSS',
		scss: 'SCSS',
		html: 'HTML',
		json: 'JSON',
		yaml: 'YAML',
		yml: 'YAML',
		xml: 'XML',
		sql: 'SQL',
		sh: 'Shell'
	};

	let fileExtension = $derived(filename.split('.').pop()?.toLowerCase() || '');
	let fileCategory = $derived((extensionMap[fileExtension] || 'unknown') as FileCategory);
	let languageLabel = $derived(languageLabels[fileExtension] || fileExtension.toUpperCase());

	// --- Fetch text content for code/markdown/text files ---

	async function fetchTextContent(): Promise<void> {
		if (!fileUrl) return;
		textLoading = true;
		textError = '';
		textContent = '';
		try {
			const res = await fetch(fileUrl);
			if (!res.ok) throw new Error(`Failed to load file (${res.status})`);
			textContent = await res.text();
		} catch (e) {
			textError = e instanceof Error ? e.message : 'Failed to load file content';
		} finally {
			textLoading = false;
		}
	}

	let renderedMarkdown = $derived.by(() => {
		if (fileCategory !== 'markdown' || !textContent) return '';
		return marked.parse(textContent, { async: false, breaks: true, gfm: true }) as string;
	});

	let textLines = $derived(textContent ? textContent.split('\n') : []);

	// --- Dialog open/close sync ---

	function close(): void {
		closing = true;
		setTimeout(() => {
			closing = false;
			open = false;
			zoomed = false;
			textContent = '';
			textError = '';
			onclose?.();
		}, 150);
	}

	function handleBackdropClick(e: MouseEvent): void {
		if (e.target === dialogEl) {
			close();
		}
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	$effect(() => {
		if (!dialogEl) return;
		if (open && !dialogEl.open) {
			dialogEl.showModal();
			zoomed = false;
			// Fetch text content for text-based files
			if (fileCategory === 'code' || fileCategory === 'markdown' || fileCategory === 'text') {
				fetchTextContent();
			}
		} else if (!open && dialogEl.open) {
			dialogEl.close();
		}
	});

	function handleDownload(): void {
		if (!fileUrl) return;
		const a = document.createElement('a');
		a.href = fileUrl;
		a.download = filename;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
	}

	function toggleZoom(): void {
		zoomed = !zoomed;
	}
</script>

<dialog
	bind:this={dialogEl}
	class="animate-dialog fixed inset-0 m-0 h-screen w-screen max-h-screen max-w-full bg-foreground/95 p-0 backdrop:bg-foreground/40 open:flex open:flex-col"
	class:closing
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
	data-testid="file-preview-dialog"
>
	{#if open}
		<!-- Header -->
		<div
			class="flex shrink-0 items-center justify-between border-b border-background/[0.08] px-4 py-3 sm:px-6"
		>
			<div class="flex min-w-0 items-center gap-3">
				<h2 class="truncate text-sm font-medium text-background">{filename}</h2>
				{#if fileCategory === 'code'}
					<span
						class="shrink-0 rounded bg-background/10 px-2 py-0.5 text-[10.5px] font-medium text-background/60"
						>{languageLabel}</span
					>
				{/if}
			</div>
			<div class="flex items-center gap-2">
				<!-- Download button -->
				<button
					onclick={handleDownload}
					class="flex items-center gap-1.5 rounded-lg bg-background/10 px-3 py-1.5 text-xs font-medium text-background/80 transition-colors hover:bg-background/20"
					title="Download"
					data-testid="download-button"
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
					>
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
						<polyline points="7 10 12 15 17 10" />
						<line x1="12" x2="12" y1="15" y2="3" />
					</svg>
					Download
				</button>
				<!-- Close button -->
				<button
					onclick={close}
					class="flex h-8 w-8 items-center justify-center rounded-lg text-background/60 transition-colors hover:bg-background/10 hover:text-background"
					title="Close"
					data-testid="close-button"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="18"
						height="18"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<line x1="18" x2="6" y1="6" y2="18" />
						<line x1="6" x2="18" y1="6" y2="18" />
					</svg>
				</button>
			</div>
		</div>

		<!-- Content area -->
		<div class="flex flex-1 items-center justify-center overflow-auto p-4 sm:p-8">
			{#if fileCategory === 'image'}
				<!-- Image viewer with zoom -->
				<button
					onclick={toggleZoom}
					class="flex items-center justify-center {zoomed ? 'cursor-zoom-out' : 'cursor-zoom-in'}"
					data-testid="image-viewer"
					aria-label={zoomed ? 'Zoom out' : 'Zoom in'}
					use:tooltip={zoomed ? 'Zoom out' : 'Zoom in'}
				>
					<img
						src={fileUrl}
						alt={filename}
						class="transition-transform duration-300 {zoomed
							? 'max-h-none max-w-none scale-150'
							: 'max-h-[80vh] max-w-full object-contain'}"
					/>
				</button>
			{:else if fileCategory === 'pdf'}
				<!-- PDF viewer -->
				<div class="h-full w-full max-w-4xl" data-testid="pdf-viewer">
					<iframe
						src={fileUrl}
						title="PDF preview: {filename}"
						class="h-full w-full rounded-lg border border-background/10"
					></iframe>
				</div>
			{:else if fileCategory === 'video'}
				<!-- Video player -->
				<div class="w-full max-w-4xl" data-testid="video-player">
					<!-- svelte-ignore a11y_media_has_caption -->
					<video src={fileUrl} controls class="w-full rounded-lg">
						Your browser does not support the video element.
					</video>
				</div>
			{:else if fileCategory === 'audio'}
				<!-- Audio player -->
				<div class="w-full max-w-lg" data-testid="audio-player">
					<div class="rounded-xl bg-background/5 p-6">
						<div class="mb-4 flex items-center justify-center">
							<div class="flex h-20 w-20 items-center justify-center rounded-full bg-background/10">
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="32"
									height="32"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="text-background/60"
								>
									<path d="M9 18V5l12-2v13" />
									<circle cx="6" cy="18" r="3" />
									<circle cx="18" cy="16" r="3" />
								</svg>
							</div>
						</div>
						<p class="mb-3 text-center text-sm font-medium text-background/80">{filename}</p>
						<audio src={fileUrl} controls class="w-full">
							Your browser does not support the audio element.
						</audio>
					</div>
				</div>
			{:else if fileCategory === 'code'}
				<!-- Code viewer with line numbers -->
				<div
					class="h-full w-full max-w-5xl overflow-auto rounded-lg border border-background/10 bg-[#1a1a2e]"
					data-testid="code-viewer"
				>
					{#if textLoading}
						<div class="flex items-center justify-center p-8">
							<div class="flex items-center gap-2 text-background/40">
								<svg
									class="h-4 w-4 animate-spin"
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
								>
									<circle
										class="opacity-25"
										cx="12"
										cy="12"
										r="10"
										stroke="currentColor"
										stroke-width="4"
									></circle>
									<path
										class="opacity-75"
										fill="currentColor"
										d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
									></path>
								</svg>
								Loading...
							</div>
						</div>
					{:else if textError}
						<div class="flex items-center justify-center p-8">
							<p class="text-sm text-accent">{textError}</p>
						</div>
					{:else}
						<div class="overflow-auto">
							<table class="w-full border-collapse font-mono text-sm">
								<tbody>
									{#each textLines as line, i (i)}
										<tr class="hover:bg-background/[0.03]">
											<td
												class="select-none border-r border-background/[0.06] px-3 py-0 text-right align-top text-xs leading-6 text-background/20"
												>{i + 1}</td
											>
											<td class="whitespace-pre px-4 py-0 leading-6 text-background/80">{line}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}
				</div>
			{:else if fileCategory === 'markdown'}
				<!-- Markdown rendered view -->
				<div
					class="h-full w-full max-w-3xl overflow-auto rounded-lg border border-background/10 bg-background/5 p-6 sm:p-8"
					data-testid="markdown-viewer"
				>
					{#if textLoading}
						<div class="flex items-center justify-center p-8">
							<div class="flex items-center gap-2 text-background/40">
								<svg
									class="h-4 w-4 animate-spin"
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
								>
									<circle
										class="opacity-25"
										cx="12"
										cy="12"
										r="10"
										stroke="currentColor"
										stroke-width="4"
									></circle>
									<path
										class="opacity-75"
										fill="currentColor"
										d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
									></path>
								</svg>
								Loading...
							</div>
						</div>
					{:else if textError}
						<div class="flex items-center justify-center p-8">
							<p class="text-sm text-accent">{textError}</p>
						</div>
					{:else}
						<!-- eslint-disable svelte/no-at-html-tags -->
						<div
							class="prose prose-sm prose-invert max-w-none text-background/90 [&_a]:text-accent [&_a]:underline [&_code]:rounded [&_code]:bg-background/10 [&_code]:px-1.5 [&_code]:py-0.5 [&_pre]:rounded-lg [&_pre]:bg-[#1a1a2e] [&_pre]:p-4"
						>
							{@html renderedMarkdown}
						</div>
						<!-- eslint-enable svelte/no-at-html-tags -->
					{/if}
				</div>
			{:else if fileCategory === 'text'}
				<!-- Plain text viewer -->
				<div
					class="h-full w-full max-w-4xl overflow-auto rounded-lg border border-background/10 bg-background/5 p-6"
					data-testid="text-viewer"
				>
					{#if textLoading}
						<div class="flex items-center justify-center p-8">
							<div class="flex items-center gap-2 text-background/40">
								<svg
									class="h-4 w-4 animate-spin"
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
								>
									<circle
										class="opacity-25"
										cx="12"
										cy="12"
										r="10"
										stroke="currentColor"
										stroke-width="4"
									></circle>
									<path
										class="opacity-75"
										fill="currentColor"
										d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
									></path>
								</svg>
								Loading...
							</div>
						</div>
					{:else if textError}
						<div class="flex items-center justify-center p-8">
							<p class="text-sm text-accent">{textError}</p>
						</div>
					{:else}
						<pre
							class="whitespace-pre-wrap font-mono text-sm leading-6 text-background/80">{textContent}</pre>
					{/if}
				</div>
			{:else if fileCategory === 'archive'}
				<!-- Archive — cannot preview -->
				<div class="text-center" data-testid="archive-notice">
					<div class="mb-4 flex justify-center">
						<div class="flex h-20 w-20 items-center justify-center rounded-full bg-background/10">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="32"
								height="32"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="text-background/60"
							>
								<path d="M21 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v3" />
								<path d="M21 16v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-3" />
								<path d="M4 12h16" />
								<path d="m9 16 3-4 3 4" />
							</svg>
						</div>
					</div>
					<p class="text-sm font-medium text-background/80">{filename}</p>
					<p class="mt-1 text-xs text-background/40">
						Archive files cannot be previewed. Use the download button.
					</p>
				</div>
			{:else}
				<!-- Unknown file type -->
				<div class="text-center" data-testid="unknown-notice">
					<div class="mb-4 flex justify-center">
						<div class="flex h-20 w-20 items-center justify-center rounded-full bg-background/10">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="32"
								height="32"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="text-background/60"
							>
								<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
								<path d="M14 2v4a2 2 0 0 0 2 2h4" />
							</svg>
						</div>
					</div>
					<p class="text-sm font-medium text-background/80">{filename}</p>
					<p class="mt-1 text-xs text-background/40">
						This file type cannot be previewed. Use the download button.
					</p>
				</div>
			{/if}
		</div>
	{/if}
</dialog>

<style>
	.animate-dialog[open] {
		animation: dialog-in 150ms ease-out;
	}
	.animate-dialog[open]::backdrop {
		animation: backdrop-in 150ms ease-out;
	}
	.animate-dialog.closing {
		animation: dialog-out 150ms ease-in forwards;
	}
	.animate-dialog.closing::backdrop {
		animation: backdrop-out 150ms ease-in forwards;
	}
	@keyframes dialog-in {
		from {
			opacity: 0;
			transform: scale(0.97);
		}
		to {
			opacity: 1;
			transform: scale(1);
		}
	}
	@keyframes dialog-out {
		from {
			opacity: 1;
			transform: scale(1);
		}
		to {
			opacity: 0;
			transform: scale(0.97);
		}
	}
	@keyframes backdrop-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}
	@keyframes backdrop-out {
		from {
			opacity: 1;
		}
		to {
			opacity: 0;
		}
	}
</style>
