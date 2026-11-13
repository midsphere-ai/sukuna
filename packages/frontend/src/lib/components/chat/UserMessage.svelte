<script lang="ts">
	import { toasts } from '$stores/toast';
	import MessageActionBar from './MessageActionBar.svelte';
	import type { UserMessage as UserMessageType } from '$services/sse';
	import { renderMarkdown } from '$lib/utils/markdown';
	import { getFileCategory } from '$lib/utils/fileCategories';
	import { getUserColor } from '$lib/utils/userColors';

	type Props = {
		message: UserMessageType;
		onFileClick?: (filename: string) => void;
		messageIndex?: number;
		onBranch?: (messageIndex: number) => void;
		onEditSubmit?: (messageIndex: number, newText: string) => void;
		isEditing?: boolean;
		onEditCancel?: () => void;
		isMultiParticipant?: boolean;
		currentUserId?: string;
		onDelete?: (messageIndex: number) => void;
	};

	let {
		message,
		onFileClick,
		messageIndex,
		onBranch,
		onEditSubmit,
		isEditing = false,
		onEditCancel,
		isMultiParticipant = false,
		currentUserId = '',
		onDelete
	}: Props = $props();

	let isOwnMessage = $derived(!message.sender_id || message.sender_id === currentUserId);
	let senderColor = $derived(message.sender_id ? getUserColor(message.sender_id) : undefined);

	// --- Inline edit state ---

	let editing = $state(false);
	let editText = $state('');
	let textareaEl: HTMLTextAreaElement | undefined = $state(undefined);

	// Sync external isEditing prop to internal state
	$effect(() => {
		if (isEditing && !editing) {
			editing = true;
			editText = message.text;
		} else if (!isEditing && editing) {
			editing = false;
		}
	});

	function startEdit(): void {
		editing = true;
		editText = message.text;
		requestAnimationFrame(() => {
			if (textareaEl) {
				textareaEl.style.height = 'auto';
				textareaEl.style.height = textareaEl.scrollHeight + 'px';
				textareaEl.focus();
			}
		});
	}

	function cancelEdit(): void {
		editing = false;
		editText = '';
		onEditCancel?.();
	}

	function saveEdit(): void {
		const trimmed = editText.trim();
		if (!trimmed || trimmed === message.text || messageIndex === undefined) {
			cancelEdit();
			return;
		}
		onEditSubmit?.(messageIndex, trimmed);
		editing = false;
		editText = '';
	}

	function handleEditKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			cancelEdit();
		} else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
			e.preventDefault();
			saveEdit();
		}
	}

	function handleEditInput(e: Event): void {
		const target = e.target as HTMLTextAreaElement;
		target.style.height = 'auto';
		target.style.height = target.scrollHeight + 'px';
	}

	// --- Action bar items ---

	let actionItems = $derived.by(() => {
		const items: {
			id: string;
			label: string;
			icon: 'copy' | 'edit' | 'branch' | 'export';
			action: () => void;
		}[] = [
			{
				id: 'copy',
				label: 'Copy',
				icon: 'copy' as const,
				action: () => {
					navigator.clipboard.writeText(message.text).then(
						() => toasts.success('Copied to clipboard'),
						() => toasts.error('Failed to copy')
					);
				}
			}
		];
		if (onEditSubmit && messageIndex !== undefined) {
			items.push({
				id: 'edit',
				label: 'Edit & Resubmit',
				icon: 'edit' as const,
				action: startEdit
			});
		}
		if (onBranch && messageIndex !== undefined) {
			items.push({
				id: 'branch',
				label: 'Branch from here',
				icon: 'branch' as const,
				action: () => onBranch!(messageIndex!)
			});
		}
		// Delete: only visible on sender's own messages in multi-participant mode
		if (onDelete && messageIndex !== undefined && isOwnMessage) {
			items.push({
				id: 'delete',
				label: 'Delete',
				icon: 'export' as const,
				action: () => onDelete!(messageIndex!)
			});
		}
		return items;
	});

	let renderedHtml = $derived(renderMarkdown(message.text));

	function handleFileClick(filename: string): void {
		if (onFileClick) {
			onFileClick(filename);
		}
	}

	let addonCount = $derived(message.addons?.length ?? 0);
	let mcpCount = $derived(message.mcps?.length ?? 0);

	// --- Relative time ---

	let now = $state(Date.now());
	$effect(() => {
		if (!message.created_at) return;
		const interval = setInterval(() => (now = Date.now()), 60_000);
		return () => clearInterval(interval);
	});

	function formatRelativeTime(isoString: string | undefined, _now: number): string {
		if (!isoString) return '';
		const diff = _now - new Date(isoString).getTime();
		if (diff < 0) return 'just now';
		const seconds = Math.floor(diff / 1000);
		if (seconds < 60) return 'just now';
		const minutes = Math.floor(seconds / 60);
		if (minutes < 60) return `${minutes}m ago`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		if (days < 7) return `${days}d ago`;
		return new Date(isoString).toLocaleDateString(undefined, {
			month: 'short',
			day: 'numeric'
		});
	}

	let relativeTime = $derived(formatRelativeTime(message.created_at, now));
</script>

<div
	class="group/msg flex py-2 {isMultiParticipant && !isOwnMessage
		? 'justify-start'
		: 'justify-end'}"
	data-testid="user-message"
>
	<div class="max-w-[85%] min-w-0 space-y-1.5 relative">
		{#if message.optimistic}
			<div class="flex justify-end">
				<span
					class="inline-flex items-center gap-1.5 rounded-full bg-accent/10 px-2.5 py-0.5 text-[11.5px] font-medium text-accent"
				>
					<svg
						class="h-3 w-3 animate-spin"
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
					>
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
						></circle>
						<path
							class="opacity-75"
							fill="currentColor"
							d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
						></path>
					</svg>
					Sending
				</span>
			</div>
		{/if}

		{#if message.files && message.files.length > 0}
			<div
				class="flex flex-wrap {isOwnMessage ? 'justify-end' : 'justify-start'} gap-1.5"
				data-testid="file-attachments"
			>
				{#each message.files as file (file)}
					<button
						onclick={() => handleFileClick(file)}
						class="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface px-2.5 py-1 text-[11.5px] font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
						title="Preview {file}"
					>
						{#if getFileCategory(file) === 'image'}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="12"
								height="12"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								><rect width="18" height="18" x="3" y="3" rx="2" ry="2" /><circle
									cx="9"
									cy="9"
									r="2"
								/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" /></svg
							>
						{:else if getFileCategory(file) === 'pdf'}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="12"
								height="12"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
									d="M14 2v4a2 2 0 0 0 2 2h4"
								/><path d="M10 12h4" /><path d="M10 16h4" /></svg
							>
						{:else if getFileCategory(file) === 'code'}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="12"
								height="12"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg
							>
						{:else}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="12"
								height="12"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
									d="M14 2v4a2 2 0 0 0 2 2h4"
								/></svg
							>
						{/if}
						<span class="max-w-[120px] truncate">{file}</span>
					</button>
				{/each}
			</div>
		{/if}

		{#if addonCount > 0 || mcpCount > 0}
			<div
				class="flex flex-wrap {isOwnMessage
					? 'justify-end'
					: 'justify-start'} gap-1.5 text-[11.5px]"
			>
				{#if addonCount > 0}
					<span
						class="inline-flex items-center gap-1 rounded-md bg-accent/10 px-2 py-0.5 font-medium text-accent"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="10"
							height="10"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2.5"><path d="M12 2v6m0 8v6M2 12h6m8 0h6" /></svg
						>
						{addonCount} addon{addonCount !== 1 ? 's' : ''}
					</span>
				{/if}
				{#if mcpCount > 0}
					<span
						class="inline-flex items-center gap-1 rounded-md bg-accent/10 px-2 py-0.5 font-medium text-accent"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="10"
							height="10"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2.5"
							><circle cx="12" cy="12" r="3" /><path
								d="M12 1v4m0 14v4M4.22 4.22l2.83 2.83m9.9 9.9l2.83 2.83M1 12h4m14 0h4M4.22 19.78l2.83-2.83m9.9-9.9l2.83-2.83"
							/></svg
						>
						{mcpCount} MCP{mcpCount !== 1 ? 's' : ''}
					</span>
				{/if}
			</div>
		{/if}

		{#if isMultiParticipant && !isOwnMessage && message.sender_name}
			<div class="flex {isOwnMessage ? 'justify-end' : 'justify-start'} px-0.5">
				<span class="text-[11.5px] font-medium" style:color={senderColor}
					>{message.sender_name}</span
				>
			</div>
		{/if}

		<div
			class="rounded-2xl {isOwnMessage
				? 'rounded-br-sm bg-accent/[0.08]'
				: 'rounded-bl-sm bg-surface border border-border-subtle'} px-4 py-2.5 text-foreground"
		>
			{#if editing}
				<!-- Inline edit UI -->
				<div class="space-y-2">
					<textarea
						bind:this={textareaEl}
						bind:value={editText}
						oninput={handleEditInput}
						onkeydown={handleEditKeydown}
						class="w-full resize-none rounded-lg bg-surface px-3 py-2 text-[14px] leading-relaxed text-foreground outline-none ring-1 ring-border-subtle placeholder:text-muted focus:ring-accent"
						rows="3"
					></textarea>
					<div class="flex items-center justify-end gap-2">
						<button
							onclick={cancelEdit}
							class="rounded-lg px-3 py-1.5 text-xs font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground"
						>
							Cancel
						</button>
						<button
							onclick={saveEdit}
							class="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-accent/90"
						>
							Save & Resubmit
						</button>
					</div>
				</div>
			{:else}
				<!-- Markdown text -->
				<!-- eslint-disable svelte/no-at-html-tags -->
				<div
					class="prose max-w-none font-normal text-[14px] leading-relaxed text-foreground [&_a]:text-accent [&_a]:underline [&_a]:decoration-accent/30 [&_code]:rounded-md [&_code]:bg-surface-2 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-[14px] [&_code]:text-foreground [&_pre]:rounded-xl [&_pre]:bg-surface-2 [&_pre]:p-3.5 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_ol]:pl-5 [&_ul]:pl-5"
				>
					{@html renderedHtml}
				</div>
				<!-- eslint-enable svelte/no-at-html-tags -->
			{/if}
		</div>

		<!-- Action bar (hover, desktop only) -->
		{#if !editing}
			<MessageActionBar items={actionItems} position="right" alwaysVisible />
		{/if}

		{#if relativeTime}
			<div class="flex {isOwnMessage ? 'justify-end' : 'justify-start'} pr-0.5 pt-0.5">
				<span class="text-[11.5px] text-muted">{relativeTime}</span>
			</div>
		{/if}
	</div>
</div>
