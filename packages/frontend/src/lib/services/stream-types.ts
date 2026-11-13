/**
 * Type definitions for SSE streaming and message rendering.
 * Extracted from sse.ts for reuse across StreamSession, SandboxClient, and page components.
 */

export type RunStatus =
	| 'idle'
	| 'connecting'
	| 'queued'
	| 'provisioning'
	| 'running'
	| 'completed'
	| 'failed'
	| 'cancelled'
	| 'waiting_for_input'
	| 'error';

export type StreamTransport = 'none' | 'direct' | 'shared';

export interface TextMessage {
	type: 'assistant';
	text: string;
	isStreaming: boolean;
	metadata?: Record<string, unknown>;
	started_by_name?: string;
	source_agent?: string;
}

export interface UserMessage {
	type: 'user';
	text: string;
	files?: string[];
	addons?: string[];
	mcps?: string[];
	clientId?: string;
	optimistic?: boolean;
	created_at?: string;
	sender_id?: string;
	sender_name?: string;
}

export interface ToolCallMessage {
	type: 'tool_call';
	callId: string;
	toolName: string;
	args: Record<string, unknown>;
	status: 'running' | 'success' | 'error';
	result?: unknown;
	error?: string;
	durationMs?: number;
	phaseId?: string;
	source_agent?: string;
}

/**
 * Narrowed shape of the result produced by the `expose` sandbox tool.
 * `framework` and `kind` are populated either by explicit kwargs on the tool
 * call or via auto-detection from `.sandbox-meta.json` in the project owning
 * the exposed dev-server port. Both fields are extensible — new frameworks
 * can be added without breaking consumers that only read the string.
 */
export interface ExposeToolResult {
	success: true;
	port: number;
	url: string;
	label?: string;
	framework?: 'next' | 'expo' | 'vite-svelte' | (string & {});
	kind?: 'web' | 'expo-web' | (string & {});
	message?: string;
}

export interface HitlMessage {
	type: 'hitl';
	requestId: string;
	prompt: string;
	choices?: string[];
	response?: string;
}

export interface ErrorMessage {
	type: 'error';
	message: string;
}

export interface StepMessage {
	type: 'step';
	stepNumber: number;
	status: 'started' | 'completed';
	maxSteps?: number;
	durationMs?: number;
}

export interface ReasoningMessage {
	type: 'reasoning';
	text: string;
	source_agent?: string;
}

export interface McpProgressMessage {
	type: 'mcp_progress';
	toolName: string;
	progress: number;
	total: number;
	message: string;
}

export interface PhaseInfo {
	id: string;
	description: string;
	status: 'pending' | 'in_progress' | 'completed';
	startedAt?: string;
	completedAt?: string;
}

export interface PlanState {
	goal: string;
	phases: PhaseInfo[];
	currentPhaseId: string;
}

export type Message =
	| UserMessage
	| TextMessage
	| ToolCallMessage
	| HitlMessage
	| ErrorMessage
	| StepMessage
	| ReasoningMessage
	| McpProgressMessage;

export interface StepInfo {
	stepNumber: number;
	status: 'started' | 'completed';
	maxSteps: number;
	durationMs?: number;
}

export interface TokenUsage {
	inputTokens: number;
	outputTokens: number;
	totalTokens: number;
	model: string;
}

export interface HitlRequest {
	requestId: string;
	prompt: string;
	choices?: string[];
}

export interface PersistedEvent {
	sequence: number;
	type?: string;
	event_type?: string;
	event?: string;
	data: unknown;
	created_at?: string;
}

export interface PaginationCursor {
	before_sequence?: number;
	before_created_at?: string;
}
