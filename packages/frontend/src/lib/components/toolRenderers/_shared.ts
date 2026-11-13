// Shared helpers for tool renderers. Keep this small — only utilities that
// more than one renderer actually needs. Do not add component abstractions
// here; each renderer stays self-contained.

export interface ToolResultEnvelope {
	success?: boolean;
	message?: string;
	error?: string;
	hint?: string;
}

/**
 * Parse the universal tool result envelope. Sandbox tools return dicts
 * with `success`/`message` on the happy path and `success: false`/`error`/`hint`
 * on failures. Some older tools return primitives (string/array/bool); this
 * coerces those too so renderers don't need to special-case them.
 */
export function parseEnvelope(r: unknown): ToolResultEnvelope {
	if (r == null) return {};
	if (typeof r === 'string') return { success: true, message: r };
	if (typeof r === 'boolean') return { success: r };
	if (Array.isArray(r)) return { success: true };
	if (typeof r !== 'object') return {};
	const obj = r as Record<string, unknown>;
	return {
		success: typeof obj.success === 'boolean' ? obj.success : undefined,
		message: typeof obj.message === 'string' ? (obj.message as string) : undefined,
		error: typeof obj.error === 'string' ? (obj.error as string) : undefined,
		hint: typeof obj.hint === 'string' ? (obj.hint as string) : undefined
	};
}

export function formatBytes(bytes?: number | null): string {
	if (bytes == null || !isFinite(bytes) || bytes < 0) return '';
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

// ANSI SGR → inline CSS using theme tokens so colors adapt to light/dark mode.
// Named colors map to the design-system palette rather than hardcoded hex.
const ANSI_STYLES: Record<string, string> = {
	'0': '',
	'1': 'font-weight: 500',
	'2': 'opacity:0.65',
	'3': 'font-style:italic',
	'4': 'text-decoration:underline',
	'22': 'font-weight:400',
	'23': 'font-style:normal',
	'24': 'text-decoration:none',
	'30': 'color:var(--ms-subtle-text)',
	'31': 'color:var(--ms-danger)',
	'32': 'color:var(--ms-green)',
	'33': 'color:var(--ms-warning)',
	'34': 'color:var(--ms-blue)',
	'35': 'color:#a65fa0',
	'36': 'color:#3a8b94',
	'37': 'color:var(--ms-dark)',
	'39': 'color:inherit',
	'90': 'color:var(--ms-subtle-text)',
	'91': 'color:var(--ms-danger)',
	'92': 'color:var(--ms-green)',
	'93': 'color:var(--ms-warning)',
	'94': 'color:var(--ms-blue)',
	'95': 'color:#a65fa0',
	'96': 'color:#3a8b94',
	'97': 'color:var(--ms-dark)'
};

/**
 * Convert ANSI SGR escape sequences into HTML spans. Strips non-color
 * ANSI escapes (cursor moves, clears) that would otherwise leak as garbage.
 * HTML entities in the input are escaped before span wrapping, so output is
 * safe to pass through `{@html ...}` in Svelte.
 */
export function ansiToHtml(text: string): string {
	if (!text) return '';
	let escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
	let openSpans = 0;
	// eslint-disable-next-line no-control-regex
	escaped = escaped.replace(/\x1b\[([0-9;]*)m/g, (_m, codes: string) => {
		if (codes === '' || codes === '0') {
			if (openSpans > 0) {
				openSpans -= 1;
				return '</span>';
			}
			return '';
		}
		const styles = codes
			.split(';')
			.map((c) => ANSI_STYLES[c] || '')
			.filter(Boolean)
			.join(';');
		if (!styles) return '';
		openSpans += 1;
		return `<span style="${styles}">`;
	});
	// eslint-disable-next-line no-control-regex
	escaped = escaped.replace(/\x1b\[[0-9;?]*[A-HJKSTfimnsu]/g, '');
	while (openSpans > 0) {
		escaped += '</span>';
		openSpans -= 1;
	}
	return escaped;
}

/** Language label from filename extension. Used by code-viewer and file-tree. */
const EXT_TO_LANG: Record<string, string> = {
	ts: 'typescript',
	tsx: 'typescript',
	js: 'javascript',
	jsx: 'javascript',
	py: 'python',
	rb: 'ruby',
	rs: 'rust',
	go: 'go',
	java: 'java',
	c: 'c',
	cpp: 'cpp',
	h: 'c',
	hpp: 'cpp',
	cs: 'csharp',
	html: 'html',
	css: 'css',
	scss: 'scss',
	less: 'less',
	json: 'json',
	yaml: 'yaml',
	yml: 'yaml',
	toml: 'toml',
	xml: 'xml',
	svg: 'xml',
	md: 'markdown',
	mdx: 'markdown',
	sh: 'bash',
	bash: 'bash',
	zsh: 'bash',
	sql: 'sql',
	graphql: 'graphql',
	svelte: 'svelte',
	vue: 'vue',
	dockerfile: 'dockerfile',
	makefile: 'makefile'
};

export function detectLanguage(filename: string): string {
	if (!filename) return 'plaintext';
	const ext = filename.split('.').pop()?.toLowerCase() ?? '';
	return EXT_TO_LANG[ext] ?? 'plaintext';
}

/** Truncate a long path to the last N segments — "…/foo/bar/baz.ts". */
export function truncatePath(path: string, segments = 3): string {
	if (!path) return '';
	const parts = path.split('/').filter(Boolean);
	if (parts.length <= segments) return path;
	return '…/' + parts.slice(-segments).join('/');
}
