<script lang="ts">
	import { Skeleton } from '$components/ui';
	import EmptyState from '$components/ui/EmptyState.svelte';
	import FilePreviewDialog from './FilePreviewDialog.svelte';
	import { getFileCategory } from '$lib/utils/fileCategories';
	import { tooltip } from '$lib/actions/tooltip';

	type FileEntry = {
		filename: string;
		url: string;
		size?: number;
		timestamp?: string;
	};

	type Props = {
		open: boolean;
		files: FileEntry[];
		loading?: boolean;
		onclose?: () => void;
	};

	let { open = $bindable(false), files, loading = false, onclose }: Props = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let closing = $state(false);

	// File preview sub-dialog
	let previewOpen = $state(false);
	let previewFilename = $state('');
	let previewFileUrl = $state('');

	function getFileExtension(filename: string): string {
		return filename.split('.').pop()?.toUpperCase() || '';
	}

	function formatFileSize(bytes?: number): string {
		if (!bytes) return '';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function formatTimestamp(ts?: string): string {
		if (!ts) return '';
		try {
			return new Intl.DateTimeFormat('en', {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			}).format(new Date(ts));
		} catch {
			return '';
		}
	}

	function isImageFile(filename: string): boolean {
		return getFileCategory(filename) === 'image';
	}

	// --- Dialog lifecycle ---

	function close(): void {
		closing = true;
		setTimeout(() => {
			closing = false;
			open = false;
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
		} else if (!open && dialogEl.open) {
			dialogEl.close();
		}
	});

	// --- Actions ---

	function handleFileClick(file: FileEntry): void {
		previewFilename = file.filename;
		previewFileUrl = file.url;
		previewOpen = true;
	}

	function handleDownload(file: FileEntry): void {
		const a = document.createElement('a');
		a.href = file.url;
		a.download = file.filename;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
	}
</script>

<dialog
	bind:this={dialogEl}
	class="animate-dialog fixed inset-0 m-0 h-screen w-screen max-h-screen max-w-full bg-transparent p-0 backdrop:bg-foreground/40 open:flex open:flex-col open:items-center open:justify-center"
	class:closing
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
	data-testid="chat-files-dialog"
>
	{#if open}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="mx-4 flex max-h-[85vh] w-full max-w-3xl flex-col rounded-2xl border border-border bg-background shadow-xl"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<!-- Header -->
			<div
				class="flex shrink-0 items-center justify-between border-b border-border-subtle px-5 py-4"
			>
				<div class="flex items-center gap-2.5">
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
						class="text-muted"
					>
						<path d="M15 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7z" />
						<path d="M14 2v4a2 2 0 002 2h4" />
					</svg>
					<h2 class="text-sm font-medium text-foreground">Session Files</h2>
					{#if !loading && files.length > 0}
						<span class="rounded-full bg-surface px-2 py-0.5 text-[11.5px] font-medium text-subtle">
							{files.length}
						</span>
					{/if}
				</div>
				<button
					onclick={close}
					class="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
					title="Close"
					aria-label="Close files dialog"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="16"
						height="16"
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

			<!-- Content -->
			<div class="flex-1 overflow-y-auto p-5">
				{#if loading}
					<!-- Loading skeleton grid -->
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
						{#each [0, 1, 2, 3, 4, 5] as i (i)}
							<div class="rounded-xl border border-border-subtle bg-surface p-3">
								<Skeleton class="mb-3 rounded-xl" width="100%" height="96px" stagger={i} />
								<Skeleton class="rounded" width="75%" height="12px" stagger={i + 1} />
							</div>
						{/each}
					</div>
				{:else if files.length === 0}
					<!-- Empty state -->
					<EmptyState
						title="No files yet"
						description="Files uploaded to or generated during this chat session will appear here."
					>
						{#snippet illustration()}
							<div
								class="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-2 text-muted"
							>
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
								>
									<path d="M15 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7z" />
									<path d="M14 2v4a2 2 0 002 2h4" />
									<line x1="16" x2="8" y1="13" y2="13" />
									<line x1="16" x2="8" y1="17" y2="17" />
									<line x1="10" x2="8" y1="9" y2="9" />
								</svg>
							</div>
						{/snippet}
					</EmptyState>
				{:else}
					<!-- File grid -->
					<div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
						{#each files as file (file.url)}
							<div
								class="group relative flex flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface transition-all duration-200 hover:-translate-y-0.5 hover:border-border-strong hover:shadow-md"
							>
								<!-- Thumbnail / Icon area -->
								<button
									onclick={() => handleFileClick(file)}
									class="flex h-24 w-full items-center justify-center bg-surface transition-colors group-hover:bg-surface-2 sm:h-28"
									title="Preview {file.filename}"
								>
									{#if isImageFile(file.filename)}
										<img
											src={file.url}
											alt={file.filename}
											class="h-full w-full object-cover"
											loading="lazy"
										/>
									{:else}
										<!-- Type icon -->
										{@const category = getFileCategory(file.filename)}
										<div class="flex flex-col items-center gap-1.5">
											{#if category === 'pdf'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="28"
													height="28"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="1.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="text-red-400"
												>
													<path
														d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"
													/>
													<polyline points="14 2 14 8 20 8" />
													<line x1="16" x2="8" y1="13" y2="13" />
													<line x1="16" x2="8" y1="17" y2="17" />
												</svg>
											{:else if category === 'video'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="28"
													height="28"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="1.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="text-purple-400"
												>
													<polygon points="23 7 16 12 23 17 23 7" />
													<rect width="15" height="14" x="1" y="5" rx="2" ry="2" />
												</svg>
											{:else if category === 'audio'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="28"
													height="28"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="1.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="text-green-400"
												>
													<path d="M9 18V5l12-2v13" />
													<circle cx="6" cy="18" r="3" />
													<circle cx="18" cy="16" r="3" />
												</svg>
											{:else if category === 'code'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="28"
													height="28"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="1.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="text-accent"
												>
													<polyline points="16 18 22 12 16 6" />
													<polyline points="8 6 2 12 8 18" />
												</svg>
											{:else if category === 'archive'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="28"
													height="28"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="1.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="text-yellow-500"
												>
													<path d="M21 8V5a2 2 0 00-2-2H5a2 2 0 00-2 2v3" />
													<path d="M21 16v3a2 2 0 01-2 2H5a2 2 0 01-2-2v-3" />
													<path d="M4 12h16" />
												</svg>
											{:else}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													width="28"
													height="28"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="1.5"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="text-muted"
												>
													<path d="M15 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7z" />
													<path d="M14 2v4a2 2 0 002 2h4" />
												</svg>
											{/if}
											<span class="text-[10.5px] font-medium text-muted"
												>{getFileExtension(file.filename)}</span
											>
										</div>
									{/if}
								</button>

								<!-- File info -->
								<div class="flex items-start justify-between gap-2 p-2.5">
									<button
										onclick={() => handleFileClick(file)}
										class="min-w-0 flex-1 text-left"
										title={file.filename}
									>
										<p class="truncate text-xs font-medium text-foreground">{file.filename}</p>
										<div class="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-muted">
											{#if file.size}
												<span>{formatFileSize(file.size)}</span>
											{/if}
											{#if file.size && file.timestamp}
												<span>·</span>
											{/if}
											{#if file.timestamp}
												<span>{formatTimestamp(file.timestamp)}</span>
											{/if}
										</div>
									</button>

									<!-- Download button -->
									<button
										onclick={() => handleDownload(file)}
										class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-subtle"
										title="Download {file.filename}"
										aria-label="Download {file.filename}"
										use:tooltip={`Download ${file.filename}`}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="13"
											height="13"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
										>
											<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
											<polyline points="7 10 12 15 17 10" />
											<line x1="12" x2="12" y1="15" y2="3" />
										</svg>
									</button>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</dialog>

<!-- File preview sub-dialog -->
<FilePreviewDialog bind:open={previewOpen} filename={previewFilename} fileUrl={previewFileUrl} />

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
			transform: scale(0.95) translateY(-8px);
		}
		to {
			opacity: 1;
			transform: scale(1) translateY(0);
		}
	}
	@keyframes dialog-out {
		from {
			opacity: 1;
			transform: scale(1) translateY(0);
		}
		to {
			opacity: 0;
			transform: scale(0.95) translateY(-8px);
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
