/**
 * Plan-extraction helpers.
 *
 * The agent publishes plan state via the `plan` / `mcp_update_plan` /
 * `mcp_advance_plan` tool calls. This module walks a list of tool calls,
 * finds the most recent plan snapshot, and returns a normalised `PlanState`.
 *
 * Used by the chat ComputerPanel for the live agent view and by the tasks
 * page drawer to show plan-derived goal + progress.
 */

import type { PlanState, ToolCallMessage } from '$services/stream-types';

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parsePlanPhases(value: unknown): PlanState['phases'] {
	if (!Array.isArray(value)) return [];
	return value
		.map((phase, index) => {
			if (typeof phase === 'string') {
				return {
					id: `phase_${index + 1}`,
					description: phase,
					status: 'pending' as const
				};
			}
			if (!isRecord(phase)) return null;
			const status = phase.status;
			return {
				id: typeof phase.id === 'string' && phase.id ? phase.id : `phase_${index + 1}`,
				description: typeof phase.description === 'string' ? phase.description : '',
				status: status === 'in_progress' || status === 'completed' ? status : ('pending' as const),
				startedAt: typeof phase.startedAt === 'string' ? phase.startedAt : undefined,
				completedAt: typeof phase.completedAt === 'string' ? phase.completedAt : undefined
			};
		})
		.filter((phase): phase is PlanState['phases'][number] => phase !== null);
}

export function normalisePlanState(value: unknown): PlanState | null {
	if (!isRecord(value)) return null;
	const goal = typeof value.goal === 'string' ? value.goal : '';
	const phases = parsePlanPhases(value.phases);
	const currentFromCamel = value.currentPhaseId;
	const currentFromSnake = value.current_phase_id;
	const currentPhaseId =
		typeof currentFromCamel === 'string'
			? currentFromCamel
			: typeof currentFromSnake === 'string'
				? currentFromSnake
				: '';

	if (!goal && phases.length === 0) return null;
	return { goal, phases, currentPhaseId };
}

export function extractPlanFromToolResult(value: unknown): PlanState | null {
	const direct = normalisePlanState(value);
	if (direct) return direct;
	if (!isRecord(value)) return null;
	return normalisePlanState(value.message);
}

export function isPlanTool(toolName: string, args: Record<string, unknown>): boolean {
	return (
		toolName === 'mcp_update_plan' ||
		toolName === 'mcp_advance_plan' ||
		toolName === 'mcp_get_plan' ||
		(toolName === 'plan' && typeof args.action === 'string')
	);
}

/** Walk tool calls (newest last) and return the most recent plan snapshot, or null. */
export function getPlanFromToolCalls(calls: ToolCallMessage[]): PlanState | null {
	for (let i = calls.length - 1; i >= 0; i--) {
		const call = calls[i];
		if (!isPlanTool(call.toolName, call.args)) continue;

		const fromResult = extractPlanFromToolResult(call.result);
		if (fromResult) return fromResult;

		const fromArgs = normalisePlanState(call.args);
		if (fromArgs) return fromArgs;
	}
	return null;
}

/** Percent progress 0-100 derived from completed vs total phases. */
export function planProgressPct(plan: PlanState | null): number {
	if (!plan || plan.phases.length === 0) return 0;
	const done = plan.phases.filter((p) => p.status === 'completed').length;
	return Math.round((done / plan.phases.length) * 100);
}

/** Rough time-remaining estimate. Heuristic: average of completed phases'
 *  durations times remaining count. Returns null if not enough data. */
export function estimateRemaining(plan: PlanState | null): string | null {
	if (!plan) return null;
	const completed = plan.phases.filter(
		(p) => p.status === 'completed' && p.startedAt && p.completedAt
	);
	if (completed.length === 0) return null;

	const avgMs =
		completed.reduce((sum, p) => {
			const dur = new Date(p.completedAt!).getTime() - new Date(p.startedAt!).getTime();
			return sum + Math.max(0, dur);
		}, 0) / completed.length;

	const remaining = plan.phases.filter((p) => p.status !== 'completed').length;
	const totalMs = avgMs * remaining;
	if (totalMs < 1000) return null;

	const minutes = Math.floor(totalMs / 60_000);
	const seconds = Math.floor((totalMs % 60_000) / 1000);
	return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}
