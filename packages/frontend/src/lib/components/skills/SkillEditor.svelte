<script lang="ts">
	import { goto } from '$app/navigation';
	import { Input, Textarea, LoadingSpinner } from '$components/ui';
	import { createFromEditor, updateMySkill, type UserSkillDetail } from '$api/user_skills';
	import { ApiClientError } from '$api/client';
	import { toasts } from '$stores/toast';

	type Props = {
		/** When provided, the editor opens in edit mode for an existing skill. */
		existing?: UserSkillDetail | null;
	};

	let { existing = null }: Props = $props();

	// ── Metadata ──
	let name = $state(existing?.name ?? '');
	let description = $state(existing?.description ?? '');
	let category = $state(existing?.category ?? '');
	let icon = $state(existing?.icon ?? '');

	// ── File state ──
	// Virtual "SKILL.md" holds the body only (front-matter is assembled on the
	// backend from the form fields). Supporting files are keyed by relative path.
	const SKILL_MD_KEY = 'SKILL.md';

	let body = $state(extractBody(existing?.skill_md_content ?? ''));
	let files: Record<string, string> = $state({ ...(existing?.skill_files ?? {}) });
	let selectedPath = $state<string>(SKILL_MD_KEY);

	let saving = $state(false);

	const isEditing = $derived(!!existing);

	const allPaths = $derived([
		SKILL_MD_KEY,
		...Object.keys(files).sort((a, b) => a.localeCompare(b))
	]);

	// Build a tree for display: nested folders → files
	type TreeNode = {
		name: string;
		path: string;
		kind: 'file' | 'dir';
		children: TreeNode[];
	};

	const tree = $derived(buildTree(allPaths));

	function buildTree(paths: string[]): TreeNode[] {
		const root: TreeNode = { name: '', path: '', kind: 'dir', children: [] };
		for (const p of paths) {
			const segments = p.split('/');
			let cur = root;
			for (let i = 0; i < segments.length; i++) {
				const seg = segments[i];
				const isFile = i === segments.length - 1;
				const fullPath = segments.slice(0, i + 1).join('/');
				let child = cur.children.find((c) => c.name === seg);
				if (!child) {
					child = {
						name: seg,
						path: fullPath,
						kind: isFile ? 'file' : 'dir',
						children: []
					};
					cur.children.push(child);
				}
				cur = child;
			}
		}
		// Sort: dirs first then files, alphabetical
		const sortNode = (n: TreeNode): void => {
			n.children.sort((a, b) => {
				if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1;
				return a.name.localeCompare(b.name);
			});
			n.children.forEach(sortNode);
		};
		sortNode(root);
		return root.children;
	}

	function extractBody(md: string): string {
		if (!md) return '';
		const lines = md.split('\n');
		if (lines[0]?.trim() !== '---') return md;
		for (let i = 1; i < lines.length; i++) {
			if (lines[i].trim() === '---') {
				return lines
					.slice(i + 1)
					.join('\n')
					.trim();
			}
		}
		return md;
	}

	function addFile(): void {
		const raw = prompt('New file path (e.g. scripts/helper.py, references/notes.md):');
		if (!raw) return;
		const clean = sanitizePath(raw);
		if (!clean) {
			toasts.error('Invalid path.');
			return;
		}
		if (clean === SKILL_MD_KEY || clean.toLowerCase() === 'skill.md') {
			toasts.error('SKILL.md is reserved.');
			return;
		}
		if (files[clean] !== undefined) {
			selectedPath = clean;
			return;
		}
		files = { ...files, [clean]: '' };
		selectedPath = clean;
	}

	function deleteSelected(): void {
		if (selectedPath === SKILL_MD_KEY) {
			toasts.error('SKILL.md cannot be deleted.');
			return;
		}
		if (!confirm(`Delete ${selectedPath}?`)) return;
		const next = { ...files };
		delete next[selectedPath];
		files = next;
		selectedPath = SKILL_MD_KEY;
	}

	function sanitizePath(raw: string): string {
		const trimmed = raw.trim().replace(/^\/+/, '');
		if (!trimmed) return '';
		const segments: string[] = [];
		for (const seg of trimmed.split('/')) {
			if (!seg || seg === '.') continue;
			if (seg === '..') return '';
			if (seg.startsWith('.')) return '';
			segments.push(seg);
		}
		return segments.join('/');
	}

	function currentContent(): string {
		return selectedPath === SKILL_MD_KEY ? body : (files[selectedPath] ?? '');
	}

	function updateCurrent(value: string): void {
		if (selectedPath === SKILL_MD_KEY) {
			body = value;
		} else {
			files = { ...files, [selectedPath]: value };
		}
	}

	async function save(): Promise<void> {
		if (!name.trim() || !description.trim() || !body.trim()) {
			toasts.error('Name, description, and SKILL.md body are required.');
			return;
		}
		saving = true;
		try {
			if (existing) {
				const updated = await updateMySkill(existing.id, {
					name: name.trim(),
					description: description.trim(),
					body: body.trim(),
					category: category.trim(),
					icon: icon.trim(),
					skill_files: files
				});
				toasts.success(`Saved ${updated.name}`);
				await goto('/skills');
			} else {
				const created = await createFromEditor({
					name: name.trim(),
					description: description.trim(),
					body: body.trim(),
					category: category.trim(),
					icon: icon.trim(),
					skill_files: files
				});
				toasts.success(`Created ${created.name}`);
				await goto('/skills');
			}
		} catch (e) {
			const msg = e instanceof ApiClientError ? e.message : 'Failed to save skill';
			toasts.error(msg);
		} finally {
			saving = false;
		}
	}
</script>

<div class="mx-auto flex w-full max-w-6xl flex-col px-4 pt-16 pb-6 sm:px-6 lg:px-8">
	<!-- Header -->
	<div class="mb-4 flex items-center justify-between gap-3">
		<div class="flex items-center gap-2.5">
			<button
				type="button"
				onclick={() => goto('/skills')}
				class="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-foreground"
				aria-label="Back"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d="m15 18-6-6 6-6" />
				</svg>
			</button>
			<h1 class="text-2xl font-normal tracking-tight text-foreground">
				{isEditing ? 'Edit skill' : 'New skill'}
			</h1>
		</div>
		<div class="flex gap-2">
			<button
				type="button"
				onclick={() => goto('/skills')}
				class="rounded-full border border-border px-4 py-1.5 text-sm text-subtle hover:border-border-strong"
			>
				Cancel
			</button>
			<button
				type="button"
				onclick={save}
				disabled={saving}
				class="rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
			>
				{#if saving}
					<LoadingSpinner size="xs" />
				{:else}
					{isEditing ? 'Save changes' : 'Create skill'}
				{/if}
			</button>
		</div>
	</div>

	<!-- Metadata -->
	<div class="mb-4 flex flex-col gap-3 rounded-xl border border-border-subtle bg-background p-4">
		<div class="grid grid-cols-[1fr_96px] gap-3">
			<Input bind:value={name} placeholder="Skill name" />
			<Input bind:value={icon} placeholder="📦" maxlength={4} />
		</div>
		<Input bind:value={description} placeholder="Short description" />
		<Input bind:value={category} placeholder="Category (optional, e.g. development)" />
	</div>

	<!-- Editor pane: file tree + content -->
	<div
		class="grid min-h-[480px] grid-cols-[240px_1fr] gap-0 overflow-hidden rounded-xl border border-border-subtle bg-background"
	>
		<!-- File tree -->
		<div class="flex flex-col border-r border-border-subtle bg-surface-2/30">
			<div class="flex items-center justify-between border-b border-border-subtle px-3 py-2">
				<span class="text-[11px] font-medium tracking-wide text-muted uppercase"> Files </span>
				<div class="flex gap-1">
					<button
						type="button"
						onclick={addFile}
						class="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-foreground"
						aria-label="Add file"
						title="Add file"
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
							<path d="M12 5v14" />
							<path d="M5 12h14" />
						</svg>
					</button>
					{#if selectedPath !== SKILL_MD_KEY}
						<button
							type="button"
							onclick={deleteSelected}
							class="rounded-md p-1 text-muted hover:bg-red-50 hover:text-red-500"
							aria-label="Delete selected file"
							title="Delete selected file"
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
								<path d="M3 6h18" />
								<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
								<path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
							</svg>
						</button>
					{/if}
				</div>
			</div>
			<div class="flex-1 overflow-auto py-1">
				{#each tree as node (node.path)}
					{@render treeNode(node, 0)}
				{/each}
			</div>
		</div>

		<!-- Content editor -->
		<div class="flex flex-col">
			<div class="flex items-center justify-between border-b border-border-subtle px-4 py-2">
				<span class="font-mono text-xs text-subtle">{selectedPath}</span>
				{#if selectedPath === SKILL_MD_KEY}
					<span class="text-[10px] text-muted">
						Front-matter is assembled from the metadata above.
					</span>
				{/if}
			</div>
			<Textarea
				value={currentContent()}
				oninput={(e) => updateCurrent((e.target as HTMLTextAreaElement).value)}
				placeholder={selectedPath === SKILL_MD_KEY
					? 'Write the SKILL.md body in Markdown...'
					: 'File content...'}
				rows={22}
				class="flex-1 rounded-none border-0 font-mono text-xs"
			/>
		</div>
	</div>
</div>

{#snippet treeNode(node: TreeNode, depth: number)}
	{@const isSelected = selectedPath === node.path}
	{#if node.kind === 'file'}
		<button
			type="button"
			onclick={() => (selectedPath = node.path)}
			class="flex w-full items-center gap-1.5 px-3 py-1 text-left font-mono text-xs transition-colors
				{isSelected ? 'bg-accent/10 text-accent' : 'text-subtle hover:bg-surface-2 hover:text-foreground'}"
			style="padding-left: {12 + depth * 12}px"
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
				class="shrink-0"
			>
				<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
				<polyline points="14 2 14 8 20 8" />
			</svg>
			<span class="truncate">{node.name}</span>
		</button>
	{:else}
		<div
			class="flex items-center gap-1.5 px-3 py-1 font-mono text-xs text-muted"
			style="padding-left: {12 + depth * 12}px"
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
				class="shrink-0"
			>
				<path
					d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
				/>
			</svg>
			<span class="truncate">{node.name}</span>
		</div>
		{#each node.children as child (child.path)}
			{@render treeNode(child, depth + 1)}
		{/each}
	{/if}
{/snippet}
