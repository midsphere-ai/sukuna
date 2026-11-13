/**
 * Registry of every entry rendered by the chat UI playground.
 *
 * Only components that are live in the current production chat flow are
 * listed here. Every canvas entry maps to an exo-registered sandbox tool
 * (or tool family) — there is no fallback canvas.
 */

export type PlaygroundCategory = 'messages' | 'renderers' | 'input';

export type PlaygroundEntry = {
	id: string;
	category: PlaygroundCategory;
	label: string;
	description?: string;
};

export const CATEGORY_LABELS: Record<PlaygroundCategory, string> = {
	messages: 'Messages',
	renderers: 'Tool renderers',
	input: 'Input & header'
};

export const CATEGORY_ORDER: PlaygroundCategory[] = ['messages', 'renderers', 'input'];

export const ENTRIES: PlaygroundEntry[] = [
	// ── Messages ─────────────────────────────────────────────────────────
	{
		id: 'chat-message-list',
		category: 'messages',
		label: 'Simulated chat',
		description:
			'Full-shell chat with a realistic thread that exercises every message type AND every tool canvas. Click any tool call in the chat to pin its canvas in the computer panel on the right.'
	},
	{
		id: 'user-message',
		category: 'messages',
		label: 'UserMessage',
		description: 'User bubble with optional file attachments and edit/branch actions.'
	},
	{
		id: 'agent-message',
		category: 'messages',
		label: 'AgentMessage',
		description: 'Assistant text with markdown, streaming, and muted variants.'
	},
	{
		id: 'tool-call-message',
		category: 'messages',
		label: 'ToolCallMessage',
		description: 'Single tool call row — icon, label, and status.'
	},
	{
		id: 'error-message',
		category: 'messages',
		label: 'ErrorMessage',
		description: 'Error bubble with optional retry action.'
	},
	{
		id: 'hitl-message',
		category: 'messages',
		label: 'HitlMessage',
		description: 'Human-in-the-loop — multiple-choice, free text, and resolved states.'
	},
	{
		id: 'message-action-bar',
		category: 'messages',
		label: 'MessageActionBar',
		description: 'Copy / edit / branch icon row shown on hover inside UserMessage.'
	},
	{
		id: 'branch-point-indicator',
		category: 'messages',
		label: 'BranchPointIndicator',
		description: 'Inline marker shown at the message where a branch was created.'
	},

	// ── Tool renderers (via ToolCanvas dispatch) ─────────────────────────
	{
		id: 'canvas-terminal',
		category: 'renderers',
		label: 'Terminal',
		description: '`shell` tool — stdout/stderr with ANSI colors, exit code, session list.'
	},
	{
		id: 'canvas-diff',
		category: 'renderers',
		label: 'Diff',
		description: '`file` action=edit — unified diff with add/remove highlights and match badges.'
	},
	{
		id: 'canvas-code-viewer',
		category: 'renderers',
		label: 'Code viewer',
		description:
			'`file` action=read or `skill` action=get — read-only file view with language detection.'
	},
	{
		id: 'canvas-file-tree',
		category: 'renderers',
		label: 'File tree',
		description: '`file` action=view or `match` action=glob — directory listing with size hints.'
	},
	{
		id: 'canvas-file-status',
		category: 'renderers',
		label: 'File status',
		description: '`file` action=write/append — success/error card with byte count.'
	},
	{
		id: 'canvas-search',
		category: 'renderers',
		label: 'Search (web)',
		description: '`search` type=web — result list with title, snippet, display_link.'
	},
	{
		id: 'canvas-search-images',
		category: 'renderers',
		label: 'Search (images masonry)',
		description: '`search` type=images — CSS-columns masonry preserving natural aspect ratios.'
	},
	{
		id: 'canvas-browser',
		category: 'renderers',
		label: 'Browser',
		description: '`browser` gateway — screenshot, extracted page output, links panel.'
	},
	{
		id: 'canvas-database',
		category: 'renderers',
		label: 'Database',
		description: '`web_db` action=sql — sticky-header table with striped rows.'
	},
	{
		id: 'canvas-media',
		category: 'renderers',
		label: 'Media generation',
		description: '`generate` tool — img/video/audio by extension with prompt caption.'
	},
	{
		id: 'canvas-audio',
		category: 'renderers',
		label: 'Audio transcribe',
		description: '`perception` action=transcribe — waveform + transcription.'
	},
	{
		id: 'canvas-vision',
		category: 'renderers',
		label: 'Vision',
		description: '`perception` action=analyze — source + rendered analysis prose.'
	},
	{
		id: 'canvas-dev-server',
		category: 'renderers',
		label: 'Dev server',
		description: '`web_server` / `mobile_server` — status pill and clickable URL.'
	},
	{
		id: 'canvas-download',
		category: 'renderers',
		label: 'Download',
		description: '`file` action=download — filename, source URL, byte count.'
	},
	{
		id: 'canvas-reasoning',
		category: 'renderers',
		label: 'Reasoning',
		description: '`reasoning` tool — prose with highlighted final answer card.'
	},
	{
		id: 'canvas-settings',
		category: 'renderers',
		label: 'Settings',
		description: '`web_env` tool — env-vars KV list with secret redaction.'
	},
	{
		id: 'canvas-checkpoint',
		category: 'renderers',
		label: 'Checkpoint',
		description: '`git` tool — commit/list/rollback with hash chip and timeline.'
	},
	{
		id: 'canvas-artifact',
		category: 'renderers',
		label: 'Artifact',
		description: '`artifact` tool — html iframe, rendered markdown, inline svg, code block.'
	},
	{
		id: 'canvas-preview',
		category: 'renderers',
		label: 'Preview (port)',
		description: '`expose` tool — live sandboxed iframe of an exposed port.'
	},
	{
		id: 'canvas-project',
		category: 'renderers',
		label: 'Project setup',
		description:
			'`web_init` / `web_project` / `mobile_init` / `mobile_project` — type badge + project info.'
	},
	{
		id: 'canvas-km',
		category: 'renderers',
		label: 'Knowledge Manager',
		description:
			'`km_read` / `km_write` / `km_list` / `km_delete` / `km_nudge` — content, list, and confirmations.'
	},

	// ── Input & header ──────────────────────────────────────────────────
	{
		id: 'agent-activity-indicator',
		category: 'input',
		label: 'AgentActivityIndicator',
		description: 'Shows active tool / thinking / reconnecting state.'
	},
	{
		id: 'injection-queue-banner',
		category: 'input',
		label: 'InjectionQueueBanner',
		description: 'Banner shown when the user queues a message behind a running run.'
	}
];

export const DEFAULT_ENTRY_ID = 'chat-message-list';
