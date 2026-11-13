<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import type { UserAddon, UserMCPConfig } from '$api/types';
	import type { SkillCatalog } from '$api/skills';

	interface Props {
		prompt: string;
		textareaEl: HTMLTextAreaElement | undefined;
		addons: UserAddon[];
		mcps: UserMCPConfig[];
		skills: SkillCatalog[];
		selectedAddonIds: SvelteSet<string>;
		selectedMCPIds: SvelteSet<string>;
		selectedSkillIds: SvelteSet<string>;
	}

	let {
		prompt = $bindable(),
		textareaEl,
		addons,
		mcps,
		skills,
		selectedAddonIds,
		selectedMCPIds,
		selectedSkillIds
	}: Props = $props();

	type MentionKind = 'addon' | 'mcp' | 'skill';

	interface MentionItem {
		kind: MentionKind;
		id: string;
		name: string;
		description?: string;
	}

	let open = $state(false);
	let query = $state('');
	let mentionStart = $state(-1);
	let selectedIndex = $state(0);

	let allItems = $derived.by<MentionItem[]>(() => {
		const list: MentionItem[] = [];
		for (const a of addons) {
			list.push({ kind: 'addon', id: a.id, name: a.enabled_addon.name });
		}
		for (const m of mcps) {
			list.push({ kind: 'mcp', id: m.id, name: m.server_name, description: m.description });
		}
		for (const s of skills) {
			list.push({ kind: 'skill', id: s.slug, name: s.name, description: s.description });
		}
		return list;
	});

	let filteredItems = $derived.by<MentionItem[]>(() => {
		if (!open) return [];
		const q = query.toLowerCase();
		const matches = q ? allItems.filter((it) => it.name.toLowerCase().includes(q)) : allItems;
		return matches.slice(0, 8);
	});

	function detectMention(): void {
		if (!textareaEl) {
			open = false;
			return;
		}
		const value = textareaEl.value;
		const cursor = textareaEl.selectionStart ?? value.length;
		const before = value.slice(0, cursor);
		const atPos = before.lastIndexOf('@');
		if (atPos < 0) {
			open = false;
			return;
		}
		const prevChar = atPos > 0 ? before[atPos - 1] : '';
		if (atPos > 0 && !/\s/.test(prevChar)) {
			open = false;
			return;
		}
		const q = before.slice(atPos + 1);
		if (/\s/.test(q)) {
			open = false;
			return;
		}
		mentionStart = atPos;
		query = q;
		if (!open) selectedIndex = 0;
		open = true;
	}

	function selectItem(item: MentionItem): void {
		if (mentionStart < 0 || !textareaEl) return;
		const cursor = textareaEl.selectionStart ?? prompt.length;
		const before = prompt.slice(0, mentionStart);
		const after = prompt.slice(cursor);
		const token = `@${item.name} `;
		prompt = before + token + after;

		if (item.kind === 'addon') selectedAddonIds.add(item.id);
		else if (item.kind === 'mcp') selectedMCPIds.add(item.id);
		else selectedSkillIds.add(item.id);

		open = false;
		mentionStart = -1;

		requestAnimationFrame(() => {
			if (!textareaEl) return;
			const newPos = before.length + token.length;
			textareaEl.setSelectionRange(newPos, newPos);
			textareaEl.focus();
		});
	}

	function onKeydown(e: KeyboardEvent): void {
		if (!open) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			open = false;
			return;
		}
		if (filteredItems.length === 0) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			e.stopPropagation();
			selectedIndex = (selectedIndex + 1) % filteredItems.length;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			e.stopPropagation();
			selectedIndex = (selectedIndex - 1 + filteredItems.length) % filteredItems.length;
		} else if (e.key === 'Enter' || e.key === 'Tab') {
			e.preventDefault();
			e.stopPropagation();
			selectItem(filteredItems[selectedIndex]);
		}
	}

	function onInputOrSelect(): void {
		detectMention();
	}

	function onBlur(): void {
		// Delay so click on dropdown item still fires.
		setTimeout(() => {
			open = false;
		}, 150);
	}

	$effect(() => {
		if (!textareaEl) return;
		const el = textareaEl;
		el.addEventListener('keydown', onKeydown, true);
		el.addEventListener('input', onInputOrSelect);
		el.addEventListener('keyup', onInputOrSelect);
		el.addEventListener('click', onInputOrSelect);
		el.addEventListener('focus', onInputOrSelect);
		el.addEventListener('blur', onBlur);
		return () => {
			el.removeEventListener('keydown', onKeydown, true);
			el.removeEventListener('input', onInputOrSelect);
			el.removeEventListener('keyup', onInputOrSelect);
			el.removeEventListener('click', onInputOrSelect);
			el.removeEventListener('focus', onInputOrSelect);
			el.removeEventListener('blur', onBlur);
		};
	});

	function kindBadgeClass(kind: MentionKind): string {
		if (kind === 'addon') return 'bg-accent/10 text-accent';
		if (kind === 'mcp') return 'bg-blue-500/10 text-blue-500';
		return 'bg-emerald-500/10 text-emerald-500';
	}
</script>

{#if open}
	<div
		class="absolute bottom-full left-0 z-50 mb-2 max-h-64 w-72 overflow-y-auto rounded-xl border border-border-subtle bg-surface-2 shadow-lg"
		role="listbox"
	>
		{#if filteredItems.length === 0}
			<div class="px-3 py-2 text-[11px] text-muted">
				{allItems.length === 0
					? 'No addons, MCPs, or skills installed yet.'
					: `No matches for "@${query}"`}
			</div>
		{/if}
		{#each filteredItems as item, i (item.kind + ':' + item.id)}
			<button
				type="button"
				onclick={() => selectItem(item)}
				onmouseenter={() => (selectedIndex = i)}
				class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors {i ===
				selectedIndex
					? 'bg-accent/10'
					: 'hover:bg-surface-2'}"
				role="option"
				aria-selected={i === selectedIndex}
			>
				<span
					class="shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide {kindBadgeClass(
						item.kind
					)}"
				>
					{item.kind}
				</span>
				<span class="min-w-0 flex-1">
					<span class="block truncate font-medium text-foreground">{item.name}</span>
					{#if item.description}
						<span class="block truncate text-[10px] text-muted">{item.description}</span>
					{/if}
				</span>
			</button>
		{/each}
	</div>
{/if}
