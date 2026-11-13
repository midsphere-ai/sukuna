<script lang="ts">
	import { Dialog } from '$components/ui';
	import { toasts } from '$stores/toast';
	import type { Message } from '$services/sse';
	import {
		exportToMarkdown,
		exportToJson,
		downloadBlob,
		sanitizeFilename
	} from '$services/chatExport';

	type Props = {
		open: boolean;
		title: string;
		messages: Message[];
		dateCreated?: string;
	};

	let { open = $bindable(false), title, messages, dateCreated }: Props = $props();

	let exporting = $state(false);
	let selectedFormat: 'markdown' | 'json' = $state('markdown');

	const formats = [
		{
			id: 'markdown' as const,
			label: 'Markdown',
			ext: '.md',
			description: 'Formatted text with headings and structure',
			icon: 'M3 5h2l3 9 3-9h2' // stylised M
		},
		{
			id: 'json' as const,
			label: 'JSON',
			ext: '.json',
			description: 'Structured data for programmatic use',
			icon: '' // will use custom path
		}
	];

	function doExport(): void {
		if (exporting) return;
		exporting = true;

		requestAnimationFrame(() => {
			try {
				const filename = sanitizeFilename(title);
				if (selectedFormat === 'markdown') {
					const content = exportToMarkdown(title, messages, dateCreated);
					downloadBlob(content, `${filename}.md`, 'text/markdown');
					toasts.success('Exported as Markdown');
				} else {
					const content = exportToJson(title, messages, dateCreated);
					downloadBlob(content, `${filename}.json`, 'application/json');
					toasts.success('Exported as JSON');
				}
				open = false;
			} catch {
				toasts.error('Export failed');
			} finally {
				exporting = false;
			}
		});
	}
</script>

<Dialog bind:open class="max-w-sm" aria-label="Export conversation">
	<div class="p-5">
		<div class="flex items-center gap-3">
			<div
				class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface border border-border"
			>
				<svg
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="text-accent"
				>
					<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
					<polyline points="7 10 12 15 17 10" />
					<line x1="12" x2="12" y1="15" y2="3" />
				</svg>
			</div>
			<div>
				<h3 class="text-[15px] font-medium text-foreground">Export conversation</h3>
				<p class="text-xs text-muted">Choose a format to download</p>
			</div>
		</div>

		<!-- Format selection -->
		<div class="mt-4 space-y-2">
			{#each formats as format (format.id)}
				<button
					onclick={() => (selectedFormat = format.id)}
					class="flex w-full items-center gap-3 rounded-xl border px-3.5 py-3 text-left transition-all duration-200 {selectedFormat ===
					format.id
						? 'border-accent/30 bg-accent/[0.04] ring-1 ring-accent/10'
						: 'border-border-subtle bg-surface hover:border-border-strong hover:bg-surface-2'}"
				>
					<div
						class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg {selectedFormat ===
						format.id
							? 'bg-accent/[0.1] text-accent'
							: 'bg-surface text-muted'}"
					>
						{#if format.id === 'markdown'}
							<svg
								width="16"
								height="16"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z" />
								<polyline points="14 2 14 8 20 8" />
							</svg>
						{:else}
							<svg
								width="16"
								height="16"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z" />
								<polyline points="14 2 14 8 20 8" />
								<path d="M8 13h2" />
								<path d="M8 17h2" />
								<path d="M14 13h2" />
								<path d="M14 17h2" />
							</svg>
						{/if}
					</div>
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span
								class="text-sm font-medium {selectedFormat === format.id
									? 'text-foreground'
									: 'text-foreground'}">{format.label}</span
							>
							<span class="rounded-md bg-surface px-1.5 py-0.5 text-[10.5px] font-medium text-muted"
								>{format.ext}</span
							>
						</div>
						<p class="mt-0.5 text-xs text-muted">{format.description}</p>
					</div>
					{#if selectedFormat === format.id}
						<svg
							width="16"
							height="16"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="shrink-0 text-accent"
						>
							<polyline points="20 6 9 17 4 12" />
						</svg>
					{/if}
				</button>
			{/each}
		</div>

		<!-- Actions -->
		<div class="mt-5 flex justify-end gap-2">
			<button
				onclick={() => (open = false)}
				class="rounded-xl border border-border px-4 py-2 text-sm font-medium text-subtle transition-all duration-200 hover:bg-surface hover:text-foreground"
			>
				Cancel
			</button>
			<button
				onclick={doExport}
				disabled={exporting}
				class="rounded-xl bg-foreground px-4 py-2 text-sm font-medium text-background transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60"
			>
				{exporting ? 'Exporting...' : 'Export'}
			</button>
		</div>
	</div>
</Dialog>
