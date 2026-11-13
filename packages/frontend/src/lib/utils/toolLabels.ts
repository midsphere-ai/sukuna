export type ToolIcon =
	| 'folder'
	| 'file'
	| 'file-plus'
	| 'file-edit'
	| 'file-x'
	| 'file-arrow'
	| 'file-search'
	| 'terminal'
	| 'code'
	| 'search'
	| 'globe'
	| 'link'
	| 'camera'
	| 'download'
	| 'book'
	| 'mic'
	| 'eye'
	| 'video'
	| 'sparkles'
	| 'database'
	| 'server'
	| 'package'
	| 'git-save'
	| 'settings'
	| 'layout'
	| 'slides'
	| 'clipboard'
	| 'message'
	| 'brain'
	| 'shield'
	| 'paperclip'
	| 'wrench';

export type ServerCategory =
	| 'file'
	| 'terminal'
	| 'code'
	| 'search'
	| 'browser'
	| 'download'
	| 'audio'
	| 'vision'
	| 'web'
	| 'slides'
	| 'mobile'
	| 'media'
	| 'plan'
	| 'reading'
	| 'reasoning'
	| 'artifact'
	| 'unknown';

/** Safely extract the action string from tool args */
function getAction(args?: Record<string, unknown>): string {
	return typeof args?.action === 'string' ? (args.action as string) : '';
}

// MCP server name → category mapping (legacy: namespaced tools)
const SERVER_CATEGORY_MAP: Record<string, ServerCategory> = {
	file_system_service: 'file',
	code: 'code',
	audio: 'audio',
	search: 'search',
	download_server: 'download',
	unified_vision_video: 'vision',
	template_manager: 'web',
	presentation_server: 'slides',
	media_generation_server: 'media',
	communication_server: 'plan',
	reading: 'reading',
	reasoning: 'reasoning'
};

/**
 * Parse a namespaced tool name "mcp__{server}__{tool}"
 * Returns [serverName, toolFn] or null if not namespaced.
 */
function parseNamespacedTool(name: string): { server: string; tool: string } | null {
	const parts = name.split('__');
	if (parts.length >= 3) {
		return { server: parts[1].toLowerCase(), tool: parts.slice(2).join('__') };
	}
	return null;
}

/** Unified tool name → category (new sandbox tools) */
const UNIFIED_CATEGORY: Record<string, ServerCategory | ((action: string) => ServerCategory)> = {
	file: 'file',
	shell: (a) => (a === 'python' ? 'code' : 'terminal'),
	find: 'file',
	git: 'file',
	plan: 'plan',
	search: 'search',
	browse: 'browser',
	perception: (a) => (a === 'transcribe' ? 'audio' : 'vision'),
	media: 'media',
	webdev: 'web',
	mobiledev: 'mobile',
	reasoning: 'reasoning',
	skill: 'reading',
	slides: 'slides',
	artifact: 'artifact',
	expose_port: 'web'
};

export function getServerCategory(
	toolName: string,
	args?: Record<string, unknown>
): ServerCategory {
	// 0. Unified tool names (new sandbox)
	const unified = UNIFIED_CATEGORY[toolName];
	if (unified) {
		return typeof unified === 'function' ? unified(getAction(args)) : unified;
	}

	// 1. Try namespaced format: mcp__{server}__{tool}
	const parsed = parseNamespacedTool(toolName);
	if (parsed) {
		const cat = SERVER_CATEGORY_MAP[parsed.server];
		if (cat) return cat;
		const s = parsed.server;
		if (s.includes('file')) return 'file';
		if (s.includes('code') || s.includes('shell')) return 'code';
		if (s.includes('search') || s.includes('browser')) return 'search';
		if (s.includes('vision') || s.includes('video')) return 'vision';
		if (s.includes('audio')) return 'audio';
		if (s.includes('slide') || s.includes('presentation')) return 'slides';
		if (s.includes('mobile')) return 'mobile';
		if (s.includes('media') || s.includes('genai')) return 'media';
		if (s.includes('template') || s.includes('web')) return 'web';
		if (s.includes('download')) return 'download';
		if (s.includes('plan') || s.includes('communication')) return 'plan';
		if (s.includes('read')) return 'reading';
		if (s.includes('reason')) return 'reasoning';
	}

	// 2. Direct tool name matching (legacy)
	if (
		[
			'edit_file',
			'read_file',
			'read_reference_file',
			'list_reference_directory',
			'save_file',
			'append_file',
			'list_directory',
			'create_directory',
			'delete_file',
			'delete_this_file',
			'move_file',
			'copy_file',
			'search_files',
			'get_file_info',
			'submit_attachments'
		].includes(toolName)
	)
		return 'file';
	if (toolName.startsWith('mcp_run_shell') || toolName === 'mcp_run_shell_command')
		return 'terminal';
	if (
		toolName.startsWith('mcp_run_python') ||
		toolName === 'mcp_run_python_code' ||
		toolName.startsWith('mcp_code')
	)
		return 'code';
	if (
		toolName.startsWith('mcp_search') ||
		toolName === 'mcp_scrape_webpage' ||
		toolName === 'mcp_wikipedia'
	)
		return 'search';
	if (
		toolName.startsWith('mcp_browser') ||
		toolName === 'mcp_use_browser' ||
		toolName === 'mcp_scrape_url' ||
		toolName === 'mcp_screenshot_url'
	)
		return 'browser';
	if (toolName.startsWith('mcp_download')) return 'download';
	if (toolName.startsWith('mcp_audio') || toolName.startsWith('mcp_transcribe')) return 'audio';
	if (
		toolName.startsWith('mcp_vision') ||
		toolName.startsWith('mcp_video') ||
		toolName.startsWith('mcp_unified_vision')
	)
		return 'vision';
	if (
		toolName.startsWith('mcp_template') ||
		toolName.startsWith('mcp_dev_server') ||
		toolName.startsWith('mcp_sql')
	)
		return 'web';
	if (toolName.startsWith('mcp_slide') || toolName.startsWith('mcp_presentation')) return 'slides';
	if (toolName.startsWith('mcp_mobile')) return 'mobile';
	if (
		toolName.startsWith('mcp_generate') ||
		toolName.startsWith('mcp_media') ||
		toolName.startsWith('mcp_create_genai')
	)
		return 'media';
	if (
		toolName.startsWith('mcp_update_plan') ||
		toolName.startsWith('mcp_advance_plan') ||
		toolName.startsWith('mcp_get_plan')
	)
		return 'plan';
	if (toolName.startsWith('mcp_read') || toolName.startsWith('mcp_reading')) return 'reading';
	if (toolName.startsWith('mcp_reason') || toolName.startsWith('mcp_validate')) return 'reasoning';
	return 'unknown';
}

// Category → fallback icon
const CATEGORY_ICON_MAP: Record<ServerCategory, ToolIcon> = {
	file: 'file',
	terminal: 'terminal',
	code: 'code',
	search: 'search',
	browser: 'globe',
	download: 'download',
	audio: 'mic',
	vision: 'eye',
	web: 'layout',
	slides: 'slides',
	mobile: 'server',
	media: 'sparkles',
	plan: 'clipboard',
	reading: 'book',
	reasoning: 'brain',
	artifact: 'sparkles',
	unknown: 'wrench'
};

/** Get icon for a unified tool based on its action */
function getUnifiedToolIcon(toolName: string, action: string): ToolIcon | null {
	switch (toolName) {
		case 'file':
			if (action === 'view') return 'folder';
			if (action === 'read' || action === 'read_resource') return 'file';
			if (action === 'write' || action === 'append') return 'file-plus';
			if (action === 'edit') return 'file-edit';
			if (action === 'delete') return 'file-x';
			if (action === 'move') return 'file-arrow';
			if (action === 'download') return 'download';
			return 'file';
		case 'shell':
			return action === 'python' ? 'code' : 'terminal';
		case 'find':
			return 'file-search';
		case 'git':
			return 'git-save';
		case 'plan':
			return 'clipboard';
		case 'search':
			if (action.startsWith('wikipedia')) return 'book';
			return 'search';
		case 'browse':
			return 'globe';
		case 'perception':
			if (action === 'transcribe') return 'mic';
			return 'eye';
		case 'media':
			if (action.includes('video')) return 'video';
			return 'sparkles';
		case 'webdev':
			if (action === 'sql') return 'database';
			if (action.includes('server')) return 'server';
			if (action === 'install_deps') return 'package';
			if (action.includes('env')) return 'settings';
			return 'layout';
		case 'mobiledev':
			if (action.includes('server')) return 'server';
			return 'server';
		case 'reasoning':
			return action === 'guard' ? 'shield' : 'brain';
		case 'skill':
			return 'book';
		case 'slides':
			return 'slides';
		case 'artifact':
			return 'sparkles';
		case 'expose_port':
			return 'globe';
	}
	return null;
}

export function getToolIcon(toolName: string, args?: Record<string, unknown>): ToolIcon {
	// 0. Unified tool names
	const unifiedIcon = getUnifiedToolIcon(toolName, getAction(args));
	if (unifiedIcon) return unifiedIcon;

	const parsed = parseNamespacedTool(toolName);
	const tool = parsed ? parsed.tool.toLowerCase() : toolName.toLowerCase();

	// File system operations
	if (/list_directory|create_directory|list_reference_directory/.test(tool)) return 'folder';
	if (/^read_file$|^read_reference_file$|^get_file_info$/.test(tool)) return 'file';
	if (/^save_file$|^append_file$/.test(tool)) return 'file-plus';
	if (/^edit_file$/.test(tool)) return 'file-edit';
	if (/delete/.test(tool) && /file/.test(tool)) return 'file-x';
	if (/^move_file$|^copy_file$/.test(tool)) return 'file-arrow';
	if (/^search_files$/.test(tool)) return 'file-search';
	if (/^submit_attachments$/.test(tool)) return 'paperclip';

	// Code & terminal
	if (/run_shell|run_local_command/.test(tool)) return 'terminal';
	if (/run_python|^code$/.test(tool)) return 'code';

	// Search & browser
	if (/search_google_image|image_search/.test(tool)) return 'search';
	if (/search_google|search_wikipedia/.test(tool)) return 'search';
	if (/use_browser/.test(tool)) return 'globe';
	if (/scrape/.test(tool)) return 'link';
	if (/screenshot/.test(tool)) return 'camera';

	// Download
	if (/download/.test(tool)) return 'download';

	// Wikipedia / reading
	if (/wikipedia|read_resource/.test(tool)) return 'book';

	// Audio
	if (/audio|transcri/.test(tool) && !/video/.test(tool)) return 'mic';

	// Vision
	if (/visual_question|compare_multiple_image/.test(tool)) return 'eye';
	if (/video|keyframe/.test(tool)) return 'video';

	// AI generation
	if (/genai|generate|media/.test(tool)) return 'sparkles';

	// Web / templates
	if (/template|copy_web/.test(tool)) return 'layout';
	if (/sql|database/.test(tool)) return 'database';
	if (/dev_server|server_status|start_dev|stop_dev|restart_dev/.test(tool)) return 'server';
	if (/install_dep/.test(tool)) return 'package';
	if (/checkpoint/.test(tool)) return 'git-save';
	if (/env_variable|add_env|remove_env|list_env|set_current/.test(tool)) return 'settings';

	// Slides
	if (/slide|presentation/.test(tool)) return 'slides';

	// Plan & communication
	if (/plan|advance_plan|update_plan|get_plan/.test(tool)) return 'clipboard';
	if (/message|schedule/.test(tool)) return 'message';

	// Reasoning
	if (/guard|validate/.test(tool)) return 'shield';
	if (/reason/.test(tool)) return 'brain';

	// Mobile
	if (/mobile/.test(tool)) return 'server';

	// List operations
	if (/^list_/.test(tool)) return 'folder';

	// Fall back to category icon
	const category = getServerCategory(toolName, args);
	return CATEGORY_ICON_MAP[category];
}

export type CanvasType =
	| 'terminal'
	| 'diff'
	| 'code-viewer'
	| 'browser'
	| 'search'
	| 'file-tree'
	| 'file-status'
	| 'database'
	| 'dev-server'
	| 'media'
	| 'vision'
	| 'audio'
	| 'download'
	| 'reasoning'
	| 'settings'
	| 'checkpoint'
	| 'artifact'
	| 'preview'
	| 'project'
	| 'km';

/**
 * Get the canvas type for an exo-registered tool.
 *
 * This is an exhaustive switch over the exo tool registry — every tool
 * that is not in SILENT_TOOLS must map to exactly one canvas. There is no
 * fallback: returning `null` signals "no UI for this tool", which should
 * only happen for silent tools (already filtered in sse.ts) or a tool that
 * has been added to the sandbox without a corresponding frontend canvas.
 *
 * In dev mode, unmapped tools log a console warning so the gap is loud.
 */
export function getCanvasType(toolName: string, args?: Record<string, unknown>): CanvasType | null {
	const action = getAction(args);

	// Browser gateway tool + its 14 sub-tools (browser_view, browser_click, …)
	if (toolName === 'browser' || toolName.startsWith('browser_')) return 'browser';

	// Knowledge Manager: km_read, km_write, km_list, km_delete, km_nudge
	if (toolName.startsWith('km_')) return 'km';

	// Project setup: web_init, web_project, mobile_init, mobile_project
	if (
		toolName === 'web_init' ||
		toolName === 'web_project' ||
		toolName === 'mobile_init' ||
		toolName === 'mobile_project'
	)
		return 'project';

	switch (toolName) {
		case 'file':
			if (action === 'edit') return 'diff';
			if (action === 'read' || action === 'read_resource') return 'code-viewer';
			if (action === 'view') return 'file-tree';
			if (action === 'download') return 'download';
			return 'file-status';

		case 'match':
			return 'file-tree';

		case 'shell':
			return 'terminal';

		case 'search':
			return 'search';

		case 'generate':
			return 'media';

		case 'perception':
			return action === 'transcribe' ? 'audio' : 'vision';

		case 'web_db':
			return 'database';

		case 'web_server':
		case 'mobile_server':
			return 'dev-server';

		case 'web_env':
			return 'settings';

		case 'expose':
			return 'preview';

		case 'git':
			return 'checkpoint';

		case 'artifact':
			return 'artifact';

		case 'reasoning':
			return 'reasoning';

		case 'skill':
			return 'code-viewer';

		// Silent tools — filtered upstream in sse.ts, but return null as a safety net.
		case 'plan':
		case 'schedule':
		case 'human_input':
		case 'submit_attachments':
			return null;
	}

	if (import.meta.env.DEV) {
		// eslint-disable-next-line no-console
		console.warn(
			`[toolLabels] no canvas for exo tool "${toolName}" — add a case to getCanvasType()`
		);
	}
	return null;
}

/** Tools that should NOT auto-open the canvas panel */
export const SILENT_TOOLS = new Set([
	// Unified
	'plan',
	// Legacy
	'mcp_update_plan',
	'mcp_advance_plan',
	'mcp_get_plan',
	// Unchanged
	'human_input',
	'submit_attachments',
	'schedule'
]);

export function isEditorEligibleTool(toolName: string): boolean {
	if (toolName === 'webdev' || toolName === 'mobiledev') return true;
	const category = getServerCategory(toolName);
	return category === 'web' || category === 'mobile';
}

export function truncate(s: string, max: number): string {
	return s.length > max ? s.slice(0, max - 1) + '\u2026' : s;
}

/** Get a human-readable label for a unified tool + action */
function getUnifiedActionLabel(toolName: string, args: Record<string, unknown>): string | null {
	const action = getAction(args);
	const p = (args.path || args.file_path || args.filename || '') as string;
	const name = p.split('/').pop() || p;

	switch (toolName) {
		case 'file':
			if (action === 'read' || action === 'read_resource')
				return name ? `Read ${name}` : 'Read file';
			if (action === 'edit') return name ? `Edited ${name}` : 'Edited file';
			if (action === 'write') return name ? `Saved ${name}` : 'Saved file';
			if (action === 'view') {
				const dir = (p || '').split('/').pop() || p;
				return dir ? `Listed ${dir}` : 'Listed directory';
			}
			if (action === 'delete') return name ? `Deleted ${name}` : 'Deleted file';
			if (action === 'move') return 'Moved file';
			if (action === 'append') return name ? `Appended to ${name}` : 'Appended to file';
			if (action === 'download') return 'Downloaded file';
			return 'File operation';
		case 'shell': {
			if (action === 'python') return 'Ran Python code';
			const cmd = (args.command || '') as string;
			if (action === 'exec') return cmd ? truncate(cmd, 45) : 'Ran shell command';
			if (action === 'view') return 'Viewed session';
			if (action === 'output') return 'Read output';
			if (action === 'wait') return 'Waiting for process';
			if (action === 'send') return 'Sent input';
			if (action === 'kill') return 'Killed process';
			return cmd ? truncate(cmd, 45) : 'Ran command';
		}
		case 'find': {
			const pattern = (args.regex || args.scope || '') as string;
			if (action === 'grep')
				return pattern ? `Searched "${truncate(pattern, 35)}"` : 'Searched content';
			return 'Searched files';
		}
		case 'git':
			if (action === 'checkpoint') return 'Git checkpoint';
			if (action === 'list') return 'Listed checkpoints';
			if (action === 'rollback') return 'Rolled back';
			return 'Git operation';
		case 'plan':
			return 'Updated plan';
		case 'search': {
			const rawQ = args.queries;
			const q = ((Array.isArray(rawQ) ? rawQ.join(', ') : typeof rawQ === 'string' ? rawQ : null) ||
				args.query ||
				'') as string;
			if (action === 'images') return q ? `Image search "${truncate(q, 35)}"` : 'Searched images';
			if (action === 'youtube_video') return 'Searched YouTube';
			if (action.startsWith('wikipedia')) return 'Looked up Wikipedia';
			return q ? `Searched "${truncate(q, 35)}"` : 'Searched the web';
		}
		case 'browse': {
			const url = (args.url || '') as string;
			if (url) {
				try {
					return `Browsed ${new URL(url).hostname}`;
				} catch {
					/* */
				}
			}
			return 'Used browser';
		}
		case 'perception':
			if (action === 'analyze') return 'Analyzed visual';
			if (action === 'transcribe') return 'Transcribed audio';
			if (action === 'compare') return 'Compared images';
			if (action === 'extract') return 'Extracted content';
			return 'Processed media';
		case 'media':
			if (action === 'create_image' || action === 'create_image_with_refs')
				return 'Generated image';
			if (action === 'edit_image') return 'Edited image';
			if (action.includes('video')) return 'Generated video';
			if (action === 'download_gcs') return 'Downloaded media';
			return 'Generated media';
		case 'webdev':
			if (action === 'sql') return 'Ran SQL query';
			if (action === 'start_server' || action === 'stop_server' || action === 'restart_server')
				return 'Dev server action';
			if (action === 'init' || action === 'set_project') return 'Set up web project';
			if (action === 'install_deps') return 'Installed dependencies';
			if (action.includes('env')) return 'Set environment';
			if (action === 'server_status') return 'Checked server status';
			if (action === 'exec') return 'Ran command';
			return 'Web dev action';
		case 'mobiledev':
			if (action === 'start_server' || action === 'stop_server') return 'Mobile server action';
			if (action === 'init' || action === 'set_project') return 'Set up mobile project';
			if (action === 'exec') return 'Ran command';
			return 'Mobile action';
		case 'reasoning':
			if (action === 'guard') return 'Guard check';
			return 'Reasoning';
		case 'skill':
			return 'Loaded skill';
		case 'slides':
			if (action === 'create') return 'Created slides';
			if (action === 'export') return 'Exported slides';
			return 'Updated slides';
		case 'artifact': {
			const t = (args.title || '') as string;
			if (action === 'update') return t ? `Updated "${truncate(t, 30)}"` : 'Updated artifact';
			return t ? `Created "${truncate(t, 30)}"` : 'Created artifact';
		}
		case 'expose_port': {
			const port = args.port as string | number;
			const lbl = (args.label || '') as string;
			if (lbl) return `Exposed port ${port} (${truncate(lbl, 30)})`;
			if (port) return `Exposed port ${port}`;
			return 'Exposed port';
		}
	}
	return null;
}

export function getActionLabel(toolName: string, args?: Record<string, unknown>): string {
	const a = args || {};
	if (a._exo_tool_brief && typeof a._exo_tool_brief === 'string')
		return a._exo_tool_brief as string;

	// Unified tools
	const unifiedLabel = getUnifiedActionLabel(toolName, a);
	if (unifiedLabel) return unifiedLabel;

	// Legacy tool names
	if (toolName === 'read_file' || toolName === 'read_reference_file') {
		const p = (a.path || a.file_path || a.filename || '') as string;
		const name = p.split('/').pop() || p;
		return name ? `Read ${name}` : 'Read file';
	}
	if (toolName === 'edit_file') {
		const p = (a.path || a.file_path || a.filename || '') as string;
		const name = p.split('/').pop() || p;
		return name ? `Edited ${name}` : 'Edited file';
	}
	if (toolName === 'save_file') {
		const p = (a.path || a.file_path || a.filename || '') as string;
		const name = p.split('/').pop() || p;
		return name ? `Saved ${name}` : 'Saved file';
	}
	if (toolName === 'list_directory') {
		const p = (a.path || '') as string;
		const name = p.split('/').pop() || p;
		return name ? `Listed ${name}` : 'Listed directory';
	}
	if (toolName === 'create_directory') return 'Created directory';
	if (toolName === 'delete_file') {
		const p = (a.path || a.file_path || '') as string;
		const name = p.split('/').pop() || p;
		return name ? `Deleted ${name}` : 'Deleted file';
	}
	if (toolName === 'move_file' || toolName === 'copy_file')
		return toolName === 'move_file' ? 'Moved file' : 'Copied file';
	if (toolName === 'search_files') {
		const q = (a.query || a.pattern || '') as string;
		return q ? `Searched "${truncate(q, 35)}"` : 'Searched files';
	}
	if (toolName === 'get_file_info') return 'Checked file info';
	if (toolName.startsWith('mcp_run_shell') || toolName === 'mcp_run_shell_command') {
		const cmd = (a.command || '') as string;
		return cmd ? truncate(cmd, 45) : 'Ran shell command';
	}
	if (toolName.startsWith('mcp_run_python') || toolName === 'mcp_run_python_code')
		return 'Ran Python code';
	if (toolName.startsWith('mcp_code')) return 'Ran code';
	if (toolName === 'mcp_search_google' || toolName.startsWith('mcp_search')) {
		const q = (a.query || '') as string;
		return q ? `Searched "${truncate(q, 35)}"` : 'Searched the web';
	}
	if (toolName === 'mcp_image_search' || toolName === 'mcp_search_google_images') {
		const q = (a.query || '') as string;
		return q ? `Image search "${truncate(q, 35)}"` : 'Searched images';
	}
	if (toolName === 'mcp_scrape_webpage') {
		const url = (a.url || '') as string;
		if (url) {
			try {
				return `Scraped ${new URL(url).hostname}`;
			} catch {
				/* */
			}
		}
		return 'Scraped webpage';
	}
	if (toolName === 'mcp_wikipedia') return 'Looked up Wikipedia';
	if (toolName.startsWith('mcp_browser')) {
		const url = (a.url || '') as string;
		if (url) {
			try {
				return `Browsed ${new URL(url).hostname}`;
			} catch {
				/* */
			}
		}
		return 'Used browser';
	}
	if (toolName.startsWith('mcp_download')) return 'Downloaded file';
	if (toolName.startsWith('mcp_audio') || toolName.startsWith('mcp_transcribe'))
		return 'Processed audio';
	if (
		toolName.startsWith('mcp_vision') ||
		toolName.startsWith('mcp_video') ||
		toolName.startsWith('mcp_unified_vision')
	)
		return 'Analyzed visual';
	if (toolName.startsWith('mcp_template')) return 'Generated from template';
	if (toolName.startsWith('mcp_dev_server')) return 'Dev server action';
	if (toolName.startsWith('mcp_env')) return 'Set environment';
	if (toolName.startsWith('mcp_git_checkpoint')) return 'Git checkpoint';
	if (toolName.startsWith('mcp_sql')) return 'Ran SQL query';
	if (toolName.startsWith('mcp_slide') || toolName.startsWith('mcp_presentation'))
		return 'Updated slides';
	if (toolName.startsWith('mcp_mobile')) return 'Mobile action';
	if (toolName.startsWith('mcp_generate') || toolName.startsWith('mcp_media'))
		return 'Generated media';
	if (
		toolName.startsWith('mcp_update_plan') ||
		toolName.startsWith('mcp_advance_plan') ||
		toolName.startsWith('mcp_get_plan')
	)
		return 'Updated plan';
	if (toolName.startsWith('mcp_read') || toolName.startsWith('mcp_reading')) return 'Read document';
	if (toolName.startsWith('mcp_reason') || toolName.startsWith('mcp_validate')) return 'Reasoning';
	if (toolName === 'submit_attachments') {
		const fileList = a.files as string[] | undefined;
		if (fileList && fileList.length > 0) {
			const name = (fileList[0] as string).split('/').pop() || fileList[0];
			return fileList.length === 1 ? `Attached ${name}` : `Attached ${fileList.length} files`;
		}
		return 'Submitted attachments';
	}
	let fallbackName = toolName;
	if (fallbackName.startsWith('mcp_')) fallbackName = fallbackName.slice(4);
	return fallbackName
		.split('_')
		.map((w) => w.charAt(0).toUpperCase() + w.slice(1))
		.join(' ');
}
