<!-- @internal Test/development component - only imported by PhaseGroup.svelte (also test-only) -->
<script lang="ts">
	import type { ToolCallMessage, PlanState, PhaseInfo } from '$services/sse';
	import { planState } from '$services/sse';

	type Props = {
		message: ToolCallMessage;
	};

	let { message }: Props = $props();

	let expanded = $state(false);

	// Get plan data from tool result first, then fall back to planState store
	let planData: PlanState | null = $derived.by(() => {
		if (message.result && typeof message.result === 'object') {
			const result = message.result as Record<string, unknown>;
			if (result.message && typeof result.message === 'object') {
				const plan = result.message as Record<string, unknown>;
				const phases: PhaseInfo[] = Array.isArray(plan.phases)
					? (plan.phases as Array<Record<string, unknown>>).map((p, i) => ({
							id: (p.id as string) || `phase_${i + 1}`,
							description: (p.description as string) || '',
							status: ((p.status as string) || 'pending') as PhaseInfo['status'],
							startedAt: (p.started_at as string) || undefined,
							completedAt: (p.completed_at as string) || undefined
						}))
					: [];
				return {
					goal: (plan.goal as string) || '',
					phases,
					currentPhaseId: (plan.current_phase_id as string) || ''
				};
			}
		}
		return $planState;
	});
</script>

<div
	class="my-1 overflow-hidden rounded-lg border border-border-subtle bg-surface transition-colors"
	data-testid="plan-overview"
>
	<!-- Header -->
	<button
		onclick={() => (expanded = !expanded)}
		class="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-surface-2"
		data-testid="plan-overview-toggle"
	>
		<!-- Status indicator -->
		<div class="relative flex shrink-0 items-center justify-center">
			{#if message.status === 'running'}
				<svg
					class="h-4 w-4 animate-spin text-muted"
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
				>
					<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
					></circle>
					<path
						class="opacity-75"
						fill="currentColor"
						d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
					></path>
				</svg>
			{:else}
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
					class="text-success"
				>
					<polyline points="20 6 9 17 4 12" />
				</svg>
			{/if}
		</div>

		<!-- Plan icon -->
		<div class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface">
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
				class="text-subtle"
			>
				<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
				<path d="M15 2H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1Z" />
				<path d="M9 12h6" />
				<path d="M9 16h6" />
			</svg>
		</div>

		<!-- Label -->
		<div class="min-w-0 flex-1">
			<div class="flex items-baseline gap-1.5">
				<span class="text-[10.5px] font-medium uppercase tracking-wide text-muted">Planning</span>
				<span class="text-muted">·</span>
				<span class="truncate text-xs font-medium text-foreground hover:text-accent">View Plan</span
				>
			</div>
			{#if planData?.goal}
				<p class="mt-0.5 truncate text-[11.5px] text-muted">{planData.goal}</p>
			{/if}
		</div>

		<!-- Expand chevron -->
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
			class="shrink-0 text-muted transition-transform"
			class:rotate-180={expanded}
		>
			<path d="m6 9 6 6 6-6" />
		</svg>
	</button>

	<!-- Expanded plan details -->
	{#if expanded && planData}
		<div class="border-t border-border-subtle px-3 py-2.5" data-testid="plan-overview-details">
			{#if planData.goal}
				<p class="mb-2 text-xs font-medium text-foreground">{planData.goal}</p>
			{/if}
			<div class="space-y-1.5">
				{#each planData.phases as phase (phase.id)}
					<div class="flex items-center gap-2" data-testid="plan-phase-item">
						{#if phase.status === 'completed'}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="12"
								height="12"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2.5"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="shrink-0 text-success"
							>
								<polyline points="20 6 9 17 4 12" />
							</svg>
						{:else if phase.status === 'in_progress'}
							<span class="flex h-3 w-3 shrink-0 items-center justify-center">
								<span class="inline-flex h-2 w-2 animate-pulse rounded-full bg-accent"></span>
							</span>
						{:else}
							<div class="flex h-3 w-3 shrink-0 items-center justify-center">
								<div class="h-1.5 w-1.5 rounded-full border border-border-strong"></div>
							</div>
						{/if}
						<span
							class="text-[11.5px] {phase.status === 'in_progress'
								? 'text-foreground'
								: ''} {phase.status === 'completed'
								? 'text-muted line-through decoration-border-strong'
								: ''} {phase.status === 'pending' ? 'text-muted' : ''}"
						>
							{phase.description}
						</span>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
