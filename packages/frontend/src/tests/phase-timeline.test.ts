import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { render, screen, fireEvent } from '@testing-library/svelte';

// Mock dependencies before importing
vi.mock('$app/environment', () => ({ browser: true }));
vi.mock('$stores/toast', () => ({
	toasts: {
		success: vi.fn(),
		error: vi.fn(),
		warning: vi.fn(),
		info: vi.fn(),
		remove: vi.fn()
	}
}));

import {
	messages,
	planState,
	resetStores,
	replayEvents,
	type Message,
	type ToolCallMessage as ToolCallMessageType
} from '$services/sse';

import ChatMessageList from '../lib/components/chat/ChatMessageList.svelte';
import PhaseGroup from '../lib/components/chat/PhaseGroup.svelte';
import PlanOverview from '../lib/components/chat/PlanOverview.svelte';

// --- SSE Service Plan Handling Tests ---

describe('SSE Service - Plan state management', () => {
	beforeEach(() => {
		resetStores();
	});

	it('initializes with null planState', () => {
		expect(get(planState)).toBeNull();
	});

	it('resets planState on resetStores', () => {
		// Replay an update_plan event first
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-1',
					tool_name: 'mcp_update_plan',
					arguments: {
						goal: 'Test goal',
						phases: ['Phase 1', 'Phase 2'],
						current_phase_id: 'phase_1',
						brief: 'Creating plan'
					}
				}
			}
		]);
		expect(get(planState)).not.toBeNull();

		resetStores();
		expect(get(planState)).toBeNull();
	});

	describe('mcp_update_plan', () => {
		it('updates planState with goal and phases from string array', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Build a dashboard',
							phases: ['Research', 'Design', 'Implementation'],
							current_phase_id: 'phase_1',
							brief: 'Creating plan'
						}
					}
				}
			]);

			const state = get(planState);
			expect(state).not.toBeNull();
			expect(state!.goal).toBe('Build a dashboard');
			expect(state!.phases).toHaveLength(3);
			expect(state!.currentPhaseId).toBe('phase_1');
		});

		it('parses phases from string array with auto-generated IDs', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Alpha', 'Beta', 'Gamma'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				}
			]);

			const state = get(planState)!;
			expect(state.phases[0].id).toBe('phase_1');
			expect(state.phases[0].description).toBe('Alpha');
			expect(state.phases[1].id).toBe('phase_2');
			expect(state.phases[1].description).toBe('Beta');
			expect(state.phases[2].id).toBe('phase_3');
			expect(state.phases[2].description).toBe('Gamma');
		});

		it('parses phases from dict array with custom IDs', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: [
								{ id: 'research', description: 'Research and planning', status: 'pending' },
								{ id: 'build', description: 'Build the app', status: 'pending' }
							],
							current_phase_id: 'research',
							brief: 'Plan'
						}
					}
				}
			]);

			const state = get(planState)!;
			expect(state.phases[0].id).toBe('research');
			expect(state.phases[0].description).toBe('Research and planning');
			expect(state.phases[1].id).toBe('build');
		});

		it('marks current phase as in_progress', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1', 'Phase 2'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				}
			]);

			const state = get(planState)!;
			expect(state.phases[0].status).toBe('in_progress');
			expect(state.phases[0].startedAt).toBeTruthy();
			expect(state.phases[1].status).toBe('pending');
		});

		it('does NOT add mcp_update_plan to messages', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(0);
		});

		it('skips tool_result for mcp_update_plan', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						success: true,
						result: { success: true, message: 'Created plan' }
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(0);
		});
	});

	describe('mcp_advance_plan', () => {
		it('transitions phases correctly', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1', 'Phase 2', 'Phase 3'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-advance-1',
						tool_name: 'mcp_advance_plan',
						arguments: {
							current_phase_id: 'phase_1',
							next_phase_id: 'phase_2',
							brief: 'Advancing'
						}
					}
				}
			]);

			const state = get(planState)!;
			expect(state.currentPhaseId).toBe('phase_2');
			expect(state.phases[0].status).toBe('completed');
			expect(state.phases[0].completedAt).toBeTruthy();
			expect(state.phases[1].status).toBe('in_progress');
			expect(state.phases[1].startedAt).toBeTruthy();
			expect(state.phases[2].status).toBe('pending');
		});

		it('does NOT add mcp_advance_plan to messages', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1', 'Phase 2'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-advance-1',
						tool_name: 'mcp_advance_plan',
						arguments: {
							current_phase_id: 'phase_1',
							next_phase_id: 'phase_2',
							brief: 'Advancing'
						}
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(0);
		});

		it('skips tool_result for mcp_advance_plan', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1', 'Phase 2'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-advance-1',
						tool_name: 'mcp_advance_plan',
						arguments: {
							current_phase_id: 'phase_1',
							next_phase_id: 'phase_2',
							brief: 'Advancing'
						}
					}
				},
				{
					sequence: 3,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-advance-1',
						tool_name: 'mcp_advance_plan',
						success: true,
						result: { success: true, message: 'Advanced' }
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(0);
		});
	});

	describe('phaseId assignment', () => {
		it('assigns phaseId to tool calls after plan creation', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Research', 'Build'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-search-1',
						tool_name: 'mcp_search_google',
						arguments: { query: 'test' }
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(1);
			expect(msgs[0].type).toBe('tool_call');
			expect((msgs[0] as ToolCallMessageType).phaseId).toBe('phase_1');
		});

		it('updates phaseId after mcp_advance_plan', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Research', 'Build'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-search-1',
						tool_name: 'mcp_search_google',
						arguments: { query: 'test' }
					}
				},
				{
					sequence: 3,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-advance-1',
						tool_name: 'mcp_advance_plan',
						arguments: {
							current_phase_id: 'phase_1',
							next_phase_id: 'phase_2',
							brief: 'Next'
						}
					}
				},
				{
					sequence: 4,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-edit-1',
						tool_name: 'edit_file',
						arguments: { path: 'test.txt' }
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(2);
			expect((msgs[0] as ToolCallMessageType).phaseId).toBe('phase_1');
			expect((msgs[1] as ToolCallMessageType).phaseId).toBe('phase_2');
		});

		it('tool calls before plan have no phaseId', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-early-1',
						tool_name: 'mcp_search_google',
						arguments: { query: 'test' }
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(1);
			expect((msgs[0] as ToolCallMessageType).phaseId).toBeUndefined();
		});
	});

	describe('mcp_get_plan', () => {
		it('adds mcp_get_plan as a regular tool_call with phaseId', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-get-1',
						tool_name: 'mcp_get_plan',
						arguments: { brief: 'Checking plan' }
					}
				}
			]);

			const msgs = get(messages);
			expect(msgs).toHaveLength(1);
			expect(msgs[0].type).toBe('tool_call');
			expect((msgs[0] as ToolCallMessageType).toolName).toBe('mcp_get_plan');
			expect((msgs[0] as ToolCallMessageType).phaseId).toBe('phase_1');
		});

		it('updates planState from mcp_get_plan tool_result', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-get-1',
						tool_name: 'mcp_get_plan',
						arguments: { brief: 'Checking plan' }
					}
				},
				{
					sequence: 2,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-get-1',
						tool_name: 'mcp_get_plan',
						success: true,
						result: {
							success: true,
							message: {
								goal: 'Build dashboard',
								phases: [
									{
										id: 'phase_1',
										description: 'Research',
										status: 'completed',
										started_at: '2024-01-01',
										completed_at: '2024-01-02'
									},
									{
										id: 'phase_2',
										description: 'Build',
										status: 'in_progress',
										started_at: '2024-01-02'
									}
								],
								current_phase_id: 'phase_2'
							},
							metadata: { total_phases: 2 }
						}
					}
				}
			]);

			const state = get(planState);
			expect(state).not.toBeNull();
			expect(state!.goal).toBe('Build dashboard');
			expect(state!.phases).toHaveLength(2);
			expect(state!.phases[0].status).toBe('completed');
			expect(state!.phases[1].status).toBe('in_progress');
			expect(state!.currentPhaseId).toBe('phase_2');
		});
	});

	describe('human_input outside phases', () => {
		it('human_input calls are not grouped into phases', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Test',
							phases: ['Phase 1'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-info-1',
						tool_name: 'human_input',
						arguments: { prompt: 'Progress update' }
					}
				}
			]);

			const msgs = get(messages);
			// human_input tool_calls are rendered as regular tool_call messages
			expect(msgs).toHaveLength(1);
			expect(msgs[0].type).toBe('tool_call');
		});
	});

	describe('full workflow replay', () => {
		it('correctly groups tool calls across multiple phases', () => {
			replayEvents([
				{
					sequence: 1,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						arguments: {
							goal: 'Build dashboard',
							phases: ['Research', 'Design', 'Build'],
							current_phase_id: 'phase_1',
							brief: 'Plan'
						}
					}
				},
				{
					sequence: 2,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-plan-1',
						tool_name: 'mcp_update_plan',
						success: true
					}
				},
				{
					sequence: 3,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-s1',
						tool_name: 'mcp_search_google',
						arguments: { query: 'dashboards' }
					}
				},
				{
					sequence: 4,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-s1',
						tool_name: 'mcp_search_google',
						success: true,
						result: {},
						duration_ms: 500
					}
				},
				{
					sequence: 5,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-s2',
						tool_name: 'mcp_scrape_webpage',
						arguments: { url: 'https://example.com' }
					}
				},
				{
					sequence: 6,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-s2',
						tool_name: 'mcp_scrape_webpage',
						success: true,
						result: {},
						duration_ms: 1000
					}
				},
				{
					sequence: 7,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-advance-1',
						tool_name: 'mcp_advance_plan',
						arguments: {
							current_phase_id: 'phase_1',
							next_phase_id: 'phase_2',
							brief: 'Next'
						}
					}
				},
				{
					sequence: 8,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-advance-1',
						tool_name: 'mcp_advance_plan',
						success: true
					}
				},
				{
					sequence: 9,
					type: 'tool_call',
					data: {
						type: 'tool_call',
						tool_call_id: 'tc-e1',
						tool_name: 'edit_file',
						arguments: { path: 'design.md' }
					}
				},
				{
					sequence: 10,
					type: 'tool_result',
					data: {
						type: 'tool_result',
						tool_call_id: 'tc-e1',
						tool_name: 'edit_file',
						success: true,
						result: {},
						duration_ms: 200
					}
				}
			]);

			const msgs = get(messages);
			// Should have: search (phase_1), scrape (phase_1), edit (phase_2)
			expect(msgs).toHaveLength(3);
			expect((msgs[0] as ToolCallMessageType).phaseId).toBe('phase_1');
			expect((msgs[0] as ToolCallMessageType).toolName).toBe('mcp_search_google');
			expect((msgs[1] as ToolCallMessageType).phaseId).toBe('phase_1');
			expect((msgs[1] as ToolCallMessageType).toolName).toBe('mcp_scrape_webpage');
			expect((msgs[2] as ToolCallMessageType).phaseId).toBe('phase_2');
			expect((msgs[2] as ToolCallMessageType).toolName).toBe('edit_file');

			// Plan state should reflect transitions
			const state = get(planState)!;
			expect(state.phases[0].status).toBe('completed');
			expect(state.phases[1].status).toBe('in_progress');
			expect(state.phases[2].status).toBe('pending');
		});
	});
});

// --- PhaseGroup Component Tests ---

describe('PhaseGroup', () => {
	const basePhase = {
		id: 'phase_1',
		description: 'Research phase',
		status: 'in_progress' as const
	};

	const sampleToolCalls: ToolCallMessageType[] = [
		{
			type: 'tool_call',
			callId: 'tc-1',
			toolName: 'mcp_search_google',
			args: { query: 'test' },
			status: 'success',
			phaseId: 'phase_1',
			durationMs: 500
		},
		{
			type: 'tool_call',
			callId: 'tc-2',
			toolName: 'mcp_scrape_webpage',
			args: { url: 'https://example.com' },
			status: 'running',
			phaseId: 'phase_1'
		}
	];

	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('renders phase header with description', () => {
		render(PhaseGroup, {
			props: { phase: basePhase, toolCalls: sampleToolCalls }
		});
		expect(screen.getByText('Research phase')).toBeInTheDocument();
	});

	it('shows Working badge for active phase', () => {
		render(PhaseGroup, {
			props: { phase: basePhase, toolCalls: sampleToolCalls }
		});
		expect(screen.getByTestId('phase-status-badge')).toBeInTheDocument();
		expect(screen.getByText('Working')).toBeInTheDocument();
	});

	it('shows active phase indicator (pulsing dot)', () => {
		render(PhaseGroup, {
			props: { phase: basePhase, toolCalls: sampleToolCalls }
		});
		expect(screen.getByTestId('phase-indicator-active')).toBeInTheDocument();
	});

	it('shows completed phase indicator (checkmark)', () => {
		const completedPhase = { ...basePhase, status: 'completed' as const };
		render(PhaseGroup, {
			props: { phase: completedPhase, toolCalls: sampleToolCalls, defaultCollapsed: false }
		});
		expect(screen.getByTestId('phase-indicator-completed')).toBeInTheDocument();
	});

	it('shows pending phase indicator (empty dot)', () => {
		const pendingPhase = { ...basePhase, status: 'pending' as const };
		render(PhaseGroup, {
			props: { phase: pendingPhase, toolCalls: sampleToolCalls }
		});
		expect(screen.getByTestId('phase-indicator-pending')).toBeInTheDocument();
	});

	it('renders tool calls inside phase content', () => {
		render(PhaseGroup, {
			props: { phase: basePhase, toolCalls: sampleToolCalls }
		});
		expect(screen.getByTestId('phase-content')).toBeInTheDocument();
		expect(screen.getByText(/Searched/)).toBeInTheDocument();
		expect(screen.getByText(/Scraped/)).toBeInTheDocument();
	});

	it('active phase content is always visible', () => {
		render(PhaseGroup, {
			props: { phase: basePhase, toolCalls: sampleToolCalls }
		});
		expect(screen.getByTestId('phase-content')).toBeInTheDocument();
	});

	it('completed phase defaults to collapsed when defaultCollapsed is true', () => {
		const completedPhase = { ...basePhase, status: 'completed' as const };
		render(PhaseGroup, {
			props: { phase: completedPhase, toolCalls: sampleToolCalls, defaultCollapsed: true }
		});
		expect(screen.queryByTestId('phase-content')).not.toBeInTheDocument();
	});

	it('shows action count for collapsed completed phase', () => {
		const completedPhase = { ...basePhase, status: 'completed' as const };
		render(PhaseGroup, {
			props: { phase: completedPhase, toolCalls: sampleToolCalls, defaultCollapsed: true }
		});
		expect(screen.getByText('2 actions')).toBeInTheDocument();
	});

	it('shows singular action count when only 1 tool', () => {
		const completedPhase = { ...basePhase, status: 'completed' as const };
		render(PhaseGroup, {
			props: { phase: completedPhase, toolCalls: [sampleToolCalls[0]], defaultCollapsed: true }
		});
		expect(screen.getByText('1 action')).toBeInTheDocument();
	});

	it('toggles collapse on click for completed phase', async () => {
		const completedPhase = { ...basePhase, status: 'completed' as const };
		render(PhaseGroup, {
			props: { phase: completedPhase, toolCalls: sampleToolCalls, defaultCollapsed: true }
		});

		expect(screen.queryByTestId('phase-content')).not.toBeInTheDocument();

		await fireEvent.click(screen.getByTestId('phase-header'));
		expect(screen.getByTestId('phase-content')).toBeInTheDocument();
	});

	it('sets correct data attributes', () => {
		render(PhaseGroup, {
			props: { phase: basePhase, toolCalls: sampleToolCalls }
		});
		const group = screen.getByTestId('phase-group');
		expect(group).toHaveAttribute('data-phase-id', 'phase_1');
		expect(group).toHaveAttribute('data-phase-status', 'in_progress');
	});

	it('renders mcp_get_plan as PlanOverview', () => {
		const toolCallsWithPlan: ToolCallMessageType[] = [
			{
				type: 'tool_call',
				callId: 'tc-get-1',
				toolName: 'mcp_get_plan',
				args: { brief: 'Check plan' },
				status: 'success',
				phaseId: 'phase_1',
				result: {
					success: true,
					message: {
						goal: 'Build app',
						phases: [{ id: 'phase_1', description: 'Research', status: 'in_progress' }],
						current_phase_id: 'phase_1'
					}
				}
			}
		];
		render(PhaseGroup, {
			props: { phase: basePhase, toolCalls: toolCallsWithPlan }
		});
		expect(screen.getByTestId('plan-overview')).toBeInTheDocument();
	});
});

// --- PlanOverview Component Tests ---

describe('PlanOverview', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		resetStores();
	});

	const basePlanMessage: ToolCallMessageType = {
		type: 'tool_call',
		callId: 'tc-get-1',
		toolName: 'mcp_get_plan',
		args: { brief: 'Check plan' },
		status: 'success',
		result: {
			success: true,
			message: {
				goal: 'Build a dashboard',
				phases: [
					{ id: 'phase_1', description: 'Research', status: 'completed' },
					{ id: 'phase_2', description: 'Design', status: 'in_progress' },
					{ id: 'phase_3', description: 'Build', status: 'pending' }
				],
				current_phase_id: 'phase_2'
			}
		}
	};

	it('renders plan overview component', () => {
		render(PlanOverview, { props: { message: basePlanMessage } });
		expect(screen.getByTestId('plan-overview')).toBeInTheDocument();
	});

	it('shows Planning label and View Plan text', () => {
		render(PlanOverview, { props: { message: basePlanMessage } });
		expect(screen.getByText('Planning')).toBeInTheDocument();
		expect(screen.getByText('View Plan')).toBeInTheDocument();
	});

	it('shows goal text', () => {
		render(PlanOverview, { props: { message: basePlanMessage } });
		expect(screen.getByText('Build a dashboard')).toBeInTheDocument();
	});

	it('shows spinner when status is running', () => {
		const runningMessage = { ...basePlanMessage, status: 'running' as const, result: undefined };
		const { container } = render(PlanOverview, { props: { message: runningMessage } });
		const spinner = container.querySelector('.animate-spin');
		expect(spinner).toBeInTheDocument();
	});

	it('shows checkmark when status is success', () => {
		render(PlanOverview, { props: { message: basePlanMessage } });
		// The green checkmark polyline
		const checkmarks = screen.getByTestId('plan-overview-toggle').querySelectorAll('.text-success');
		expect(checkmarks.length).toBeGreaterThan(0);
	});

	it('details are hidden by default', () => {
		render(PlanOverview, { props: { message: basePlanMessage } });
		expect(screen.queryByTestId('plan-overview-details')).not.toBeInTheDocument();
	});

	it('expands to show phase list on click', async () => {
		render(PlanOverview, { props: { message: basePlanMessage } });

		await fireEvent.click(screen.getByTestId('plan-overview-toggle'));

		expect(screen.getByTestId('plan-overview-details')).toBeInTheDocument();
		const phaseItems = screen.getAllByTestId('plan-phase-item');
		expect(phaseItems).toHaveLength(3);
	});

	it('shows phase descriptions in expanded view', async () => {
		render(PlanOverview, { props: { message: basePlanMessage } });
		await fireEvent.click(screen.getByTestId('plan-overview-toggle'));

		expect(screen.getByText('Research')).toBeInTheDocument();
		expect(screen.getByText('Design')).toBeInTheDocument();
		expect(screen.getByText('Build')).toBeInTheDocument();
	});

	it('collapses on second click', async () => {
		render(PlanOverview, { props: { message: basePlanMessage } });
		await fireEvent.click(screen.getByTestId('plan-overview-toggle'));
		expect(screen.getByTestId('plan-overview-details')).toBeInTheDocument();

		await fireEvent.click(screen.getByTestId('plan-overview-toggle'));
		expect(screen.queryByTestId('plan-overview-details')).not.toBeInTheDocument();
	});
});

// --- ChatMessageList Phase Grouping Tests ---

describe('ChatMessageList - Phase grouping', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		resetStores();
	});

	it('groups consecutive tool_calls with same phaseId into a phase group', () => {
		// First set up planState so the phase info is available
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-1',
					tool_name: 'mcp_update_plan',
					arguments: {
						goal: 'Test',
						phases: ['Research phase'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			}
		]);

		const msgs: Message[] = [
			{
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_search_google',
				args: {},
				status: 'success',
				phaseId: 'phase_1'
			},
			{
				type: 'tool_call',
				callId: 'tc-2',
				toolName: 'mcp_scrape_webpage',
				args: {},
				status: 'running',
				phaseId: 'phase_1'
			}
		];

		render(ChatMessageList, { props: { messages: msgs } });
		expect(screen.getByTestId('phase-group')).toBeInTheDocument();
		expect(screen.getByText('Research phase')).toBeInTheDocument();
	});

	it('renders tool_calls without phaseId outside phase groups', () => {
		const msgs: Message[] = [
			{
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_search_google',
				args: {},
				status: 'success'
			}
		];

		render(ChatMessageList, { props: { messages: msgs } });
		expect(screen.queryByTestId('phase-group')).not.toBeInTheDocument();
		expect(screen.getByText('Searched the web')).toBeInTheDocument();
	});

	it('creates separate phase groups for different phaseIds', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-1',
					tool_name: 'mcp_update_plan',
					arguments: {
						goal: 'Test',
						phases: ['Research', 'Build'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			},
			{
				sequence: 2,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-advance-1',
					tool_name: 'mcp_advance_plan',
					arguments: {
						current_phase_id: 'phase_1',
						next_phase_id: 'phase_2',
						brief: 'Next'
					}
				}
			}
		]);

		const msgs: Message[] = [
			{
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_search_google',
				args: {},
				status: 'success',
				phaseId: 'phase_1'
			},
			{
				type: 'tool_call',
				callId: 'tc-2',
				toolName: 'edit_file',
				args: {},
				status: 'running',
				phaseId: 'phase_2'
			}
		];

		render(ChatMessageList, { props: { messages: msgs } });
		const groups = screen.getAllByTestId('phase-group');
		expect(groups).toHaveLength(2);
	});

	it('info messages break phase groups and render outside', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-1',
					tool_name: 'mcp_update_plan',
					arguments: {
						goal: 'Test',
						phases: ['Research'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			}
		]);

		const msgs: Message[] = [
			{
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_search_google',
				args: {},
				status: 'success',
				phaseId: 'phase_1'
			},
			{
				type: 'tool_call',
				callId: 'tc-info-1',
				toolName: 'human_input',
				args: { prompt: 'Progress update' },
				status: 'running',
				phaseId: 'phase_1'
			},
			{
				type: 'tool_call',
				callId: 'tc-2',
				toolName: 'mcp_scrape_webpage',
				args: {},
				status: 'running',
				phaseId: 'phase_1'
			}
		];

		render(ChatMessageList, { props: { messages: msgs } });
		// Should have 2 phase groups (split by the info message) + 1 info message
		const groups = screen.getAllByTestId('phase-group');
		expect(groups).toHaveLength(2);
		expect(screen.getByTestId('info-message')).toBeInTheDocument();
	});

	it('renders mixed content: user message, phase group, result', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-1',
					tool_name: 'mcp_update_plan',
					arguments: {
						goal: 'Test',
						phases: ['Research'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			}
		]);

		const msgs: Message[] = [
			{ type: 'user', text: 'Build me something' },
			{
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_search_google',
				args: {},
				status: 'success',
				phaseId: 'phase_1'
			},
			{
				type: 'assistant',
				text: 'Done!',
				isStreaming: false
			}
		];

		render(ChatMessageList, { props: { messages: msgs } });
		expect(screen.getByText('Build me something')).toBeInTheDocument();
		expect(screen.getByTestId('phase-group')).toBeInTheDocument();
		expect(screen.getByText('Done!')).toBeInTheDocument();
	});
});

// --- Unified tool names (new sandbox) ---

describe('SSE Service - Unified plan tool names', () => {
	beforeEach(() => {
		resetStores();
	});

	it('handles plan + update action', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-u1',
					tool_name: 'plan',
					arguments: {
						action: 'update',
						goal: 'Unified test',
						phases: ['Step A', 'Step B'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			}
		]);

		const state = get(planState);
		expect(state).not.toBeNull();
		expect(state!.goal).toBe('Unified test');
		expect(state!.phases).toHaveLength(2);
		expect(state!.currentPhaseId).toBe('phase_1');
		expect(state!.phases[0].status).toBe('in_progress');
	});

	it('handles plan + advance action', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-u1',
					tool_name: 'plan',
					arguments: {
						action: 'update',
						goal: 'Test',
						phases: ['Phase 1', 'Phase 2'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			},
			{
				sequence: 2,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-u2',
					tool_name: 'plan',
					arguments: {
						action: 'advance',
						current_phase_id: 'phase_1',
						next_phase_id: 'phase_2',
						brief: 'Advancing'
					}
				}
			}
		]);

		const state = get(planState)!;
		expect(state.currentPhaseId).toBe('phase_2');
		expect(state.phases[0].status).toBe('completed');
		expect(state.phases[1].status).toBe('in_progress');
	});

	it('handles plan + get action with tool_result', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-u3',
					tool_name: 'plan',
					arguments: { action: 'get', brief: 'Get plan' }
				}
			},
			{
				sequence: 2,
				type: 'tool_result',
				data: {
					type: 'tool_result',
					tool_call_id: 'tc-plan-u3',
					tool_name: 'plan',
					arguments: { action: 'get' },
					success: true,
					result: {
						success: true,
						message: {
							goal: 'Retrieved plan',
							phases: ['Phase X', 'Phase Y'],
							current_phase_id: 'phase_1'
						}
					}
				}
			}
		]);

		const state = get(planState);
		expect(state).not.toBeNull();
		expect(state!.goal).toBe('Retrieved plan');
		expect(state!.phases).toHaveLength(2);
	});

	it('does NOT add plan + update/advance to messages', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-u1',
					tool_name: 'plan',
					arguments: {
						action: 'update',
						goal: 'Test',
						phases: ['Phase 1'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			},
			{
				sequence: 2,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-u2',
					tool_name: 'plan',
					arguments: {
						action: 'advance',
						current_phase_id: 'phase_1',
						next_phase_id: 'phase_2',
						brief: 'Advance'
					}
				}
			}
		]);

		const msgs = get(messages);
		expect(msgs).toHaveLength(0);
	});

	it('assigns phaseId to unified tool calls', () => {
		replayEvents([
			{
				sequence: 1,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-plan-u1',
					tool_name: 'plan',
					arguments: {
						action: 'update',
						goal: 'Test',
						phases: ['Phase 1', 'Phase 2'],
						current_phase_id: 'phase_1',
						brief: 'Plan'
					}
				}
			},
			{
				sequence: 2,
				type: 'tool_call',
				data: {
					type: 'tool_call',
					tool_call_id: 'tc-search-1',
					tool_name: 'search',
					arguments: { action: 'web', queries: ['test'] }
				}
			}
		]);

		const msgs = get(messages);
		expect(msgs).toHaveLength(1);
		expect((msgs[0] as ToolCallMessageType).toolName).toBe('search');
		expect((msgs[0] as ToolCallMessageType).phaseId).toBe('phase_1');
	});
});
