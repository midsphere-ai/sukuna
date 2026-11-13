<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';
	import { parseEnvelope, formatBytes } from './_shared';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface FileEntry {
		name: string;
		isDir: boolean;
		size?: number;
	}

	let envelope = $derived(parseEnvelope(toolCall.result));
	let isError = $derived(envelope.success === false);
	let isFind = $derived(toolCall.toolName === 'find' || toolCall.toolName === 'match');

	let rawPath = $derived(
		(typeof toolCall.args?.path === 'string'
			? (toolCall.args.path as string)
			: typeof toolCall.args?.scope === 'string'
				? (toolCall.args.scope as string)
				: typeof toolCall.args?.directory === 'string'
					? (toolCall.args.directory as string)
					: '') ?? ''
	);
	let globPattern = $derived(
		typeof toolCall.args?.pattern === 'string' ? (toolCall.args.pattern as string) : ''
	);

	let resultObj = $derived(
		toolCall.result && typeof toolCall.result === 'object' && !Array.isArray(toolCall.result)
			? (toolCall.result as Record<string, unknown>)
			: {}
	);

	let entries: FileEntry[] = $derived.by(() => {
		const r = toolCall.result;
		const toEntries = (raw: unknown[]): FileEntry[] =>
			raw
				.map((e) => {
					if (typeof e === 'string') {
						const isDir = e.endsWith('/');
						const cleaned = isDir ? e.slice(0, -1) : e;
						return { name: cleaned, isDir };
					}
					if (e && typeof e === 'object') {
						const obj = e as Record<string, unknown>;
						const name = typeof obj.name === 'string' ? (obj.name as string) : '';
						const type = typeof obj.type === 'string' ? (obj.type as string) : '';
						const isDir =
							type === 'directory' ||
							type === 'dir' ||
							(typeof obj.is_dir === 'boolean' && obj.is_dir);
						return {
							name,
							isDir,
							size: typeof obj.size === 'number' ? (obj.size as number) : undefined
						};
					}
					return { name: String(e), isDir: false };
				})
				.filter((e) => e.name);

		if (Array.isArray(r)) return toEntries(r);
		if (Array.isArray(resultObj.files)) return toEntries(resultObj.files as unknown[]);
		if (Array.isArray(resultObj.matches)) return toEntries(resultObj.matches as unknown[]);
		if (typeof r === 'string') {
			return r
				.split('\n')
				.filter((line) => line.trim() !== '')
				.map((line) => ({ name: line.replace(/\/$/, ''), isDir: line.endsWith('/') }));
		}
		return [];
	});

	let sorted = $derived(
		[...entries].sort((a, b) => {
			if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
			return a.name.localeCompare(b.name);
		})
	);
	let dirCount = $derived(sorted.filter((e) => e.isDir).length);
	let fileCount = $derived(sorted.length - dirCount);
</script>

<div data-testid="file-tree-renderer">
	<!-- Header -->
	<div class="mb-2 flex items-center justify-between gap-2">
		<div class="flex min-w-0 items-center gap-2 text-xs text-subtle">
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
				class="shrink-0"
			>
				{#if isFind}
					<circle cx="11" cy="11" r="8" />
					<path d="m21 21-4.3-4.3" />
				{:else}
					<path
						d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
					/>
				{/if}
			</svg>
			<span
				class="truncate font-mono text-[11px] text-foreground"
				title={rawPath || globPattern}
				data-testid="file-tree-path"
			>
				{globPattern || rawPath || '.'}
			</span>
		</div>

		<div class="flex shrink-0 items-center gap-2">
			{#if isError}
				<span
					class="rounded bg-accent/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-accent"
				>
					error
				</span>
			{:else if sorted.length > 0}
				<span class="font-mono text-[10px] text-subtle">
					{#if dirCount > 0}
						<span data-testid="file-tree-dir-count"
							>{dirCount} folder{dirCount === 1 ? '' : 's'}</span
						>
					{/if}
					{#if dirCount > 0 && fileCount > 0}
						<span class="mx-0.5">·</span>
					{/if}
					{#if fileCount > 0}
						<span data-testid="file-tree-file-count"
							>{fileCount} file{fileCount === 1 ? '' : 's'}</span
						>
					{/if}
				</span>
			{/if}
		</div>
	</div>

	{#if isError}
		<div class="rounded-lg border border-accent/30 bg-accent/5 px-3 py-2">
			<div class="font-mono text-[10px] font-medium uppercase text-accent">
				{envelope.error ?? 'error'}
			</div>
			{#if envelope.message}
				<div class="mt-1 text-[11px] text-foreground">{envelope.message}</div>
			{/if}
			{#if envelope.hint}
				<div class="mt-1 text-[10px] italic text-muted">hint: {envelope.hint}</div>
			{/if}
		</div>
	{:else if sorted.length > 0}
		<div
			class="overflow-hidden rounded-lg border border-border-subtle bg-background"
			data-testid="file-tree-content"
		>
			<div class="max-h-[400px] overflow-auto" data-testid="file-tree-list">
				{#each sorted as entry, i (i + ':' + entry.name)}
					<div
						class="flex items-center gap-2 border-b border-border-subtle px-3 py-1.5 text-xs transition-colors last:border-b-0 hover:bg-surface-2"
						data-testid="file-tree-item"
						data-is-dir={entry.isDir}
					>
						{#if entry.isDir}
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
								class="shrink-0 text-accent"
							>
								<path
									d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
								/>
							</svg>
							<span class="font-mono text-foreground" data-testid="file-tree-name"
								>{entry.name}/</span
							>
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
								class="shrink-0 text-subtle"
							>
								<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
								<path d="M14 2v4a2 2 0 0 0 2 2h4" />
							</svg>
							<span class="font-mono text-muted" data-testid="file-tree-name">{entry.name}</span>
						{/if}
						{#if entry.size !== undefined}
							<span class="ml-auto shrink-0 font-mono text-[10px] text-subtle">
								{formatBytes(entry.size)}
							</span>
						{/if}
					</div>
				{/each}
			</div>
		</div>
	{:else}
		<div
			class="rounded-lg border border-border-subtle bg-background px-3 py-4 text-center text-xs italic text-subtle"
			data-testid="file-tree-empty"
		>
			{isFind ? 'No matches' : 'Empty directory'}
		</div>
	{/if}
</div>
