import type { Message } from '$services/sse';

/* Canonical font stacks — keep in sync with app.css @theme tokens */
const FONT_SANS =
	"'Inter Tight', -apple-system, system-ui, 'Segoe UI', 'Helvetica Neue', Helvetica, Ubuntu, Roboto, Noto, Arial, sans-serif";
const FONT_MONO =
	"'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace";

function formatTimestamp(date: Date): string {
	return date.toLocaleString('en-GB', {
		year: 'numeric',
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit'
	});
}

function stripMcpPrefix(toolName: string): string {
	return toolName.replace(/^mcp_/, '').replace(/_/g, ' ');
}

function truncate(text: string, maxLen: number): string {
	if (text.length <= maxLen) return text;
	return text.slice(0, maxLen) + '...';
}

function toolArgsSummary(args: Record<string, unknown>): string {
	const priorityKeys = [
		'path',
		'file_path',
		'filename',
		'command',
		'query',
		'url',
		'code',
		'brief',
		'message',
		'title'
	];
	for (const key of priorityKeys) {
		if (args[key] && typeof args[key] === 'string') {
			return truncate(args[key] as string, 120);
		}
	}
	const keys = Object.keys(args);
	if (keys.length === 0) return '';
	return truncate(JSON.stringify(args), 120);
}

// --- Markdown Export ---

function messageToMarkdown(msg: Message): string {
	switch (msg.type) {
		case 'user':
			return `### You\n\n${msg.text}${msg.files?.length ? `\n\n**Attached files:** ${msg.files.join(', ')}` : ''}`;
		case 'assistant':
			return `### Assistant\n\n${msg.text}`;
		case 'tool_call': {
			const name = stripMcpPrefix(msg.toolName);
			const summary = toolArgsSummary(msg.args);
			const status = msg.status === 'error' ? ' (failed)' : '';
			let block = `> **Tool:** ${name}${status}`;
			if (summary) block += `\n> ${summary}`;
			if (msg.error) block += `\n> **Error:** ${msg.error}`;
			if (msg.result && typeof msg.result === 'string') {
				block += `\n> **Result:** ${truncate(msg.result, 200)}`;
			}
			return block;
		}
		case 'error':
			return `> **Error:** ${msg.message}`;
		case 'hitl':
			return `> **Human Input Required:** ${msg.prompt}${msg.response ? `\n> **Response:** ${msg.response}` : ''}`;
		case 'step':
			return '';
		case 'reasoning':
			return `> *Reasoning:* ${truncate(msg.text, 200)}`;
		case 'mcp_progress':
			return '';
		default:
			return '';
	}
}

export function exportSingleMessage(msg: Message): string {
	return messageToMarkdown(msg);
}

export function exportToMarkdown(title: string, messages: Message[], dateCreated?: string): string {
	const header = `# ${title}\n\n*Exported from Jatayu AI${dateCreated ? ` · Created ${formatTimestamp(new Date(dateCreated))}` : ''}*\n\n---\n`;

	const body = messages.map(messageToMarkdown).filter(Boolean).join('\n\n');

	return `${header}\n${body}\n`;
}

// --- Plain Text Export ---

function messageToPlainText(msg: Message): string {
	switch (msg.type) {
		case 'user':
			return `[You]\n${msg.text}${msg.files?.length ? `\nAttached files: ${msg.files.join(', ')}` : ''}`;
		case 'assistant':
			return `[Assistant]\n${msg.text}`;
		case 'tool_call': {
			const name = stripMcpPrefix(msg.toolName);
			const summary = toolArgsSummary(msg.args);
			const status = msg.status === 'error' ? ' (failed)' : '';
			let line = `[Tool: ${name}${status}]`;
			if (summary) line += ` ${summary}`;
			if (msg.error) line += `\nError: ${msg.error}`;
			return line;
		}
		case 'error':
			return `[Error] ${msg.message}`;
		case 'hitl':
			return `[Human Input Required] ${msg.prompt}${msg.response ? `\nResponse: ${msg.response}` : ''}`;
		case 'reasoning':
			return `[Reasoning] ${truncate(msg.text, 200)}`;
		default:
			return '';
	}
}

export function exportToPlainText(
	title: string,
	messages: Message[],
	dateCreated?: string
): string {
	const header = `${title}\nExported from Jatayu AI${dateCreated ? ` · Created ${formatTimestamp(new Date(dateCreated))}` : ''}\n${'='.repeat(60)}\n`;

	const body = messages.map(messageToPlainText).filter(Boolean).join('\n\n---\n\n');

	return `${header}\n${body}\n`;
}

// --- PDF Export ---

function escapeHtml(text: string): string {
	return text
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

function simpleMarkdownToHtml(text: string): string {
	return escapeHtml(text)
		.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
		.replace(/\*(.+?)\*/g, '<em>$1</em>')
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/```[\s\S]*?```/g, (match) => {
			const code = match.replace(/```\w*\n?/, '').replace(/```$/, '');
			return `<pre><code>${code}</code></pre>`;
		})
		.replace(/\n/g, '<br>');
}

function messageToPdfHtml(msg: Message): string {
	switch (msg.type) {
		case 'user':
			return `<div class="message user-message">
				<div class="role">You</div>
				<div class="content">${simpleMarkdownToHtml(msg.text)}</div>
				${msg.files?.length ? `<div class="files">Attached: ${escapeHtml(msg.files.join(', '))}</div>` : ''}
			</div>`;
		case 'assistant':
			return `<div class="message assistant-message">
				<div class="role">Assistant</div>
				<div class="content">${simpleMarkdownToHtml(msg.text)}</div>
			</div>`;
		case 'tool_call': {
			const name = stripMcpPrefix(msg.toolName);
			const summary = toolArgsSummary(msg.args);
			return `<div class="message tool-message">
				<div class="tool-badge">${escapeHtml(name)}${msg.status === 'error' ? ' <span class="error-badge">failed</span>' : ''}</div>
				${summary ? `<div class="tool-summary">${escapeHtml(summary)}</div>` : ''}
				${msg.error ? `<div class="tool-error">${escapeHtml(msg.error)}</div>` : ''}
			</div>`;
		}
		case 'error':
			return `<div class="message error-message">
				<div class="error-text">${escapeHtml(msg.message)}</div>
			</div>`;
		case 'hitl':
			return `<div class="message hitl-message">
				<div class="role">Human Input</div>
				<div class="content">${escapeHtml(msg.prompt)}</div>
				${msg.response ? `<div class="hitl-response">Response: ${escapeHtml(msg.response)}</div>` : ''}
			</div>`;
		default:
			return '';
	}
}

export function exportToPdfHtml(title: string, messages: Message[], dateCreated?: string): string {
	const messagesHtml = messages.map(messageToPdfHtml).filter(Boolean).join('\n');

	return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>${escapeHtml(title)}</title>
<style>
	@page { margin: 40px 50px; size: A4; }
	* { margin: 0; padding: 0; box-sizing: border-box; }
	body {
		font-family: ${FONT_SANS};
		line-height: 1.6;
		color: #4d4f46;
		background: #fff;
		max-width: 800px;
		margin: 0 auto;
		padding: 40px 24px;
	}
	.header {
		border-bottom: 2px solid #bfc1b7;
		padding-bottom: 20px;
		margin-bottom: 32px;
	}
	.header h1 {
		font-size: 24px;
		font-weight: 500;
		color: #4d4f46;
		margin-bottom: 4px;
	}
	.header .meta {
		font-size: 13px;
		color: #4d4f46;
	}
	.header .brand {
		font-size: 13px;
		color: #F54E00;
		font-weight: 500;
		margin-top: 4px;
	}
	.message {
		margin-bottom: 20px;
		padding: 16px;
		border-radius: 12px;
	}
	.user-message {
		background: #fdfdf8;
		border: 1px solid #bfc1b7;
	}
	.assistant-message {
		background: #ffffff;
		border: 1px solid #bfc1b7;
	}
	.tool-message {
		background: #fdfdf8;
		border: 1px solid #bfc1b7;
		padding: 10px 16px;
		font-size: 13px;
	}
	.result-message {
		background: #f0f8f0;
		border: 1px solid #bfc1b7;
	}
	.info-message {
		background: #f0f4f8;
		border: 1px solid #bfc1b7;
		padding: 10px 16px;
		font-size: 13px;
	}
	.error-message {
		background: #fef2f2;
		border: 1px solid #bfc1b7;
		padding: 10px 16px;
	}
	.hitl-message {
		background: #fffbf0;
		border: 1px solid #bfc1b7;
	}
	.role {
		font-size: 12px;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: #4d4f46;
		margin-bottom: 6px;
	}
	.content { font-size: 14px; }
	.files {
		margin-top: 8px;
		font-size: 12px;
		color: #4d4f46;
	}
	.tool-badge {
		font-weight: 500;
		color: #4d4f46;
	}
	.tool-summary {
		color: #4d4f46;
		margin-top: 4px;
		font-family: ${FONT_MONO};
		font-size: 12px;
	}
	.tool-error {
		color: #dc2626;
		margin-top: 4px;
		font-size: 12px;
	}
	.error-badge {
		background: #dc2626;
		color: white;
		font-size: 10px;
		padding: 1px 6px;
		border-radius: 4px;
		font-weight: 500;
	}
	.error-text { color: #dc2626; font-size: 13px; }
	.info-text { color: #F54E00; font-size: 13px; }
	.hitl-response {
		margin-top: 8px;
		padding-top: 8px;
		border-top: 1px solid #bfc1b7;
		font-size: 13px;
		color: #4d4f46;
	}
	code {
		background: #fdfdf8;
		padding: 1px 5px;
		border-radius: 4px;
		font-size: 13px;
		font-family: ${FONT_MONO};
	}
	pre {
		background: #fdfdf8;
		padding: 12px;
		border-radius: 8px;
		overflow-x: auto;
		margin: 8px 0;
	}
	pre code { background: none; padding: 0; }
	.footer {
		margin-top: 40px;
		padding-top: 16px;
		border-top: 1px solid #bfc1b7;
		font-size: 12px;
		color: #4d4f46;
		text-align: center;
	}
</style>
</head>
<body>
<div class="header">
	<h1>${escapeHtml(title)}</h1>
	${dateCreated ? `<div class="meta">Created ${formatTimestamp(new Date(dateCreated))}</div>` : ''}
	<div class="brand">Midsphere</div>
</div>

${messagesHtml}

<div class="footer">
	Exported from Jatayu AI · ${formatTimestamp(new Date())}
</div>
</body>
</html>`;
}

// --- JSON Export ---

interface JsonMessage {
	type: string;
	text?: string;
	toolName?: string;
	args?: Record<string, unknown>;
	status?: string;
	error?: string;
	result?: unknown;
	files?: string[];
	attachments?: string[];
}

function messageToJson(msg: Message): JsonMessage | null {
	switch (msg.type) {
		case 'user':
			return { type: 'user', text: msg.text, ...(msg.files?.length ? { files: msg.files } : {}) };
		case 'assistant':
			return { type: 'assistant', text: msg.text };
		case 'tool_call':
			return {
				type: 'tool_call',
				toolName: stripMcpPrefix(msg.toolName),
				args: msg.args,
				status: msg.status,
				...(msg.error ? { error: msg.error } : {}),
				...(msg.result && typeof msg.result === 'string' ? { result: msg.result } : {})
			};
		case 'error':
			return { type: 'error', text: msg.message };
		case 'hitl':
			return { type: 'hitl', text: msg.prompt, ...(msg.response ? { result: msg.response } : {}) };
		case 'reasoning':
			return { type: 'reasoning', text: msg.text };
		default:
			return null;
	}
}

export function exportToJson(title: string, messages: Message[], dateCreated?: string): string {
	const data = {
		title,
		exported_from: 'Jatayu AI',
		exported_at: new Date().toISOString(),
		...(dateCreated ? { created_at: dateCreated } : {}),
		messages: messages.map(messageToJson).filter(Boolean)
	};
	return JSON.stringify(data, null, 2);
}

// --- Download helpers ---

export function downloadBlob(content: string, filename: string, mimeType: string): void {
	const blob = new Blob([content], { type: mimeType });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	document.body.removeChild(a);
	URL.revokeObjectURL(url);
}

export function sanitizeFilename(name: string): string {
	return name.replace(/[^a-zA-Z0-9_\- ]/g, '').trim() || 'conversation';
}
