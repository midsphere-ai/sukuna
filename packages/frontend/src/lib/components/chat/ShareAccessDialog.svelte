<script lang="ts">
	import { Dialog } from '$components/ui';
	import { shareConversation, unshareConversation } from '$api/conversations';
	import { toasts } from '$stores/toast';

	type Props = {
		open: boolean;
		conversationId: string;
		isShared: boolean;
		onsharedchange?: (shared: boolean) => void;
	};

	let { open = $bindable(false), conversationId, isShared, onsharedchange }: Props = $props();

	let pending = $state(false);
	// eslint-disable-next-line svelte/prefer-writable-derived -- sharedState is written in setAccess(), not purely derived
	let sharedState = $state(false);
	let copied = $state(false);

	$effect(() => {
		sharedState = isShared;
	});

	$effect(() => {
		if (open) copied = false;
	});

	let shareUrl = $derived.by(() => {
		if (!conversationId || typeof window === 'undefined') return '';
		return `${window.location.origin}/shared/${conversationId}`;
	});

	function closeDialog(): void {
		open = false;
	}

	async function handleCopyLink(): Promise<void> {
		if (!sharedState) {
			toasts.warning('Make this conversation public before copying the link');
			return;
		}

		if (!shareUrl || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
			toasts.error('Clipboard is not available');
			return;
		}

		try {
			await navigator.clipboard.writeText(shareUrl);
			copied = true;
			toasts.success('Share link copied to clipboard');
			setTimeout(() => (copied = false), 2000);
		} catch {
			toasts.error('Failed to copy share link');
		}
	}

	async function setAccess(shared: boolean): Promise<void> {
		if (!conversationId || pending || sharedState === shared) return;

		pending = true;
		try {
			if (shared) {
				await shareConversation(conversationId);
			} else {
				await unshareConversation(conversationId);
			}
			sharedState = shared;
			onsharedchange?.(shared);
			toasts.success(shared ? 'Conversation is now public' : 'Conversation is now private');
		} catch {
			toasts.error(
				shared ? 'Failed to make conversation public' : 'Failed to make conversation private'
			);
		} finally {
			pending = false;
		}
	}
</script>

<Dialog bind:open class="max-w-sm" aria-label="Share conversation">
	<div class="p-5">
		<!-- Header -->
		<div class="flex items-center gap-3">
			<div
				class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl {sharedState
					? 'bg-success/[0.08]'
					: 'bg-surface-2'}"
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
					class={sharedState ? 'text-success' : 'text-muted'}
				>
					<circle cx="18" cy="5" r="3" />
					<circle cx="6" cy="12" r="3" />
					<circle cx="18" cy="19" r="3" />
					<line x1="8.59" x2="15.42" y1="13.51" y2="17.49" />
					<line x1="15.41" x2="8.59" y1="6.51" y2="10.49" />
				</svg>
			</div>
			<div>
				<h3 class="text-[15px] font-medium text-foreground">Share conversation</h3>
				<p class="text-xs text-muted">Control who can view this conversation</p>
			</div>
		</div>

		<!-- Access toggle -->
		<div class="mt-4 rounded-xl border border-border-subtle bg-surface p-3.5">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-2.5">
					<div
						class="flex h-7 w-7 items-center justify-center rounded-lg {sharedState
							? 'bg-success/[0.1]'
							: 'bg-surface-2'}"
					>
						{#if sharedState}
							<svg
								width="13"
								height="13"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="text-success"
							>
								<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
							</svg>
						{:else}
							<svg
								width="13"
								height="13"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="text-muted"
							>
								<rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
								<path d="M7 11V7a5 5 0 0110 0v4" />
							</svg>
						{/if}
					</div>
					<div>
						<span class="text-sm font-medium text-foreground"
							>{sharedState ? 'Public' : 'Private'}</span
						>
						<p class="text-[11.5px] text-muted">
							{sharedState ? 'Anyone with the link can view' : 'Only you can access'}
						</p>
					</div>
				</div>
				<button
					onclick={() => setAccess(!sharedState)}
					disabled={pending}
					class="relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-60 {sharedState
						? 'bg-success'
						: 'bg-border-strong'}"
					aria-label={sharedState ? 'Make private' : 'Make public'}
					role="switch"
					aria-checked={sharedState}
				>
					<span
						class="absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 {sharedState
							? 'translate-x-5'
							: 'translate-x-0'}"
					></span>
				</button>
			</div>
		</div>

		<!-- Share link (shown when public) -->
		{#if sharedState}
			<div class="mt-3">
				<label
					for="share-url"
					class="mb-1.5 block text-[11.5px] font-medium uppercase tracking-wider text-muted"
				>
					Share link
				</label>
				<div class="flex gap-2">
					<input
						id="share-url"
						type="text"
						value={shareUrl}
						readonly
						class="min-w-0 flex-1 rounded-xl border border-border-subtle bg-surface-2 px-3 py-2 text-[14px] text-subtle outline-none"
					/>
					<button
						onclick={handleCopyLink}
						disabled={pending}
						class="flex shrink-0 items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-[14px] font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50 {copied
							? 'border-success/20 bg-success/[0.05] text-success'
							: 'text-subtle hover:bg-surface hover:text-foreground'}"
					>
						{#if copied}
							<svg
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<polyline points="20 6 9 17 4 12" />
							</svg>
							Copied
						{:else}
							<svg
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
								<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
							</svg>
							Copy
						{/if}
					</button>
				</div>
			</div>
		{/if}

		<!-- Actions -->
		<div class="mt-5 flex justify-end">
			<button
				onclick={closeDialog}
				class="rounded-xl border border-border px-4 py-2 text-sm font-medium text-subtle transition-all duration-200 hover:bg-surface hover:text-foreground"
			>
				Done
			</button>
		</div>
	</div>
</Dialog>
