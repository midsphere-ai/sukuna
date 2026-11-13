<script lang="ts">
	import type { FileTreeNode } from '$api/sandbox';
	import Self from './FileTreeNode.svelte';
	import {
		expandedDirs,
		selectedFilePath,
		creatingIn,
		toggleDir,
		expandDir,
		selectFile,
		createFileOrFolder,
		deleteFileOrFolder
	} from '$stores/fileExplorer';
	import ContextMenu from '$components/ui/ContextMenu.svelte';

	type Props = {
		node: FileTreeNode;
		conversationId: string;
		depth?: number;
	};

	let { node, conversationId, depth = 0 }: Props = $props();

	let expanded: Set<string> = $state(new Set());
	let selected: string | null = $state(null);
	let creating: { parentPath: string; type: 'file' | 'directory' } | null = $state(null);
	let newItemName = $state('');
	let newItemInput: HTMLInputElement | undefined = $state();

	const unsubExpanded = expandedDirs.subscribe((v) => (expanded = v));
	const unsubSelected = selectedFilePath.subscribe((v) => (selected = v));
	const unsubCreating = creatingIn.subscribe((v) => {
		creating = v;
		if (v && v.parentPath === node.path) {
			newItemName = '';
			requestAnimationFrame(() => newItemInput?.focus());
		}
	});

	import { onDestroy } from 'svelte';
	onDestroy(() => {
		unsubExpanded();
		unsubSelected();
		unsubCreating();
	});

	let isDir = $derived(node.type === 'directory');
	let isExpanded = $derived(expanded.has(node.path));
	let isSelected = $derived(selected === node.path);

	function handleClick(): void {
		if (isDir) {
			toggleDir(node.path);
		} else {
			selectFile(conversationId, node.path);
		}
	}

	function getContextMenuItems(): Array<{
		label: string;
		icon?: string;
		danger?: boolean;
		action: () => void;
	}> {
		const items: Array<{
			label: string;
			icon?: string;
			danger?: boolean;
			action: () => void;
		}> = [];

		if (isDir) {
			items.push({
				label: 'New file',
				action: () => {
					expandDir(node.path);
					creatingIn.set({ parentPath: node.path, type: 'file' });
				}
			});
			items.push({
				label: 'New folder',
				action: () => {
					expandDir(node.path);
					creatingIn.set({ parentPath: node.path, type: 'directory' });
				}
			});
		}

		items.push({
			label: 'Delete',
			danger: true,
			action: () => deleteFileOrFolder(conversationId, node.path)
		});

		return items;
	}

	async function handleNewItemSubmit(): Promise<void> {
		if (!creating || creating.parentPath !== node.path || !newItemName.trim()) {
			if (creating?.parentPath === node.path) creatingIn.set(null);
			return;
		}
		await createFileOrFolder(
			conversationId,
			creating.parentPath,
			newItemName.trim(),
			creating.type
		);
		creatingIn.set(null);
	}

	function handleNewItemKeydown(e: KeyboardEvent): void {
		if (e.key === 'Enter') {
			handleNewItemSubmit();
		} else if (e.key === 'Escape') {
			creatingIn.set(null);
		}
	}

	function getFileIconLetter(name: string): string {
		const ext = name.split('.').pop()?.toLowerCase() ?? '';
		const map: Record<string, string> = {
			ts: 'TS',
			tsx: 'TX',
			js: 'JS',
			jsx: 'JX',
			py: 'PY',
			rb: 'RB',
			rs: 'RS',
			go: 'GO',
			html: '<>',
			css: '#',
			scss: 'SC',
			json: '{}',
			yaml: 'YL',
			yml: 'YL',
			toml: 'TL',
			md: 'MD',
			mdx: 'MX',
			txt: 'TX',
			svg: 'SV',
			png: 'PN',
			jpg: 'JP',
			jpeg: 'JP',
			gif: 'GF',
			webp: 'WP',
			sh: 'SH',
			bash: 'SH',
			dockerfile: 'DK',
			svelte: 'SV',
			vue: 'VU',
			lock: 'LK',
			env: 'EN',
			sql: 'SQ',
			c: 'C',
			cpp: 'C+',
			h: 'H',
			java: 'JV',
			kt: 'KT',
			swift: 'SW',
			dart: 'DT',
			php: 'PH'
		};
		return map[ext] || ext.slice(0, 2).toUpperCase() || 'F';
	}

	function formatSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	let iconLetter = $derived(isDir ? null : getFileIconLetter(node.name));
	let menuItems = $derived(getContextMenuItems());
	let paddingLeft = $derived(`${depth * 12 + 10}px`);
</script>

<ContextMenu items={menuItems}>
	<button
		type="button"
		onclick={handleClick}
		class="flex w-full items-center gap-1.5 py-[5px] text-left text-[14px] transition-colors {isSelected
			? 'bg-border text-foreground'
			: 'text-foreground hover:bg-surface-2'}"
		style="padding-left: {paddingLeft}; padding-right: 10px;"
		data-testid="file-explorer-item"
		data-path={node.path}
		data-type={node.type}
	>
		{#if isDir}
			<!-- Chevron -->
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
				class="shrink-0 text-muted transition-transform {isExpanded ? 'rotate-90' : ''}"
			>
				<path d="m9 18 6-6-6-6" />
			</svg>
			<!-- Folder icon -->
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
				class="shrink-0 {isExpanded ? 'text-accent/80' : 'text-accent/60'}"
			>
				{#if isExpanded}
					<path
						d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"
					/>
				{:else}
					<path
						d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
					/>
				{/if}
			</svg>
			<span class="truncate font-medium">{node.name}</span>
		{:else if iconLetter}
			<!-- Spacer to align with directory chevron -->
			<span class="w-3 shrink-0"></span>
			<!-- File type badge -->
			<span
				class="inline-flex h-4 w-5 shrink-0 items-center justify-center rounded-[3px] bg-accent text-[7.5px] font-medium leading-none text-[--fg-on-accent]"
			>
				{iconLetter}
			</span>
			<span class="truncate">{node.name}</span>
			{#if node.size != null}
				<span class="ml-auto shrink-0 text-[10.5px] text-muted">
					{formatSize(node.size)}
				</span>
			{/if}
		{/if}
	</button>
</ContextMenu>

<!-- Expanded children -->
{#if isDir && isExpanded && node.children}
	<!-- Inline create input for this directory -->
	{#if creating && creating.parentPath === node.path}
		<div class="flex items-center gap-1.5 py-1" style="padding-left: {(depth + 1) * 12 + 10}px;">
			{#if creating.type === 'directory'}
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
					class="shrink-0 text-accent/70"
				>
					<path
						d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
					/>
				</svg>
			{:else}
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
					class="shrink-0 text-accent/40"
				>
					<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
					<path d="M14 2v4a2 2 0 0 0 2 2h4" />
				</svg>
			{/if}
			<input
				bind:this={newItemInput}
				type="text"
				bind:value={newItemName}
				onkeydown={handleNewItemKeydown}
				onblur={handleNewItemSubmit}
				placeholder={creating.type === 'directory' ? 'folder name' : 'file name'}
				class="min-w-0 flex-1 rounded border border-border-strong bg-background px-1.5 py-0.5 text-xs text-foreground outline-none focus:border-foreground"
			/>
		</div>
	{/if}

	{#each node.children as child (child.path)}
		<Self node={child} {conversationId} depth={depth + 1} />
	{/each}
{/if}
