<script lang="ts">
	import { onDestroy } from 'svelte';
	import { marked } from 'marked';
	import { infoTutorials, loadTutorialContent } from '$stores/infoTutorials';
	import type { Tutorial } from '$api/types';

	interface Props {
		/** Context keyword to match against tutorial title/subtitle */
		context: string;
		/** Size of the icon button (default 'sm') */
		size?: 'sm' | 'md';
	}

	let { context, size = 'sm' }: Props = $props();

	let tutorial: Tutorial | undefined = $state();
	let open = $state(false);
	let loading = $state(false);
	let content = $state('');
	let popoverEl: HTMLDivElement | undefined = $state();
	let buttonEl: HTMLButtonElement | undefined = $state();

	// Find matching tutorial from store
	const unsub = infoTutorials.subscribe((tutorials) => {
		const lower = context.toLowerCase();
		tutorial = tutorials.find(
			(t) =>
				t.title.toLowerCase().includes(lower) ||
				(t.subtitle && t.subtitle.toLowerCase().includes(lower))
		);
	});

	onDestroy(() => {
		unsub();
		removeListeners();
	});

	async function togglePopover(): Promise<void> {
		if (open) {
			open = false;
			removeListeners();
			return;
		}
		open = true;
		addListeners();

		if (!content && tutorial) {
			loading = true;
			const md = await loadTutorialContent(tutorial.title);
			if (md) {
				content = marked.parse(md, { async: false, breaks: true, gfm: true }) as string;
			}
			loading = false;
		}
	}

	function handleClickOutside(e: MouseEvent): void {
		if (
			popoverEl &&
			!popoverEl.contains(e.target as Node) &&
			buttonEl &&
			!buttonEl.contains(e.target as Node)
		) {
			open = false;
			removeListeners();
		}
	}

	function handleEscape(e: KeyboardEvent): void {
		if (e.key === 'Escape' && open) {
			open = false;
			removeListeners();
		}
	}

	function addListeners(): void {
		document.addEventListener('click', handleClickOutside, true);
		document.addEventListener('keydown', handleEscape);
	}

	function removeListeners(): void {
		document.removeEventListener('click', handleClickOutside, true);
		document.removeEventListener('keydown', handleEscape);
	}

	let sizeClasses = $derived(size === 'md' ? 'h-6 w-6' : 'h-5 w-5');
	let iconSize = $derived(size === 'md' ? 14 : 12);
</script>

{#if tutorial}
	<span class="relative inline-flex">
		<button
			bind:this={buttonEl}
			onclick={togglePopover}
			class="inline-flex {sizeClasses} items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-subtle"
			aria-label="Help: {tutorial.title}"
			aria-expanded={open}
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width={iconSize}
				height={iconSize}
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<circle cx="12" cy="12" r="10" />
				<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
				<path d="M12 17h.01" />
			</svg>
		</button>

		{#if open}
			<div
				bind:this={popoverEl}
				class="popover-animate absolute left-1/2 z-50 w-72 -translate-x-1/2 rounded-xl border border-border-subtle bg-surface-2 shadow-sm sm:w-80"
				class:bottom-full={true}
				class:mb-2={true}
				role="tooltip"
			>
				<div class="border-b border-border-subtle px-4 py-3">
					<h4 class="text-sm font-medium text-foreground">{tutorial.title}</h4>
					{#if tutorial.subtitle}
						<p class="mt-0.5 text-xs text-subtle">{tutorial.subtitle}</p>
					{/if}
				</div>
				<div class="max-h-64 overflow-y-auto px-4 py-3">
					{#if loading}
						<div class="flex items-center justify-center py-6">
							<svg
								class="h-5 w-5 animate-spin text-muted"
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
							>
								<circle
									class="opacity-25"
									cx="12"
									cy="12"
									r="10"
									stroke="currentColor"
									stroke-width="4"
								></circle>
								<path
									class="opacity-75"
									fill="currentColor"
									d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
								></path>
							</svg>
						</div>
					{:else if content}
						<div
							class="prose prose-sm max-w-none text-foreground [&_a]:text-accent [&_a]:underline [&_code]:rounded [&_code]:bg-surface [&_code]:px-1 [&_code]:text-xs [&_h1]:text-sm [&_h2]:text-sm [&_h3]:text-xs [&_li]:text-xs [&_p]:text-xs [&_p]:leading-relaxed [&_ul]:pl-4"
						>
							<!-- eslint-disable-next-line svelte/no-at-html-tags -->
							{@html content}
						</div>
					{:else}
						<p class="text-xs text-muted">No content available.</p>
					{/if}
				</div>
			</div>
		{/if}
	</span>
{/if}

<style>
	.popover-animate {
		animation: popover-in 150ms ease-out;
	}
	@keyframes popover-in {
		from {
			opacity: 0;
			transform: translateX(-50%) scale(0.95) translateY(4px);
		}
		to {
			opacity: 1;
			transform: translateX(-50%) scale(1) translateY(0);
		}
	}
</style>
