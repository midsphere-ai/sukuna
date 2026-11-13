import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ToolCallMessage from '../lib/components/chat/ToolCallMessage.svelte';
import type { ToolCallMessage as ToolCallMessageType, Message } from '$services/sse';

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

function createToolCall(overrides: Partial<ToolCallMessageType> = {}): ToolCallMessageType {
	return {
		type: 'tool_call',
		callId: 'test-call-1',
		toolName: 'mcp_search_google',
		args: {},
		status: 'running',
		...overrides
	};
}

describe('ToolCallMessage', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('basic rendering', () => {
		it('renders with tool-call-message test id', () => {
			render(ToolCallMessage, { props: { message: createToolCall() } });
			expect(screen.getByTestId('tool-call-message')).toBeInTheDocument();
		});

		it('sets data-tool-name attribute', () => {
			render(ToolCallMessage, { props: { message: createToolCall({ toolName: 'edit_file' }) } });
			expect(screen.getByTestId('tool-call-message')).toHaveAttribute(
				'data-tool-name',
				'edit_file'
			);
		});

		it('sets data-tool-status attribute', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'success' }) }
			});
			expect(screen.getByTestId('tool-call-message')).toHaveAttribute(
				'data-tool-status',
				'success'
			);
		});

		it('renders category icon as SVG', () => {
			const { container } = render(ToolCallMessage, {
				props: { message: createToolCall() }
			});
			const svgs = container.querySelectorAll('svg');
			expect(svgs.length).toBeGreaterThan(0);
		});
	});

	describe('status indicators', () => {
		it('shows running spinner when status is running', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'running' }) }
			});
			expect(screen.getByTestId('tool-status-running')).toBeInTheDocument();
		});

		it('shows error icon when status is error', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'error' }) }
			});
			expect(screen.getByTestId('tool-status-error')).toBeInTheDocument();
		});

		it('running spinner has animate-spin class', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'running' }) }
			});
			const spinner = screen.getByTestId('tool-status-running');
			expect(spinner.getAttribute('class')).toContain('animate-spin');
		});

		it('error icon has coral color', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'error' }) }
			});
			const icon = screen.getByTestId('tool-status-error');
			expect(icon.getAttribute('class')).toContain('text-accent');
		});
	});

	describe('duration display', () => {
		it('shows duration when provided', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'success', durationMs: 2500 }) }
			});
			expect(screen.getByTestId('tool-duration')).toBeInTheDocument();
			expect(screen.getByTestId('tool-duration').textContent?.trim()).toBe('2.5s');
		});

		it('does not show duration when not provided', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'success' }) }
			});
			expect(screen.queryByTestId('tool-duration')).not.toBeInTheDocument();
		});

		it('formats duration correctly for sub-second', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'success', durationMs: 350 }) }
			});
			expect(screen.getByTestId('tool-duration').textContent?.trim()).toBe('0.3s');
		});

		it('formats duration correctly for long operations', () => {
			render(ToolCallMessage, {
				props: { message: createToolCall({ status: 'success', durationMs: 15230 }) }
			});
			expect(screen.getByTestId('tool-duration').textContent?.trim()).toBe('15.2s');
		});
	});

	describe('action label display', () => {
		it('shows action label for file edit', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'edit_file',
						args: { path: '/home/user/workspace/src/main.py' }
					})
				}
			});
			expect(screen.getByText('Edited main.py')).toBeInTheDocument();
		});

		it('shows action label for shell commands', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'mcp_run_shell_command',
						args: { command: 'npm install express' }
					})
				}
			});
			expect(screen.getByText('npm install express')).toBeInTheDocument();
		});

		it('shows action label for search', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'mcp_search_google',
						args: { query: 'SvelteKit SSR documentation' }
					})
				}
			});
			expect(screen.getByText(/SvelteKit SSR documentation/)).toBeInTheDocument();
		});

		it('shows action label for read file', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'read_file',
						args: { file_path: '/workspace/config.json' }
					})
				}
			});
			expect(screen.getByText('Read config.json')).toBeInTheDocument();
		});

		it('shows URL hostname for scrape tools', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'mcp_scrape_webpage',
						args: { url: 'https://docs.svelte.dev/tutorial/introduction' }
					})
				}
			});
			expect(screen.getByText('Scraped docs.svelte.dev')).toBeInTheDocument();
		});

		it('shows action label for python code', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'mcp_run_python_code',
						args: { code: 'import numpy as np\nresult = np.array([1, 2, 3])' }
					})
				}
			});
			expect(screen.getByText('Ran Python code')).toBeInTheDocument();
		});
	});

	describe('message tool display', () => {
		it('renders message text as card body', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'message',
						args: { type: 'info', text: 'Analyzing code structure' }
					})
				}
			});
			expect(screen.getByText('Analyzing code structure')).toBeInTheDocument();
		});

		it('shows message type badge', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'message',
						args: { type: 'result', text: 'Done' }
					})
				}
			});
			expect(screen.getByText('Result')).toBeInTheDocument();
		});

		it('hides error icon when message content is present', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'message',
						status: 'error',
						args: { type: 'result', text: 'Completed successfully' }
					})
				}
			});
			expect(screen.queryByTestId('tool-status-error')).not.toBeInTheDocument();
		});

		it('shows error icon when message content is missing', () => {
			render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'message',
						status: 'error',
						args: { type: 'result' }
					})
				}
			});
			expect(screen.getByTestId('tool-status-error')).toBeInTheDocument();
		});

		it('can hide message header and only render body text', () => {
			const { container } = render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'message',
						args: { type: 'info', text: 'Executor update body' }
					}),
					hideMessageHeader: true
				}
			});
			expect(screen.getByTestId('tool-message-body')).toBeInTheDocument();
			expect(screen.queryByText('Message')).not.toBeInTheDocument();
			expect(container.querySelector('[data-tool-name="message"]')).toBeInTheDocument();
		});
	});

	describe('muted rendering', () => {
		it('renders tool call row as boxed in muted mode', () => {
			const { container } = render(ToolCallMessage, {
				props: {
					message: createToolCall({
						toolName: 'mcp_search_google',
						args: { brief: 'Searching references' },
						status: 'success',
						durationMs: 1200
					}),
					muted: true
				}
			});
			const row = container.querySelector('[data-testid="tool-call-message"]');
			expect(row?.className).toContain('my-0.5');
			expect(row?.className).toContain('rounded-3xl');
			expect(row?.className).toContain('border');
			expect(row?.className).toContain('inline-flex');
			expect(row?.className).toContain('max-w-full');
			expect(screen.queryByTestId('tool-duration')).not.toBeInTheDocument();
		});
	});

	describe('file server tool mapping', () => {
		const fileTools = [
			'edit_file',
			'read_file',
			'save_file',
			'list_directory',
			'create_directory',
			'delete_file',
			'move_file',
			'copy_file',
			'search_files',
			'get_file_info'
		];

		for (const toolName of fileTools) {
			it(`renders ${toolName} with file category icon`, () => {
				const { container } = render(ToolCallMessage, {
					props: { message: createToolCall({ toolName }) }
				});
				expect(screen.getByTestId('tool-call-message')).toHaveAttribute('data-tool-name', toolName);
				// Should render an SVG icon for the file category
				const svgs = container.querySelectorAll('svg');
				expect(svgs.length).toBeGreaterThan(0);
			});
		}
	});

	describe('ToolCallMessage type integration', () => {
		it('ToolCallMessage is part of Message union', () => {
			const msg: Message = {
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'edit_file',
				args: { path: '/test.py' },
				status: 'running'
			};
			expect(msg.type).toBe('tool_call');
		});

		it('handles all three statuses', () => {
			const statuses: Array<'running' | 'success' | 'error'> = ['running', 'success', 'error'];
			for (const status of statuses) {
				const msg: ToolCallMessageType = {
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'edit_file',
					args: {},
					status
				};
				expect(msg.status).toBe(status);
			}
		});

		it('supports optional result field', () => {
			const msg: ToolCallMessageType = {
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_search_google',
				args: { query: 'test' },
				status: 'success',
				result: { items: ['result1', 'result2'] }
			};
			expect(msg.result).toBeDefined();
		});

		it('supports optional error field', () => {
			const msg: ToolCallMessageType = {
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_run_shell_command',
				args: { command: 'invalid' },
				status: 'error',
				error: 'Command not found'
			};
			expect(msg.error).toBe('Command not found');
		});
	});
});
