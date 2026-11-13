<script lang="ts" module>
	function formatFileSize(chars: number): string {
		if (chars < 1024) return `${chars} B`;
		if (chars < 1024 * 1024) return `${(chars / 1024).toFixed(1)} KB`;
		return `${(chars / (1024 * 1024)).toFixed(1)} MB`;
	}

	/**
	 * Basic markdown-to-HTML converter for skill content.
	 * Handles headers, code blocks, bold, italic, lists, links.
	 */
	function markdownToHtml(md: string): string {
		if (!md) return '';
		// Remove front-matter
		const fmMatch = md.match(/^---\n[\s\S]*?\n---\n?/);
		if (fmMatch) md = md.slice(fmMatch[0].length);

		let html = md
			// Escape HTML
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			// Code blocks
			.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
			// Inline code
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			// Headers
			.replace(/^#### (.+)$/gm, '<h4>$1</h4>')
			.replace(/^### (.+)$/gm, '<h3>$1</h3>')
			.replace(/^## (.+)$/gm, '<h2>$1</h2>')
			.replace(/^# (.+)$/gm, '<h1>$1</h1>')
			// Bold + italic
			.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			.replace(/\*(.+?)\*/g, '<em>$1</em>')
			// Unordered lists
			.replace(/^- (.+)$/gm, '<li>$1</li>')
			// Links
			.replace(
				/\[([^\]]+)\]\(([^)]+)\)/g,
				'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
			)
			// Paragraphs (blank lines)
			.replace(/\n\n/g, '</p><p>')
			// Line breaks
			.replace(/\n/g, '<br>');

		// Wrap consecutive <li> in <ul>
		html = html.replace(/(<li>[\s\S]*?<\/li>(?:<br>)?)+/g, (match) => {
			return '<ul>' + match.replace(/<br>/g, '') + '</ul>';
		});

		return '<p>' + html + '</p>';
	}
</script>

<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { Skeleton, Badge, LoadingSpinner } from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import { getSkillDetail, installSkill, uninstallSkill, type SkillDetail } from '$api/skills';

	interface FileNode {
		name: string;
		path: string;
		type: 'file' | 'dir';
		children?: FileNode[];
	}

	let skill: SkillDetail | null = $state(null);
	let loading = $state(true);
	let installing = $state(false);
	let slug = $derived(page.params.slug ?? '');

	// Skill files state
	let filesExpanded = $state(false);
	let expandedDirs = $state<Set<string>>(new Set());
	let selectedFile = $state<string | null>(null);

	let skillFiles: Record<string, string> = $derived(
		(skill as SkillDetail | null)?.skill_files ?? {}
	);
	let fileTree: FileNode[] = $derived(
		Object.keys(skillFiles).length > 0 ? buildFileTree(skillFiles) : []
	);
	let fileCount: number = $derived(Object.keys(skillFiles).length);

	function buildFileTree(files: Record<string, string>): FileNode[] {
		const root: FileNode[] = [];
		const dirs = new Map<string, FileNode>();

		for (const filePath of Object.keys(files).sort()) {
			const parts = filePath.split('/');
			let currentChildren = root;

			for (let i = 0; i < parts.length; i++) {
				const part = parts[i];
				const dirPath = parts.slice(0, i + 1).join('/');

				if (i === parts.length - 1) {
					// File leaf
					currentChildren.push({ name: part, path: filePath, type: 'file' });
				} else {
					// Directory
					let dirNode = dirs.get(dirPath);
					if (!dirNode) {
						dirNode = { name: part, path: dirPath, type: 'dir', children: [] };
						dirs.set(dirPath, dirNode);
						currentChildren.push(dirNode);
					}
					currentChildren = dirNode.children!;
				}
			}
		}
		return root;
	}

	function toggleDir(path: string): void {
		const next = new Set(expandedDirs);
		if (next.has(path)) next.delete(path);
		else next.add(path);
		expandedDirs = next;
	}

	function selectFile(path: string): void {
		selectedFile = selectedFile === path ? null : path;
	}

	function getExtIcon(name: string): string {
		const ext = name.split('.').pop()?.toLowerCase() ?? '';
		const map: Record<string, string> = {
			ts: 'TS',
			tsx: 'TX',
			js: 'JS',
			jsx: 'JX',
			py: 'PY',
			sh: 'SH',
			bash: 'SH',
			md: 'MD',
			json: '{}',
			yaml: 'YL',
			yml: 'YL',
			toml: 'TL',
			html: '<>',
			css: '#',
			sql: 'SQ',
			rs: 'RS',
			go: 'GO',
			rb: 'RB',
			txt: 'TX',
			cfg: 'CF',
			ini: 'IN',
			xml: 'XL',
			csv: 'CV'
		};
		return map[ext] || ext.slice(0, 2).toUpperCase() || 'F';
	}

	function getLang(name: string): string {
		const ext = name.split('.').pop()?.toLowerCase() ?? '';
		const map: Record<string, string> = {
			ts: 'typescript',
			js: 'javascript',
			py: 'python',
			sh: 'bash',
			json: 'json',
			yaml: 'yaml',
			yml: 'yaml',
			md: 'markdown',
			html: 'html',
			css: 'css',
			sql: 'sql',
			rs: 'rust',
			go: 'go'
		};
		return map[ext] || ext;
	}

	async function load(): Promise<void> {
		loading = true;
		try {
			skill = await getSkillDetail(slug);
			pageTitle.set(skill.name);
		} catch {
			toasts.error('Failed to load skill');
			goto('/skills');
		} finally {
			loading = false;
		}
	}

	async function handleInstallToggle(): Promise<void> {
		if (!skill || installing) return;
		installing = true;
		try {
			if (skill.is_installed) {
				await uninstallSkill(skill.slug);
				skill.is_installed = false;
				skill.install_count = Math.max(0, skill.install_count - 1);
				toasts.success(`Uninstalled ${skill.name}`);
			} else {
				await installSkill(skill.slug);
				skill.is_installed = true;
				skill.install_count += 1;
				toasts.success(`Installed ${skill.name}`);
			}
		} catch {
			toasts.error(`Failed to ${skill.is_installed ? 'uninstall' : 'install'} ${skill.name}`);
		} finally {
			installing = false;
		}
	}

	onMount(() => {
		showHeaderTitle.set(false);
		load();
	});
</script>

<svelte:head>
	<title>{skill?.name ?? 'Skill'} - Jatayu AI</title>
</svelte:head>

<div class="mx-auto flex w-full max-w-4xl flex-col px-4 pt-16 pb-6 sm:px-6 lg:px-8">
	<!-- Back link -->
	<button
		onclick={() => goto('/skills')}
		class="mb-6 flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-foreground"
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
			<path d="M19 12H5" />
			<path d="M12 19l-7-7 7-7" />
		</svg>
		Back to Skills
	</button>

	{#if loading}
		<div class="space-y-4">
			<Skeleton width="60%" height="28px" />
			<Skeleton width="80%" height="16px" />
			<Skeleton width="100%" height="300px" />
		</div>
	{:else if skill}
		<!-- Header -->
		<div class="mb-6 flex items-start gap-4">
			<div
				class="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl border border-border-subtle bg-surface-2 text-2xl"
			>
				{skill.icon || '📦'}
			</div>
			<div class="flex-1">
				<div class="flex items-center gap-2">
					<h1 class="text-2xl font-medium text-foreground">{skill.name}</h1>
					{#if skill.source_type === 'official'}
						<Badge variant="green">Official</Badge>
					{/if}
				</div>
				<p class="mt-1 text-sm text-subtle">{skill.description}</p>

				<!-- Meta row -->
				<div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted">
					{#if skill.author}
						<span>by {skill.author}</span>
					{/if}
					{#if skill.category}
						<span class="rounded-full bg-surface px-2 py-0.5 text-[10px] font-medium text-muted"
							>{skill.category}</span
						>
					{/if}
					{#if skill.version}
						<span>v{skill.version}</span>
					{/if}
					{#if skill.license}
						<span>{skill.license}</span>
					{/if}
					<span>{skill.install_count.toLocaleString()} installs</span>
					{#if skill.has_scripts}
						<span class="rounded-full bg-amber-50 px-2 py-0.5 text-amber-600">scripts</span>
					{/if}
					{#if skill.has_templates}
						<span class="rounded-full bg-blue-50 px-2 py-0.5 text-blue-600">templates</span>
					{/if}
				</div>
			</div>

			<!-- Install button -->
			<button
				onclick={handleInstallToggle}
				disabled={installing}
				class="shrink-0 rounded-xl px-5 py-2.5 text-sm font-medium transition-colors {skill.is_installed
					? 'bg-success/10 text-success hover:bg-red-50 hover:text-red-500'
					: 'bg-accent text-white hover:bg-accent/90'} disabled:opacity-50"
			>
				{#if installing}
					<LoadingSpinner size="sm" />
				{:else if skill.is_installed}
					Installed
				{:else}
					Install
				{/if}
			</button>
		</div>

		<!-- Source info -->
		{#if skill.source_repo}
			<div class="mb-6 rounded-xl border border-border-subtle bg-surface-2/50 px-4 py-3">
				<div class="flex items-center gap-2 text-xs text-muted">
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
						<path
							d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"
						/>
						<path d="M9 18c-4.51 2-5-2-7-2" />
					</svg>
					<a
						href="https://github.com/{skill.source_repo}"
						target="_blank"
						rel="noopener noreferrer"
						class="hover:text-foreground hover:underline"
					>
						{skill.source_repo}
					</a>
					{#if skill.source_path}
						<span class="text-muted">/</span>
						<span>{skill.source_path}</span>
					{/if}
				</div>
			</div>
		{/if}

		<!-- SKILL.md content -->
		<div
			class="prose prose-sm max-w-none rounded-xl border border-border-subtle bg-background p-6 text-foreground prose-headings:text-foreground prose-code:rounded prose-code:bg-surface prose-code:px-1.5 prose-code:py-0.5 prose-code:text-foreground prose-pre:bg-surface"
		>
			{@html markdownToHtml(skill.skill_md_content)}
		</div>

		<!-- Skill Files -->
		{#if fileCount > 0}
			<div class="mt-6 overflow-hidden rounded-xl border border-border-subtle">
				<!-- Toggle header -->
				<button
					onclick={() => (filesExpanded = !filesExpanded)}
					class="flex w-full items-center gap-2 bg-surface-2/50 px-4 py-3 text-left text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
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
						class="shrink-0 transition-transform {filesExpanded ? 'rotate-90' : ''}"
					>
						<path d="m9 18 6-6-6-6" />
					</svg>
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
						class="shrink-0 text-muted"
					>
						<path
							d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
						/>
					</svg>
					Included Files
					<span class="rounded-full bg-surface px-2 py-0.5 text-[10px] font-medium text-muted"
						>{fileCount}</span
					>
				</button>

				{#if filesExpanded}
					<div class="border-t border-border-subtle bg-background">
						<!-- File tree -->
						<div class="py-1">
							{#snippet renderNode(node: FileNode, depth: number)}
								{#if node.type === 'dir'}
									<button
										onclick={() => toggleDir(node.path)}
										class="flex w-full items-center gap-1.5 py-[5px] text-left text-xs text-foreground transition-colors hover:bg-surface-2"
										style="padding-left: {depth * 16 + 12}px;"
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
											class="shrink-0 text-muted transition-transform {expandedDirs.has(node.path)
												? 'rotate-90'
												: ''}"
										>
											<path d="m9 18 6-6-6-6" />
										</svg>
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
											class="shrink-0 {expandedDirs.has(node.path)
												? 'text-accent/80'
												: 'text-accent/60'}"
										>
											{#if expandedDirs.has(node.path)}
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
									</button>
									{#if expandedDirs.has(node.path) && node.children}
										{#each node.children as child (child.path)}
											{@render renderNode(child, depth + 1)}
										{/each}
									{/if}
								{:else}
									<button
										onclick={() => selectFile(node.path)}
										class="flex w-full items-center gap-1.5 py-[5px] text-left text-xs transition-colors {selectedFile ===
										node.path
											? 'bg-surface text-foreground'
											: 'text-foreground hover:bg-surface-2'}"
										style="padding-left: {depth * 16 + 12 + 16}px;"
									>
										<span
											class="inline-flex h-4 w-5 shrink-0 items-center justify-center rounded-[3px] bg-accent text-[7px] font-medium leading-none text-[--fg-on-accent]"
										>
											{getExtIcon(node.name)}
										</span>
										<span class="truncate">{node.name}</span>
										{#if skillFiles[node.path]}
											<span class="ml-auto shrink-0 text-[10px] text-muted">
												{formatFileSize(skillFiles[node.path].length)}
											</span>
										{/if}
									</button>
								{/if}
							{/snippet}

							{#each fileTree as node (node.path)}
								{@render renderNode(node, 0)}
							{/each}
						</div>

						<!-- Selected file content -->
						{#if selectedFile && skillFiles[selectedFile]}
							<div class="border-t border-border-subtle">
								<div class="flex items-center justify-between bg-surface-2/50 px-4 py-2 text-xs">
									<span class="font-medium text-foreground">{selectedFile}</span>
									<button
										onclick={() => (selectedFile = null)}
										aria-label="Close file preview"
										class="text-muted transition-colors hover:text-foreground"
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
											<path d="M18 6 6 18" />
											<path d="m6 6 12 12" />
										</svg>
									</button>
								</div>
								<pre
									class="max-h-[500px] overflow-auto bg-surface p-4 text-xs leading-relaxed text-foreground"><code
										class="language-{getLang(selectedFile)}">{skillFiles[selectedFile]}</code
									></pre>
							</div>
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	{/if}
</div>
