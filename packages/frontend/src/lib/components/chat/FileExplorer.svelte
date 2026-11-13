<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { FileTreeNode } from '$api/sandbox';
	import {
		fileTree,
		fileTreeLoading,
		creatingIn,
		loadFileTree,
		createFileOrFolder
	} from '$stores/fileExplorer';
	import FileTreeNodeComponent from './FileTreeNode.svelte';
	import { tooltip } from '$lib/actions/tooltip';

	type Props = {
		conversationId: string;
	};

	let { conversationId }: Props = $props();

	let tree: FileTreeNode[] = $state([]);
	let loading = $state(false);
	let creating: { parentPath: string; type: 'file' | 'directory' } | null = $state(null);
	let newItemName = $state('');
	let newItemInput: HTMLInputElement | undefined = $state();
	let searchQuery = $state('');
	let searchVisible = $state(false);

	const unsubTree = fileTree.subscribe((v) => (tree = v));
	const unsubLoading = fileTreeLoading.subscribe((v) => (loading = v));
	const unsubCreating = creatingIn.subscribe((v) => {
		creating = v;
		if (v && v.parentPath === '.') {
			newItemName = '';
			requestAnimationFrame(() => newItemInput?.focus());
		}
	});

	onMount(() => {
		loadFileTree(conversationId);
	});

	onDestroy(() => {
		unsubTree();
		unsubLoading();
		unsubCreating();
	});

	// Search/filter
	function matchesSearch(node: FileTreeNode, query: string): boolean {
		if (!query) return true;
		const q = query.toLowerCase();
		if (node.name.toLowerCase().includes(q)) return true;
		if (node.type === 'directory' && node.children) {
			return node.children.some((child) => matchesSearch(child, q));
		}
		return false;
	}

	let filteredTree = $derived.by(() => {
		if (!searchQuery) return tree;
		function filterNodes(nodes: FileTreeNode[]): FileTreeNode[] {
			return nodes
				.filter((n) => matchesSearch(n, searchQuery))
				.map((n) => {
					if (n.type === 'directory' && n.children) {
						return { ...n, children: filterNodes(n.children) };
					}
					return n;
				});
		}
		return filterNodes(tree);
	});

	function handleRootNewFile(): void {
		creatingIn.set({ parentPath: '.', type: 'file' });
	}

	function handleRootNewFolder(): void {
		creatingIn.set({ parentPath: '.', type: 'directory' });
	}

	async function handleNewItemSubmit(): Promise<void> {
		if (!creating || creating.parentPath !== '.' || !newItemName.trim()) {
			if (creating?.parentPath === '.') creatingIn.set(null);
			return;
		}
		await createFileOrFolder(conversationId, '.', newItemName.trim(), creating.type);
		creatingIn.set(null);
	}

	function handleNewItemKeydown(e: KeyboardEvent): void {
		if (e.key === 'Enter') {
			handleNewItemSubmit();
		} else if (e.key === 'Escape') {
			creatingIn.set(null);
		}
	}
</script>

<div class="flex h-full flex-col" data-testid="file-explorer">
	<!-- Toolbar -->
	<div
		class="flex items-center justify-between border-b border-border px-2.5 py-1.5"
		data-testid="file-explorer-toolbar"
	>
		<span class="text-[11.5px] font-medium uppercase tracking-wider text-muted">Files</span>
		<div class="flex items-center gap-0.5">
			<button
				type="button"
				onclick={() => (searchVisible = !searchVisible)}
				class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
				aria-label="Search files"
				use:tooltip={'Search files'}
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
					<circle cx="11" cy="11" r="8" />
					<path d="m21 21-4.3-4.3" />
				</svg>
			</button>
			<button
				type="button"
				onclick={handleRootNewFile}
				class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
				aria-label="New file"
				use:tooltip={'New file'}
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
					<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
					<path d="M14 2v4a2 2 0 0 0 2 2h4" />
					<path d="M12 18v-6" />
					<path d="M9 15h6" />
				</svg>
			</button>
			<button
				type="button"
				onclick={handleRootNewFolder}
				class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
				aria-label="New folder"
				use:tooltip={'New folder'}
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
					<path
						d="M12 10v6M9 13h6M2 7l1.4-2.1A2 2 0 0 1 5.06 4h3.88a2 2 0 0 1 1.66.9L12 7h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Z"
					/>
				</svg>
			</button>
			<button
				type="button"
				onclick={() => loadFileTree(conversationId)}
				class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
				aria-label="Refresh"
				use:tooltip={'Refresh'}
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
					<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
					<path d="M3 3v5h5" />
					<path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
					<path d="M16 16h5v5" />
				</svg>
			</button>
		</div>
	</div>

	<!-- Search bar -->
	{#if searchVisible}
		<div class="border-b border-border px-2.5 py-1.5">
			<input
				type="text"
				bind:value={searchQuery}
				placeholder="Search files..."
				class="w-full rounded-md border border-border-strong bg-surface px-2 py-1 text-xs text-foreground outline-none placeholder:text-muted focus:border-foreground"
			/>
		</div>
	{/if}

	<!-- Tree content -->
	<div class="min-h-0 flex-1 overflow-auto" data-testid="file-explorer-tree">
		{#if loading && tree.length === 0}
			<div class="flex items-center justify-center py-8">
				<div class="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-subtle"></div>
			</div>
		{:else if filteredTree.length === 0}
			<div class="px-3 py-8 text-center text-xs text-muted italic">
				{#if searchQuery}
					No matching files
				{:else}
					No files yet
				{/if}
			</div>
		{:else}
			<!-- Root-level new item input -->
			{#if creating && creating.parentPath === '.'}
				<div class="flex items-center gap-1.5 px-2.5 py-1">
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

			{#each filteredTree as node (node.path)}
				<FileTreeNodeComponent {node} {conversationId} depth={0} />
			{/each}
		{/if}
	</div>
</div>
