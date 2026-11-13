<script lang="ts">
	import Self from './JsonViewer.svelte';

	type Props = {
		value: unknown;
		depth?: number;
		collapseDepth?: number;
		maxInlineLength?: number;
		rootKey?: string;
	};

	let { value, depth = 0, collapseDepth = 1, maxInlineLength = 80, rootKey }: Props = $props();

	// svelte-ignore state_referenced_locally
	// Initial open state is derived from depth once on construction; later toggles are user-driven.
	let open = $state(depth < collapseDepth);

	let kind = $derived.by<
		'null' | 'undefined' | 'boolean' | 'number' | 'string' | 'array' | 'object' | 'other'
	>(() => {
		if (value === null) return 'null';
		if (typeof value === 'undefined') return 'undefined';
		if (typeof value === 'boolean') return 'boolean';
		if (typeof value === 'number') return 'number';
		if (typeof value === 'string') return 'string';
		if (Array.isArray(value)) return 'array';
		if (typeof value === 'object') return 'object';
		return 'other';
	});

	let stringIsInline = $derived(
		kind === 'string' &&
			(value as string).length <= maxInlineLength &&
			!(value as string).includes('\n')
	);

	let objectEntries = $derived.by(() => {
		if (kind !== 'object') return [];
		return Object.entries(value as Record<string, unknown>);
	});

	let arrayItems = $derived.by(() => {
		if (kind !== 'array') return [];
		return value as unknown[];
	});

	function toggle(): void {
		open = !open;
	}
</script>

{#if kind === 'null'}
	<span class="text-muted">null</span>
{:else if kind === 'undefined'}
	<span class="text-muted">undefined</span>
{:else if kind === 'boolean'}
	<span class="text-accent">{String(value)}</span>
{:else if kind === 'number'}
	<span class="text-accent">{String(value)}</span>
{:else if kind === 'string'}
	{#if stringIsInline}
		<span class="text-success whitespace-pre-wrap break-words">"{value}"</span>
	{:else}
		<button
			type="button"
			onclick={toggle}
			class="inline-flex items-center gap-1 text-left text-success hover:text-foreground"
		>
			<span class="font-mono text-[10px] text-subtle">{open ? '▾' : '▸'}</span>
			<span class="truncate"
				>"{(value as string).slice(0, 40).replace(/\n/g, '\\n')}{(value as string).length > 40
					? '…'
					: ''}"</span
			>
			<span class="text-[10px] text-subtle">({(value as string).length} chars)</span>
		</button>
		{#if open}
			<pre
				class="ml-4 mt-1 whitespace-pre-wrap break-words rounded bg-surface-2/60 p-1.5 text-[11px] text-success">{value}</pre>
		{/if}
	{/if}
{:else if kind === 'array'}
	{#if arrayItems.length === 0}
		<span class="text-muted">[]</span>
	{:else}
		<button
			type="button"
			onclick={toggle}
			class="inline-flex items-center gap-1 text-left text-subtle hover:text-foreground"
		>
			<span class="font-mono text-[10px]">{open ? '▾' : '▸'}</span>
			<span>Array ({arrayItems.length})</span>
		</button>
		{#if open}
			<ul class="ml-2 border-l border-border-subtle pl-2">
				{#each arrayItems as item, i (i)}
					<li class="flex gap-2 py-0.5">
						<span class="font-mono text-[10px] text-subtle">{i}:</span>
						<div class="min-w-0 flex-1">
							<Self value={item} depth={depth + 1} {collapseDepth} {maxInlineLength} />
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
{:else if kind === 'object'}
	{#if objectEntries.length === 0}
		<span class="text-muted">{'{}'}</span>
	{:else}
		<button
			type="button"
			onclick={toggle}
			class="inline-flex items-center gap-1 text-left text-subtle hover:text-foreground"
		>
			<span class="font-mono text-[10px]">{open ? '▾' : '▸'}</span>
			<span>{rootKey ? rootKey : 'Object'} ({objectEntries.length})</span>
		</button>
		{#if open}
			<ul class="ml-2 border-l border-border-subtle pl-2">
				{#each objectEntries as [key, val] (key)}
					<li class="flex gap-2 py-0.5">
						<span class="font-mono text-[10px] text-foreground">{key}:</span>
						<div class="min-w-0 flex-1">
							<Self value={val} depth={depth + 1} {collapseDepth} {maxInlineLength} />
						</div>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
{:else}
	<span class="text-muted">{String(value)}</span>
{/if}
