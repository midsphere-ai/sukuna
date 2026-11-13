<script lang="ts">
	import type { ToolCallMessage as ToolCallMessageType, PhaseInfo } from '$services/sse';
	import { getServerCategory } from '$lib/utils/toolLabels';
	import ToolCallMessage from './ToolCallMessage.svelte';
	import PlanOverview from './PlanOverview.svelte';

	type Props = {
		phase: PhaseInfo;
		toolCalls: ToolCallMessageType[];
		defaultCollapsed?: boolean;
		onToolCallClick?: (callId: string) => void;
	};

	let { phase, toolCalls, defaultCollapsed = false, onToolCallClick }: Props = $props();

	let isActive = $derived(phase.status === 'in_progress');
	let isCompleted = $derived(phase.status === 'completed');
	let toolCount = $derived(toolCalls.length);

	// Track user-initiated toggle separately; null = no user override
	let userToggle = $state<boolean | null>(null);
	let collapsed = $derived(isActive ? false : (userToggle ?? defaultCollapsed));

	function toggle(): void {
		if (isActive) return;
		userToggle = !collapsed;
	}

	// Get unique category icons for the collapsed summary
	let uniqueCategories = $derived.by(() => {
		const seen: Record<string, boolean> = {};
		const cats: string[] = [];
		for (const tc of toolCalls) {
			if (tc.toolName === 'mcp_get_plan' || (tc.toolName === 'plan' && tc.args?.action === 'get'))
				continue;
			const cat = getServerCategory(tc.toolName, tc.args);
			if (!seen[cat]) {
				seen[cat] = true;
				cats.push(cat);
			}
			if (cats.length >= 4) break;
		}
		return cats;
	});
</script>

<div
	class="my-0.5"
	data-testid="phase-group"
	data-phase-id={phase.id}
	data-phase-status={phase.status}
>
	<!-- Phase header -->
	<button
		onclick={toggle}
		class="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-surface -mx-1.5"
		class:cursor-default={isActive}
		data-testid="phase-header"
	>
		<!-- Collapse chevron -->
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="10"
			height="10"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2.5"
			stroke-linecap="round"
			stroke-linejoin="round"
			class="shrink-0 text-muted transition-transform"
			class:rotate-90={!collapsed}
		>
			<path d="m9 18 6-6-6-6" />
		</svg>

		{#if collapsed}
			<!-- Collapsed: show mini category icons + "N actions" -->
			<div class="flex items-center gap-1 text-muted">
				{#each uniqueCategories as cat (cat)}
					<div class="flex h-3.5 w-3.5 items-center justify-center">
						{#if cat === 'terminal'}
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
								><polyline points="4 17 10 11 4 5" /><line x1="12" x2="20" y1="19" y2="19" /></svg
							>
						{:else if cat === 'file'}
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
								><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
									d="M14 2v4a2 2 0 0 0 2 2h4"
								/></svg
							>
						{:else if cat === 'code'}
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
								><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg
							>
						{:else if cat === 'search'}
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
								><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg
							>
						{:else if cat === 'browser'}
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
								><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path
									d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
								/></svg
							>
						{:else if cat === 'download'}
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
								><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline
									points="7 10 12 15 17 10"
								/><line x1="12" x2="12" y1="15" y2="3" /></svg
							>
						{:else if cat === 'web'}
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
								><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M3 9h18" /><path
									d="M9 21V9"
								/></svg
							>
						{:else if cat === 'plan'}
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
								><path
									d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"
								/><path
									d="M15 2H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1Z"
								/></svg
							>
						{:else}
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
								><path
									d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76Z"
								/></svg
							>
						{/if}
					</div>
				{/each}
			</div>

			<span class="text-[14px] text-muted">
				{toolCount}
				{toolCount === 1 ? 'action' : 'actions'}
			</span>
		{:else}
			<!-- Expanded: show phase status + description -->
			{#if isActive}
				<span class="relative flex h-2 w-2 shrink-0" data-testid="phase-indicator-active">
					<span class="inline-flex h-2 w-2 animate-pulse rounded-full bg-accent"></span>
				</span>
			{:else if isCompleted}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="11"
					height="11"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2.5"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="shrink-0 text-success"
					data-testid="phase-indicator-completed"
				>
					<polyline points="20 6 9 17 4 12" />
				</svg>
			{:else}
				<div
					class="h-2 w-2 shrink-0 rounded-full border border-border-strong"
					data-testid="phase-indicator-pending"
				></div>
			{/if}

			<span
				class="flex-1 truncate text-[14px] font-medium {isActive
					? 'text-subtle'
					: isCompleted
						? 'text-muted'
						: 'text-muted'}"
			>
				{phase.description}
			</span>

			{#if isActive}
				<span class="shrink-0 text-[10.5px] text-accent/70" data-testid="phase-status-badge">
					Working
				</span>
			{:else}
				<span class="shrink-0 text-[10.5px] text-muted" data-testid="phase-tool-count">
					{toolCount}
				</span>
			{/if}
		{/if}
	</button>

	<!-- Phase content -->
	{#if !collapsed}
		<div class="ml-2.5 border-l border-border-subtle pl-3 pt-0.5" data-testid="phase-content">
			{#each toolCalls as tc (tc.callId)}
				{#if tc.toolName === 'mcp_get_plan' || (tc.toolName === 'plan' && tc.args?.action === 'get')}
					<PlanOverview message={tc} />
				{:else}
					<ToolCallMessage
						message={tc}
						onClick={onToolCallClick ? () => onToolCallClick(tc.callId) : undefined}
					/>
				{/if}
			{/each}
		</div>
	{/if}
</div>
