import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/svelte';
import TerminalRenderer from '../lib/components/toolRenderers/TerminalRenderer.svelte';
import DiffRenderer from '../lib/components/toolRenderers/DiffRenderer.svelte';
import CodeViewerRenderer from '../lib/components/toolRenderers/CodeViewerRenderer.svelte';
import FileTreeRenderer from '../lib/components/toolRenderers/FileTreeRenderer.svelte';
import FileStatusRenderer from '../lib/components/toolRenderers/FileStatusRenderer.svelte';
import type { ToolCallMessage } from '$services/sse';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock $stores/toast to avoid store side-effects from SSE
vi.mock('$stores/toast', () => ({
	toasts: {
		success: vi.fn(),
		error: vi.fn(),
		warning: vi.fn(),
		info: vi.fn()
	}
}));

function createToolCall(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
	return {
		type: 'tool_call',
		callId: 'test-call-1',
		toolName: 'mcp_search_google',
		args: {},
		status: 'success',
		...overrides
	};
}

afterEach(() => {
	cleanup();
});

// =======================================================
// TerminalRenderer
// =======================================================
describe('TerminalRenderer', () => {
	const shellCall = (
		overrides: Partial<Parameters<typeof createToolCall>[0]> = {}
	): ReturnType<typeof createToolCall> =>
		createToolCall({
			toolName: 'shell',
			args: { action: 'exec', command: 'ls -la' },
			result: {
				success: true,
				message: 'Command executed',
				exit_code: 0,
				stdout: 'total 0',
				stderr: ''
			},
			...overrides
		});

	it('renders the terminal-renderer container', () => {
		render(TerminalRenderer, { props: { toolCall: shellCall() } });
		expect(screen.getByTestId('terminal-renderer')).toBeInTheDocument();
	});

	it('shows the command prompt for shell exec', () => {
		render(TerminalRenderer, { props: { toolCall: shellCall() } });
		const command = screen.getByTestId('terminal-command');
		expect(command).toHaveTextContent('$');
		expect(command).toHaveTextContent('ls -la');
	});

	it('displays stdout content', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'echo hello' },
					result: { success: true, exit_code: 0, stdout: 'hello world output', stderr: '' }
				})
			}
		});
		expect(screen.getByTestId('terminal-stdout')).toHaveTextContent('hello world output');
	});

	it('displays stderr content', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'bad-cmd' },
					result: {
						success: true,
						exit_code: 1,
						stdout: '',
						stderr: 'command not found: bad-cmd'
					}
				})
			}
		});
		expect(screen.getByTestId('terminal-stderr')).toHaveTextContent('command not found: bad-cmd');
	});

	it('shows a success-styled exit code badge for exit 0', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'true' },
					result: { success: true, exit_code: 0, stdout: '', stderr: '' }
				})
			}
		});
		const badge = screen.getByTestId('terminal-exit-code');
		expect(badge).toHaveTextContent('exit 0');
		expect(badge.className).toContain('text-success');
	});

	it('shows a coral exit code badge for non-zero exit', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'false' },
					result: { success: true, exit_code: 1, stdout: '', stderr: 'error' }
				})
			}
		});
		const badge = screen.getByTestId('terminal-exit-code');
		expect(badge).toHaveTextContent('exit 1');
		expect(badge.className).toContain('text-accent');
	});

	it('shows a session badge when session is set', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'ls', session: 'work' },
					result: { success: true, exit_code: 0, stdout: 'file1', stderr: '' }
				})
			}
		});
		expect(screen.getByTestId('terminal-session')).toHaveTextContent('@work');
	});

	it('shows package install note when present', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'pip install requests' },
					result: {
						success: true,
						exit_code: 0,
						stdout: 'Successfully installed',
						stderr: '',
						package_install_note: 'Package requests installed to user environment'
					}
				})
			}
		});
		expect(screen.getByTestId('terminal-package-note')).toHaveTextContent(
			'Package requests installed'
		);
	});

	it('has a copy button', () => {
		render(TerminalRenderer, { props: { toolCall: shellCall() } });
		expect(screen.getByTestId('terminal-copy')).toBeInTheDocument();
	});

	it('displays the shell action label in the header', () => {
		render(TerminalRenderer, { props: { toolCall: shellCall() } });
		expect(screen.getByText(/shell · exec/i)).toBeInTheDocument();
	});

	it('renders the terminal body', () => {
		render(TerminalRenderer, { props: { toolCall: shellCall() } });
		expect(screen.getByTestId('terminal-body')).toBeInTheDocument();
	});

	it('handles string-only result', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'echo hi' },
					result: 'plain text output'
				})
			}
		});
		expect(screen.getByTestId('terminal-stdout')).toHaveTextContent('plain text output');
	});

	it('escapes HTML in stdout output', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'ls --color' },
					result: {
						success: true,
						exit_code: 0,
						stdout: '<script>alert("xss")</script>',
						stderr: ''
					}
				})
			}
		});
		const stdout = screen.getByTestId('terminal-stdout');
		expect(stdout.innerHTML).not.toContain('<script>');
		expect(stdout.textContent).toContain('<script>alert("xss")</script>');
	});

	it('shows "No output" when exec produced no command or output', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec' },
					result: { success: true, exit_code: 0, stdout: '', stderr: '' }
				})
			}
		});
		expect(screen.getByText('No output')).toBeInTheDocument();
	});

	it('renders an error block with hint when success is false', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'rm -rf /' },
					result: {
						success: false,
						error: 'Command blocked',
						message: 'Dangerous pattern detected',
						hint: 'Remove dangerous patterns from the command before retrying'
					}
				})
			}
		});
		const err = screen.getByTestId('terminal-error');
		expect(err).toHaveTextContent('Command blocked');
		expect(err).toHaveTextContent('Dangerous pattern detected');
		expect(err).toHaveTextContent(/hint:/i);
	});

	it('renders session list for action=view', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'view' },
					result: {
						success: true,
						message: 'Active sessions',
						sessions: [
							{ session: 'build', created: '1', last_activity: '2', windows: '1' },
							{ session: 'server', created: '3', last_activity: '4', windows: '1' }
						]
					}
				})
			}
		});
		const list = screen.getByTestId('terminal-sessions');
		expect(list).toHaveTextContent('build');
		expect(list).toHaveTextContent('server');
	});

	it('shows a running indicator when result is absent', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'sleep 1' },
					result: undefined as unknown as Record<string, unknown>
				})
			}
		});
		expect(screen.getByTestId('terminal-running')).toBeInTheDocument();
	});

	it('renders a stdout-saved-to notice when output overflowed', () => {
		render(TerminalRenderer, {
			props: {
				toolCall: shellCall({
					args: { action: 'exec', command: 'cat big.log' },
					result: {
						success: true,
						exit_code: 0,
						stdout: '(preview)',
						stderr: '',
						stdout_saved_to: '/tmp/out.log',
						stdout_size_bytes: 4096,
						stdout_total_lines: 500
					}
				})
			}
		});
		expect(screen.getByTestId('terminal-stdout-saved')).toHaveTextContent('/tmp/out.log');
	});
});

// =======================================================
// DiffRenderer
// =======================================================
describe('DiffRenderer', () => {
	const diffResult = {
		success: true,
		message: 'File edited',
		diff: `--- a/src/app.ts
+++ b/src/app.ts
@@ -1,5 +1,5 @@
 import express from 'express';
-const port = 3000;
+const port = 8080;
 const app = express();
-app.listen(port);
+app.listen(port, () => console.log('running'));`,
		match_results: [
			{ edit_index: 0, match_type: 'exact' as const, details: 'Matched line 2' },
			{ edit_index: 1, match_type: 'fuzzy' as const, details: 'Fuzzy matched line 4' }
		],
		file_path: '/home/user/workspace/src/app.ts',
		dry_run: false
	};

	it('renders the diff-renderer container', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		expect(screen.getByTestId('diff-renderer')).toBeInTheDocument();
	});

	it('displays the file name from result', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		expect(screen.getByTestId('diff-file-path')).toHaveTextContent('app.ts');
	});

	it('falls back to file_path from args', () => {
		const result = { ...diffResult, file_path: undefined };
		render(DiffRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'edit_file',
					result,
					args: { file_path: '/workspace/index.js' }
				})
			}
		});
		expect(screen.getByTestId('diff-file-path')).toHaveTextContent('index.js');
	});

	it('renders diff lines with correct types', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		const lines = screen.getAllByTestId('diff-line');
		expect(lines.length).toBeGreaterThan(0);

		// Check we have added and removed lines
		const addedLines = lines.filter((l) => l.getAttribute('data-line-type') === 'added');
		const removedLines = lines.filter((l) => l.getAttribute('data-line-type') === 'removed');
		expect(addedLines.length).toBe(2);
		expect(removedLines.length).toBe(2);
	});

	it('displays change stats (+added/-removed)', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		expect(screen.getByTestId('diff-stats')).toHaveTextContent('+2');
		expect(screen.getByTestId('diff-stats')).toHaveTextContent('-2');
	});

	it('renders hunk headers', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		const hunkHeaders = screen.getAllByTestId('diff-hunk-header');
		expect(hunkHeaders.length).toBeGreaterThanOrEqual(1);
		expect(hunkHeaders[0]).toHaveTextContent('@@ -1,5 +1,5 @@');
	});

	it('renders match result badges', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		const badges = screen.getAllByTestId('diff-match-badge');
		expect(badges).toHaveLength(2);
		expect(badges[0]).toHaveTextContent('Edit 1: exact');
		expect(badges[1]).toHaveTextContent('Edit 2: fuzzy');
	});

	it('shows dry run badge when dry_run is true', () => {
		const dryRunResult = { ...diffResult, dry_run: true };
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: dryRunResult }) }
		});
		expect(screen.getByTestId('diff-dry-run')).toHaveTextContent('dry run');
	});

	it('does not show dry run badge when dry_run is false', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		expect(screen.queryByTestId('diff-dry-run')).not.toBeInTheDocument();
	});

	it('has a copy button', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		expect(screen.getByTestId('diff-copy')).toBeInTheDocument();
	});

	it('renders the diff content container', () => {
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: diffResult }) }
		});
		expect(screen.getByTestId('diff-content')).toBeInTheDocument();
	});

	it('handles string-only result', () => {
		render(DiffRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'edit_file',
					result: '--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old\n+new'
				})
			}
		});
		const lines = screen.getAllByTestId('diff-line');
		const addedLines = lines.filter((l) => l.getAttribute('data-line-type') === 'added');
		expect(addedLines.length).toBe(1);
	});

	it('shows expand button for large diffs', () => {
		// Generate a large diff (>50 lines)
		const largeDiffLines = ['--- a/big.txt', '+++ b/big.txt', '@@ -1,60 +1,60 @@'];
		for (let i = 0; i < 60; i++) {
			largeDiffLines.push(`-old line ${i}`);
			largeDiffLines.push(`+new line ${i}`);
		}
		const largeDiff = { ...diffResult, diff: largeDiffLines.join('\n') };
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: largeDiff }) }
		});
		expect(screen.getByTestId('diff-expand')).toBeInTheDocument();
	});

	it('expands large diff on button click', async () => {
		const largeDiffLines = ['--- a/big.txt', '+++ b/big.txt', '@@ -1,60 +1,60 @@'];
		for (let i = 0; i < 60; i++) {
			largeDiffLines.push(`-old line ${i}`);
			largeDiffLines.push(`+new line ${i}`);
		}
		const largeDiff = { ...diffResult, diff: largeDiffLines.join('\n') };
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: largeDiff }) }
		});
		await fireEvent.click(screen.getByTestId('diff-expand'));
		expect(screen.queryByTestId('diff-expand')).not.toBeInTheDocument();
	});

	it('handles result with no match_results', () => {
		const simpleResult = { ...diffResult, match_results: undefined };
		render(DiffRenderer, {
			props: { toolCall: createToolCall({ toolName: 'edit_file', result: simpleResult }) }
		});
		expect(screen.queryByTestId('diff-match-results')).not.toBeInTheDocument();
	});
});

// =======================================================
// CodeViewerRenderer
// =======================================================
describe('CodeViewerRenderer', () => {
	const fileContent = `import express from 'express';
const app = express();
const port = 3000;

app.get('/', (req, res) => {
  res.send('Hello World!');
});

app.listen(port);`;

	it('renders the code-viewer-renderer container', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/src/app.ts' },
					result: fileContent
				})
			}
		});
		expect(screen.getByTestId('code-viewer-renderer')).toBeInTheDocument();
	});

	it('displays the file name', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/src/app.ts' },
					result: fileContent
				})
			}
		});
		expect(screen.getByTestId('code-file-path')).toHaveTextContent('app.ts');
	});

	it('detects language from file extension', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/src/app.ts' },
					result: fileContent
				})
			}
		});
		expect(screen.getByTestId('code-language')).toHaveTextContent('typescript');
	});

	it('detects python language', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/main.py' },
					result: 'print("hello")'
				})
			}
		});
		expect(screen.getByTestId('code-language')).toHaveTextContent('python');
	});

	it('displays line count', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/src/app.ts' },
					result: fileContent
				})
			}
		});
		expect(screen.getByTestId('code-line-count')).toHaveTextContent('9 lines');
	});

	it('shows singular "line" when count is 1', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/one.txt' },
					result: 'single line'
				})
			}
		});
		expect(screen.getByTestId('code-line-count')).toHaveTextContent('1 line');
	});

	it('renders code lines with line numbers', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/src/app.ts' },
					result: fileContent
				})
			}
		});
		const lines = screen.getAllByTestId('code-line');
		expect(lines).toHaveLength(9);
	});

	it('has a copy button', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/src/app.ts' },
					result: fileContent
				})
			}
		});
		expect(screen.getByTestId('code-copy')).toBeInTheDocument();
	});

	it('renders code content container', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/src/app.ts' },
					result: fileContent
				})
			}
		});
		expect(screen.getByTestId('code-content')).toBeInTheDocument();
	});

	it('handles object result with message field', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/test.txt' },
					result: { success: true, message: 'file content here' }
				})
			}
		});
		expect(screen.getByTestId('code-lines')).toHaveTextContent('file content here');
	});

	it('uses path arg as fallback when file_path not present', () => {
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { path: '/workspace/style.css' },
					result: 'body { color: red; }'
				})
			}
		});
		expect(screen.getByTestId('code-file-path')).toHaveTextContent('style.css');
		expect(screen.getByTestId('code-language')).toHaveTextContent('css');
	});

	it('shows expand button for large files (>100 lines)', () => {
		const largeFile = Array.from({ length: 120 }, (_, i) => `line ${i + 1}`).join('\n');
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/big.txt' },
					result: largeFile
				})
			}
		});
		expect(screen.getByTestId('code-expand')).toBeInTheDocument();
	});

	it('expands large file on button click', async () => {
		const largeFile = Array.from({ length: 120 }, (_, i) => `line ${i + 1}`).join('\n');
		render(CodeViewerRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'read_file',
					args: { file_path: '/workspace/big.txt' },
					result: largeFile
				})
			}
		});
		await fireEvent.click(screen.getByTestId('code-expand'));
		expect(screen.queryByTestId('code-expand')).not.toBeInTheDocument();
		const lines = screen.getAllByTestId('code-line');
		expect(lines).toHaveLength(120);
	});
});

// =======================================================
// FileTreeRenderer
// =======================================================
describe('FileTreeRenderer', () => {
	const directoryResult = [
		'src/',
		'docs/',
		'package.json',
		'tsconfig.json',
		'README.md',
		'.gitignore'
	];

	it('renders the file-tree-renderer container', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/home/user/workspace' },
					result: directoryResult
				})
			}
		});
		expect(screen.getByTestId('file-tree-renderer')).toBeInTheDocument();
	});

	it('displays the directory path', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/home/user/workspace' },
					result: directoryResult
				})
			}
		});
		expect(screen.getByTestId('file-tree-path')).toHaveTextContent('/home/user/workspace');
	});

	it('renders file tree items', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/home/user/workspace' },
					result: directoryResult
				})
			}
		});
		const items = screen.getAllByTestId('file-tree-item');
		expect(items).toHaveLength(6);
	});

	it('sorts directories first', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/workspace' },
					result: directoryResult
				})
			}
		});
		const items = screen.getAllByTestId('file-tree-item');
		// First two should be directories
		expect(items[0].getAttribute('data-is-dir')).toBe('true');
		expect(items[1].getAttribute('data-is-dir')).toBe('true');
	});

	it('displays file and directory counts', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/workspace' },
					result: directoryResult
				})
			}
		});
		expect(screen.getByTestId('file-tree-dir-count')).toHaveTextContent('2 folders');
		expect(screen.getByTestId('file-tree-file-count')).toHaveTextContent('4 files');
	});

	it('shows singular "folder" when count is 1', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/workspace' },
					result: ['src/', 'index.ts']
				})
			}
		});
		expect(screen.getByTestId('file-tree-dir-count')).toHaveTextContent('1 folder');
	});

	it('handles string result (newline-separated)', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/workspace' },
					result: 'file1.txt\nfile2.txt\nsrc/'
				})
			}
		});
		const items = screen.getAllByTestId('file-tree-item');
		expect(items.length).toBeGreaterThanOrEqual(3);
	});

	it('shows empty state for empty directory', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/workspace/empty' },
					result: []
				})
			}
		});
		expect(screen.getByTestId('file-tree-empty')).toHaveTextContent('Empty directory');
	});

	it('renders file tree content container', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/workspace' },
					result: directoryResult
				})
			}
		});
		expect(screen.getByTestId('file-tree-content')).toBeInTheDocument();
	});

	it('handles object result with files array', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { path: '/workspace' },
					result: { success: true, files: ['app.ts', 'utils/'] }
				})
			}
		});
		const items = screen.getAllByTestId('file-tree-item');
		expect(items).toHaveLength(2);
	});

	it('uses directory arg as fallback', () => {
		render(FileTreeRenderer, {
			props: {
				toolCall: createToolCall({
					toolName: 'list_directory',
					args: { directory: '/home/user/project' },
					result: ['file.txt']
				})
			}
		});
		expect(screen.getByTestId('file-tree-path')).toHaveTextContent('/home/user/project');
	});
});

// =======================================================
// FileStatusRenderer
// =======================================================
describe('FileStatusRenderer', () => {
	const writeCall = (
		overrides: Partial<Parameters<typeof createToolCall>[0]> = {}
	): ReturnType<typeof createToolCall> =>
		createToolCall({
			toolName: 'file',
			args: { action: 'write', path: '/workspace/app.ts' },
			result: { success: true, message: 'File written' },
			...overrides
		});

	it('renders the file-status-renderer container', () => {
		render(FileStatusRenderer, { props: { toolCall: writeCall() } });
		expect(screen.getByTestId('file-status-renderer')).toBeInTheDocument();
	});

	it('displays the action for file write', () => {
		render(FileStatusRenderer, { props: { toolCall: writeCall() } });
		expect(screen.getByTestId('file-status-action')).toHaveTextContent('Wrote');
	});

	it('displays the action for file append', () => {
		render(FileStatusRenderer, {
			props: {
				toolCall: writeCall({
					args: { action: 'append', path: '/workspace/log.txt' },
					result: { success: true, message: 'Content appended' }
				})
			}
		});
		expect(screen.getByTestId('file-status-action')).toHaveTextContent('Appended to');
	});

	it('displays the action for file download', () => {
		render(FileStatusRenderer, {
			props: {
				toolCall: writeCall({
					args: {
						action: 'download',
						path: '/workspace/out.zip',
						url: 'https://example.com/out.zip'
					},
					result: { success: true, message: 'Downloaded' }
				})
			}
		});
		expect(screen.getByTestId('file-status-action')).toHaveTextContent('Downloaded');
	});

	it('displays the file name from args.path', () => {
		render(FileStatusRenderer, {
			props: {
				toolCall: writeCall({ args: { action: 'write', path: '/workspace/src/utils.ts' } })
			}
		});
		expect(screen.getByTestId('file-status-name')).toHaveTextContent('utils.ts');
	});

	it('displays the status message on success', () => {
		render(FileStatusRenderer, {
			props: {
				toolCall: writeCall({
					result: { success: true, message: 'File saved successfully to /workspace/app.ts' }
				})
			}
		});
		expect(screen.getByTestId('file-status-message')).toHaveTextContent('File saved successfully');
	});

	it('renders the status card', () => {
		render(FileStatusRenderer, { props: { toolCall: writeCall() } });
		expect(screen.getByTestId('file-status-card')).toBeInTheDocument();
	});

	it('falls back to "Completed" when action is missing', () => {
		render(FileStatusRenderer, {
			props: {
				toolCall: writeCall({
					args: { path: '/workspace/app.ts' },
					result: { success: true, message: 'Done' }
				})
			}
		});
		expect(screen.getByTestId('file-status-action')).toHaveTextContent('Completed');
	});

	it('renders an error block with hint when success is false', () => {
		render(FileStatusRenderer, {
			props: {
				toolCall: writeCall({
					args: { action: 'write', path: '/workspace/missing/app.ts' },
					status: 'error',
					result: {
						success: false,
						error: 'FileNotFoundError',
						message: 'Parent directory does not exist',
						hint: 'Create the parent directory first using shell mkdir.'
					}
				})
			}
		});
		expect(screen.getByTestId('file-status-action')).toHaveTextContent('Failed to write');
		const card = screen.getByTestId('file-status-card');
		expect(card).toHaveTextContent('Parent directory does not exist');
		expect(card).toHaveTextContent(/hint:/i);
	});
});
