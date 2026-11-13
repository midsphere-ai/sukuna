<script lang="ts">
	import { searchConversations } from '$api/conversations';
	import { getConversationIcon, formatRelativeTime } from '$stores/conversations';
	import type { Conversation } from '$api/types';
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';

	type Props = {
		open: boolean;
	};

	let { open = $bindable(false) }: Props = $props();

	let query = $state('');
	let results = $state<Conversation[]>([]);
	let loading = $state(false);
	let searched = $state(false);
	let selectedIndex = $state(-1);
	let inputEl: HTMLInputElement | undefined = $state();
	let dialogEl: HTMLDialogElement | undefined = $state();
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;

	const RECENT_SEARCHES_KEY = 'midsphere-recent-searches';
	const MAX_RECENT = 5;

	function loadRecentSearches(): string[] {
		if (!browser) return [];
		try {
			const raw = localStorage.getItem(RECENT_SEARCHES_KEY);
			if (raw) return JSON.parse(raw) as string[];
		} catch {
			// ignore
		}
		return [];
	}

	function saveRecentSearch(term: string): void {
		if (!browser || !term.trim()) return;
		try {
			const existing = loadRecentSearches();
			const filtered = existing.filter((s) => s !== term);
			const updated = [term, ...filtered].slice(0, MAX_RECENT);
			localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
			recentSearches = updated;
		} catch {
			// ignore
		}
	}

	function clearRecentSearches(): void {
		if (!browser) return;
		try {
			localStorage.removeItem(RECENT_SEARCHES_KEY);
			recentSearches = [];
		} catch {
			// ignore
		}
	}

	let recentSearches = $state<string[]>(loadRecentSearches());
	let closing = $state(false);

	function close(): void {
		closing = true;
		setTimeout(() => {
			closing = false;
			open = false;
			query = '';
			results = [];
			searched = false;
			selectedIndex = -1;
			if (debounceTimer) clearTimeout(debounceTimer);
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
			return;
		}

		const itemCount = results.length || (query === '' ? recentSearches.length : 0);

		if (e.key === 'ArrowDown') {
			e.preventDefault();
			selectedIndex = selectedIndex < itemCount - 1 ? selectedIndex + 1 : 0;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selectedIndex = selectedIndex > 0 ? selectedIndex - 1 : itemCount - 1;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (results.length > 0 && selectedIndex >= 0) {
				navigateToResult(results[selectedIndex]);
			} else if (query === '' && recentSearches.length > 0 && selectedIndex >= 0) {
				query = recentSearches[selectedIndex];
				performSearch(query);
			}
		}
	}

	async function performSearch(searchQuery: string): Promise<void> {
		if (!searchQuery.trim()) {
			results = [];
			searched = false;
			return;
		}

		loading = true;
		searched = true;
		selectedIndex = -1;

		try {
			const response = await searchConversations(searchQuery);
			results = response.items;
		} catch {
			results = [];
		} finally {
			loading = false;
		}
	}

	function handleInput(): void {
		selectedIndex = -1;
		if (debounceTimer) clearTimeout(debounceTimer);

		if (!query.trim()) {
			results = [];
			searched = false;
			return;
		}

		debounceTimer = setTimeout(() => {
			performSearch(query);
		}, 300);
	}

	function navigateToResult(conversation: Conversation): void {
		saveRecentSearch(query);
		close();
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto(`/chat/${conversation.id}`);
	}

	function selectRecentSearch(term: string): void {
		query = term;
		performSearch(term);
	}

	function highlightMatch(text: string, term: string): string {
		if (!term.trim()) return escapeHtml(text);
		const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
		const regex = new RegExp(`(${escaped})`, 'gi');
		return escapeHtml(text).replace(
			regex,
			'<mark class="bg-accent/20 text-foreground rounded-sm px-0.5">$1</mark>'
		);
	}

	function escapeHtml(str: string): string {
		return str
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;');
	}

	function getStatusColor(status: string): string {
		switch (status) {
			case 'completed':
				return 'text-green';
			case 'running':
			case 'in_progress':
				return 'text-accent';
			case 'failed':
				return 'text-accent';
			default:
				return 'text-muted';
		}
	}

	$effect(() => {
		if (!dialogEl) return;
		if (open && !dialogEl.open) {
			dialogEl.showModal();
			recentSearches = loadRecentSearches();
			setTimeout(() => inputEl?.focus(), 0);
		} else if (!open && dialogEl.open) {
			dialogEl.close();
		}
	});
</script>

<dialog
	bind:this={dialogEl}
	class="search-dialog fixed inset-0 z-[10000] mx-auto mt-[12vh] mb-auto max-h-[70vh] w-full max-w-xl rounded-2xl border border-border-subtle bg-surface-2 p-0 shadow-xl backdrop:bg-foreground/40 open:flex open:flex-col"
	class:closing
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
>
	{#if open}
		<!-- Search input -->
		<div class="flex items-center gap-3 border-b border-border-subtle px-5 py-4">
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
				class="shrink-0 text-muted"
			>
				<circle cx="11" cy="11" r="8" />
				<path d="M21 21l-4.35-4.35" />
			</svg>
			<input
				bind:this={inputEl}
				bind:value={query}
				oninput={handleInput}
				type="text"
				placeholder="Search conversations..."
				class="flex-1 bg-transparent text-lg font-medium text-foreground outline-none placeholder:text-muted placeholder:font-normal"
				autocomplete="off"
				spellcheck="false"
			/>
			{#if loading}
				<div class="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-subtle"></div>
			{:else if query}
				<button
					onclick={() => {
						query = '';
						results = [];
						searched = false;
						selectedIndex = -1;
					}}
					class="rounded-md p-1 text-muted transition-colors hover:text-foreground"
					aria-label="Clear search"
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
						<path d="M18 6L6 18" /><path d="M6 6l12 12" />
					</svg>
				</button>
			{/if}
			<kbd
				class="hidden rounded border border-border px-1.5 py-0.5 text-[10px] text-muted sm:inline"
				>Esc</kbd
			>
		</div>

		<!-- Results area -->
		<div class="flex-1 overflow-y-auto">
			{#if searched && results.length > 0}
				<!-- Search results -->
				<ul class="py-1" role="listbox">
					{#each results as conversation, i (conversation.id)}
						<li role="option" aria-selected={i === selectedIndex}>
							<!-- eslint-disable svelte/no-navigation-without-resolve -->
							<button
								class="flex w-full items-center gap-3 px-5 py-2.5 text-left transition-all duration-150 hover:bg-surface {i ===
								selectedIndex
									? 'bg-surface-2'
									: ''}"
								onclick={() => navigateToResult(conversation)}
							>
								<img
									src={getConversationIcon(conversation.title || 'Untitled')}
									alt=""
									class="h-5 w-5 shrink-0 rounded opacity-60"
								/>
								<div class="min-w-0 flex-1">
									<!-- eslint-disable svelte/no-at-html-tags -- input sanitized via escapeHtml -->
									<p class="truncate text-sm font-medium text-foreground">
										{@html highlightMatch(conversation.title || 'Untitled', query)}
									</p>
									<!-- eslint-enable svelte/no-at-html-tags -->
									<div class="flex items-center gap-2 text-xs text-muted">
										<span class={getStatusColor(conversation.status)}>{conversation.status}</span>
										<span>·</span>
										<span
											>{formatRelativeTime(
												conversation.date_updated || conversation.date_created
											)}</span
										>
									</div>
								</div>
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
									<polyline points="9 18 15 12 9 6" />
								</svg>
							</button>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						</li>
					{/each}
				</ul>
			{:else if searched && !loading && query.trim()}
				<!-- No results -->
				<div class="flex flex-col items-center gap-2 px-4 py-10 text-center">
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
						class="text-muted"
					>
						<circle cx="11" cy="11" r="8" />
						<path d="M21 21l-4.35-4.35" />
						<path d="M8 11h6" />
					</svg>
					<p class="text-sm font-medium text-subtle">No results for "{query}"</p>
					<p class="text-xs text-muted">Try a different search term or check your spelling</p>
				</div>
			{:else if !searched && query === ''}
				<!-- Recent searches -->
				{#if recentSearches.length > 0}
					<div class="px-4 pt-3 pb-1">
						<div class="flex items-center justify-between">
							<span class="text-xs font-medium tracking-wide text-muted uppercase"
								>Recent searches</span
							>
							<button
								onclick={clearRecentSearches}
								class="text-xs text-muted transition-colors hover:text-accent"
							>
								Clear
							</button>
						</div>
					</div>
					<ul class="py-1" role="listbox">
						{#each recentSearches as term, i (term)}
							<li role="option" aria-selected={i === selectedIndex}>
								<button
									class="flex w-full items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-surface-2 {i ===
									selectedIndex
										? 'bg-surface-2'
										: ''}"
									onclick={() => selectRecentSearch(term)}
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
										class="shrink-0 text-muted"
									>
										<circle cx="12" cy="12" r="10" />
										<polyline points="12 6 12 12 16 14" />
									</svg>
									<span class="text-sm text-foreground">{term}</span>
								</button>
							</li>
						{/each}
					</ul>
				{:else}
					<div class="flex flex-col items-center gap-2 px-4 py-10 text-center">
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
							class="text-muted"
						>
							<circle cx="11" cy="11" r="8" />
							<path d="M21 21l-4.35-4.35" />
						</svg>
						<p class="text-sm text-muted">Search your conversations</p>
						<p class="text-xs text-muted">Type to search by title or content</p>
					</div>
				{/if}
			{/if}
		</div>

		<!-- Footer hint -->
		<div
			class="flex items-center gap-4 border-t border-border-subtle px-5 py-2.5 text-[11px] text-muted"
		>
			<span class="flex items-center gap-1">
				<kbd class="rounded border border-border px-1 py-0.5 font-mono">↑</kbd>
				<kbd class="rounded border border-border px-1 py-0.5 font-mono">↓</kbd>
				navigate
			</span>
			<span class="flex items-center gap-1">
				<kbd class="rounded border border-border px-1 py-0.5 font-mono">↵</kbd>
				select
			</span>
			<span class="flex items-center gap-1">
				<kbd class="rounded border border-border px-1 py-0.5 font-mono">esc</kbd>
				close
			</span>
		</div>
	{/if}
</dialog>

<style>
	.search-dialog[open] {
		animation: dialog-in 150ms ease-out;
	}

	.search-dialog[open]::backdrop {
		animation: backdrop-in 150ms ease-out;
	}

	.search-dialog.closing {
		animation: dialog-out 150ms ease-in forwards;
	}

	.search-dialog.closing::backdrop {
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
