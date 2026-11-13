<script lang="ts">
	import type { ToolCallMessage as ToolCallMessageType } from '$services/sse';
	import { getToolIcon, getActionLabel } from '$lib/utils/toolLabels';
	import { getFileCategory } from '$lib/utils/fileCategories';
	import ToolCategoryIcon from './ToolCategoryIcon.svelte';
	import { fade } from 'svelte/transition';

	type Props = {
		message: ToolCallMessageType;
		onClick?: () => void;
		muted?: boolean;
		hideMessageHeader?: boolean;
	};

	let { message, onClick, muted = false, hideMessageHeader = false }: Props = $props();
	let icon = $derived(getToolIcon(message.toolName, message.args));
	let label = $derived.by(() => {
		if (!muted) return getActionLabel(message.toolName, message.args);
		return firstNonEmptyString(message.args?.brief) || '';
	});
	let isMessageTool = $derived(message.toolName === 'message');
	let labelTextClass = $derived(
		muted ? 'text-[14px] text-foreground/70' : 'text-[14px] text-foreground'
	);
	let messageBodyClass = $derived(
		muted
			? 'text-[14px] leading-relaxed text-foreground/70 whitespace-pre-wrap'
			: 'text-[14px] leading-relaxed text-foreground whitespace-pre-wrap'
	);
	let mutedCardClass = $derived('my-0.5 rounded-3xl border border-border bg-surface/80 px-2 py-1');
	let rowDisplayClass = $derived(muted ? 'inline-flex max-w-full' : 'flex');
	let rowGapClass = $derived(muted ? 'gap-1.5' : 'gap-2.5');
	let rowLabelClass = $derived(muted ? 'min-w-0 flex-1 truncate' : 'min-w-0 flex-1 truncate');
	let mutedIconClass = $derived('inline-flex shrink-0 text-foreground/70');
	let iconWrapClass = $derived(
		'flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] border border-border-strong bg-transparent text-subtle'
	);
	let messageHeaderLabelClass = $derived(
		muted
			? 'min-w-0 whitespace-normal break-words font-medium'
			: 'min-w-0 flex-1 truncate font-medium'
	);
	let containerClickClass = $derived(
		onClick
			? `cursor-pointer transition-colors ${muted ? 'hover:border-border' : 'rounded-lg px-1.5 -mx-1.5 hover:bg-surface'}`
			: ''
	);
	let messageToolContainerClass = $derived.by(() =>
		muted ? `my-0.5 py-0.5 ${containerClickClass}` : `py-0.5 ${containerClickClass}`
	);

	// For submit_attachments, extract the file list from args
	let isAttachment = $derived(message.toolName === 'submit_attachments');
	let attachmentFiles = $derived.by(() => {
		if (!isAttachment) return [];
		const files = message.args?.files;
		if (!Array.isArray(files)) return [];
		return files.filter((f): f is string => typeof f === 'string');
	});
	let attachmentExpanded = $state(false);

	function toggleAttachmentExpand(e: MouseEvent) {
		e.stopPropagation();
		attachmentExpanded = !attachmentExpanded;
	}

	function basename(path: string): string {
		return path.split('/').pop() || path;
	}

	function firstNonEmptyString(...values: unknown[]): string | null {
		for (const value of values) {
			if (typeof value !== 'string') continue;
			const trimmed = value.trim();
			if (trimmed) return trimmed;
		}
		return null;
	}

	function toTitleWords(value: string): string {
		return value
			.split(/[\s_-]+/)
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
			.join(' ');
	}

	let messageBadge = $derived.by(() => {
		if (!isMessageTool) return null;
		const raw = firstNonEmptyString(message.args?.type);
		return raw ? toTitleWords(raw) : null;
	});

	let messageBody = $derived.by(() => {
		if (!isMessageTool) return null;
		const result =
			typeof message.result === 'object' && message.result !== null
				? (message.result as Record<string, unknown>)
				: null;
		const resultText = typeof message.result === 'string' ? message.result : null;
		return firstNonEmptyString(
			message.args?.text,
			message.args?.content,
			result?.message,
			result?.text,
			result?.content,
			result?.output,
			result?.answer,
			result?.final_answer,
			result?.summary,
			resultText
		);
	});

	let showErrorIndicator = $derived(message.status === 'error' && (!isMessageTool || !messageBody));
</script>

{#if isAttachment && attachmentFiles.length > 0}
	<!-- Special rendering for submit_attachments -->
	<div
		data-testid="tool-call-message"
		data-tool-name={message.toolName}
		data-tool-status={message.status}
	>
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="{rowDisplayClass} items-center {rowGapClass} cursor-pointer transition-colors {muted
				? `${mutedCardClass} hover:border-border`
				: 'py-0.5 rounded-lg px-1.5 -mx-1.5 hover:bg-surface'}"
			onclick={toggleAttachmentExpand}
		>
			<!-- Tool icon -->
			{#if muted}
				<span class={mutedIconClass}>
					<ToolCategoryIcon {icon} size={14} />
				</span>
			{:else}
				<div class={iconWrapClass}>
					<ToolCategoryIcon {icon} size={14} />
				</div>
			{/if}

			<!-- Label -->
			<span class="{rowLabelClass} {labelTextClass}">
				{label}
			</span>

			<!-- Expand chevron + status -->
			<div class="flex shrink-0 items-center gap-1.5">
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
					class="text-muted transition-transform duration-150 {attachmentExpanded
						? 'rotate-180'
						: ''}"
				>
					<path d="m6 9 6 6 6-6" />
				</svg>
				{#if message.durationMs && message.status !== 'running' && !muted}
					<span class="text-[10.5px] text-muted" data-testid="tool-duration">
						{(message.durationMs / 1000).toFixed(1)}s
					</span>
				{/if}
			</div>
		</div>

		{#if attachmentExpanded}
			<div class="ml-9 mt-1 flex flex-wrap gap-1.5" transition:fade={{ duration: 150 }}>
				{#each attachmentFiles as file (file)}
					{@const name = basename(file)}
					{@const category = getFileCategory(name)}
					<div
						class="inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface px-2.5 py-1 text-[11.5px] font-medium text-subtle"
						title={file}
					>
						{#if category === 'image'}
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
						{:else if category === 'pdf'}
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
						{:else if category === 'code'}
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
						<span class="max-w-[200px] truncate">{name}</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{:else if isMessageTool}
	<!-- Message tool rendering -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class={messageToolContainerClass}
		data-testid="tool-call-message"
		data-tool-name={message.toolName}
		data-tool-status={message.status}
		onclick={onClick}
	>
		{#if hideMessageHeader}
			{#if messageBody}
				<p class={messageBodyClass} data-testid="tool-message-body">
					{messageBody}
				</p>
			{:else if message.error}
				<p class={messageBodyClass} data-testid="tool-message-body">
					{message.error}
				</p>
			{:else}
				<p class={messageBodyClass} data-testid="tool-message-body">
					{label}
				</p>
			{/if}
		{:else}
			<div class="flex items-center gap-2">
				{#if muted}
					<span class={mutedIconClass}>
						<ToolCategoryIcon {icon} size={14} />
					</span>
				{:else}
					<div class={iconWrapClass}>
						<ToolCategoryIcon {icon} size={14} />
					</div>
				{/if}

				<div class="min-w-0 flex flex-1 items-center gap-1.5">
					<span class="{messageHeaderLabelClass} {labelTextClass}">{label}</span>
					{#if messageBadge}
						<span
							class="inline-flex shrink-0 items-center rounded-md border border-border-subtle bg-surface px-1.5 py-0.5 text-[10.5px] font-medium text-muted"
						>
							{messageBadge}
						</span>
					{/if}
				</div>

				<div class="flex shrink-0 items-center gap-1.5">
					{#if message.status === 'running'}
						<svg
							class="h-3 w-3 animate-spin text-muted"
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							data-testid="tool-status-running"
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
					{:else if showErrorIndicator}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="11"
							height="11"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-accent/50"
							data-testid="tool-status-error"
						>
							<circle cx="12" cy="12" r="10" /><line x1="15" x2="9" y1="9" y2="15" /><line
								x1="9"
								x2="15"
								y1="9"
								y2="15"
							/>
						</svg>
					{/if}

					{#if message.durationMs && message.status !== 'running' && !muted}
						<span class="text-[10.5px] text-muted" data-testid="tool-duration">
							{(message.durationMs / 1000).toFixed(1)}s
						</span>
					{/if}
				</div>
			</div>
		{/if}

		{#if messageBody && !hideMessageHeader}
			<p class="mt-2 {messageBodyClass}">{messageBody}</p>
		{/if}
	</div>
{:else}
	<!-- Default tool call rendering -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="{rowDisplayClass} items-center {rowGapClass} py-0.5 {muted
			? mutedCardClass
			: ''} {containerClickClass}"
		data-testid="tool-call-message"
		data-tool-name={message.toolName}
		data-tool-status={message.status}
		onclick={onClick}
	>
		<!-- Tool icon -->
		{#if muted}
			<span class={mutedIconClass}>
				<ToolCategoryIcon {icon} size={14} />
			</span>
		{:else}
			<div class={iconWrapClass}>
				<ToolCategoryIcon {icon} size={14} />
			</div>
		{/if}

		<!-- Label -->
		<span class="{rowLabelClass} {labelTextClass}">
			{label}
		</span>

		<!-- Status indicator -->
		{#if !muted}
			<div class="flex shrink-0 items-center gap-1.5">
				{#if message.status === 'running'}
					<svg
						class="h-3 w-3 animate-spin text-muted"
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						data-testid="tool-status-running"
					>
						<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
						></circle>
						<path
							class="opacity-75"
							fill="currentColor"
							d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
						></path>
					</svg>
				{:else if showErrorIndicator}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="11"
						height="11"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="text-accent/50"
						data-testid="tool-status-error"
					>
						<circle cx="12" cy="12" r="10" /><line x1="15" x2="9" y1="9" y2="15" /><line
							x1="9"
							x2="15"
							y1="9"
							y2="15"
						/>
					</svg>
				{/if}

				{#if message.durationMs && message.status !== 'running'}
					<span class="text-[10.5px] text-muted" data-testid="tool-duration">
						{(message.durationMs / 1000).toFixed(1)}s
					</span>
				{/if}
			</div>
		{/if}
	</div>
{/if}
