import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import ChatMessageList from '../lib/components/chat/ChatMessageList.svelte';
import { runStatus, type Message } from '$services/sse';

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

// Mock auth store to avoid localStorage access during SSE module init
vi.mock('$stores/auth', () => ({
	authToken: {
		subscribe: (callback: (value: string | null) => void) => {
			callback(null);
			return () => {};
		}
	}
}));

describe('ChatMessageList', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		runStatus.set('idle');
	});

	describe('rendering', () => {
		it('renders empty state when no messages', () => {
			render(ChatMessageList, { props: { messages: [] } });
			expect(screen.getByText('No messages yet')).toBeInTheDocument();
		});

		it('renders loading skeleton when loading with no messages', () => {
			render(ChatMessageList, { props: { messages: [], loading: true } });
			expect(screen.getByTestId('message-skeleton')).toBeInTheDocument();
		});

		it('does not show loading skeleton when messages exist', () => {
			const messages: Message[] = [{ type: 'user', text: 'Hello' }];
			render(ChatMessageList, { props: { messages } });
			expect(screen.queryByTestId('message-skeleton')).not.toBeInTheDocument();
		});

		it('renders user messages', () => {
			const messages: Message[] = [{ type: 'user', text: 'Hello world' }];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Hello world')).toBeInTheDocument();
		});

		it('renders assistant messages', () => {
			const messages: Message[] = [
				{ type: 'assistant', text: 'I can help you with that.', isStreaming: false }
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('I can help you with that.')).toBeInTheDocument();
		});

		it('skips finalized empty assistant outputs', () => {
			const messages: Message[] = [{ type: 'assistant', text: '', isStreaming: false }];
			const { container } = render(ChatMessageList, { props: { messages } });
			expect(screen.queryByTestId('agent-message')).not.toBeInTheDocument();
			expect(container.querySelectorAll('.message-item').length).toBe(0);
		});

		it('renders streaming assistant messages directly', () => {
			runStatus.set('running');
			const messages: Message[] = [{ type: 'assistant', text: 'Typing...', isStreaming: true }];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Typing...')).toBeInTheDocument();
			expect(screen.getByTestId('agent-message')).toBeInTheDocument();
		});

		it('renders tool call with running status spinner', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'mcp_search_google',
					args: {},
					status: 'running'
				}
			];
			const { container } = render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Searched the web')).toBeInTheDocument();
			const spinner = container.querySelector('.animate-spin');
			expect(spinner).toBeInTheDocument();
		});

		it('renders tool call summary for success status', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'tc-2',
					toolName: 'mcp_run_shell_command',
					args: {},
					status: 'success',
					durationMs: 1500
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Ran shell command')).toBeInTheDocument();
			expect(screen.getByText('1.5s')).toBeInTheDocument();
		});

		it('renders tool call with error status', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'tc-3',
					toolName: 'failed_tool',
					args: {},
					status: 'error',
					error: 'Something failed'
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Failed Tool')).toBeInTheDocument();
		});

		it('renders HITL request with prompt', () => {
			const messages: Message[] = [
				{
					type: 'hitl',
					requestId: 'hitl-1',
					prompt: 'Should I continue with this approach?'
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Should I continue with this approach?')).toBeInTheDocument();
		});

		it('renders HITL with response when submitted', () => {
			const messages: Message[] = [
				{
					type: 'hitl',
					requestId: 'hitl-2',
					prompt: 'Pick a color:',
					choices: ['red', 'blue'],
					response: 'blue'
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Pick a color:')).toBeInTheDocument();
			expect(screen.getByTestId('hitl-response')).toBeInTheDocument();
			expect(screen.getByText('blue')).toBeInTheDocument();
		});

		it('renders error messages', () => {
			const messages: Message[] = [{ type: 'error', message: 'Connection lost' }];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Connection lost')).toBeInTheDocument();
		});

		it('hides step indicators in the chat list', () => {
			const messages: Message[] = [{ type: 'step', stepNumber: 2, status: 'started', maxSteps: 5 }];
			render(ChatMessageList, { props: { messages } });
			expect(screen.queryByText(/Step 2/)).not.toBeInTheDocument();
		});

		it('renders reasoning messages', () => {
			const messages: Message[] = [
				{ type: 'reasoning', text: 'I need to analyze the data first.' }
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('I need to analyze the data first.')).toBeInTheDocument();
		});

		it('renders MCP progress indicator', () => {
			const messages: Message[] = [
				{
					type: 'mcp_progress',
					toolName: 'mcp_download',
					progress: 50,
					total: 100,
					message: 'Downloading...'
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Downloading...')).toBeInTheDocument();
		});

		it('renders tool calls as individual rows', () => {
			const messages: Message[] = [
				{ type: 'user', text: 'Do a multi-step task' },
				{
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'mcp_search_google',
					args: { brief: 'First step' },
					status: 'success'
				},
				{ type: 'assistant', text: 'Interim response', isStreaming: false },
				{
					type: 'tool_call',
					callId: 'tc-2',
					toolName: 'mcp_run_shell_command',
					args: { brief: 'Second step' },
					status: 'running'
				}
			];
			const { container } = render(ChatMessageList, { props: { messages } });
			const toolCalls = container.querySelectorAll('[data-testid="tool-call-message"]');
			expect(toolCalls).toHaveLength(2);
			expect(screen.getByText('Second step')).toBeInTheDocument();
		});

		it.each(['completed', 'failed', 'cancelled'] as const)(
			'does not convert tool calls to worked-for summary when run is %s',
			(status) => {
				runStatus.set(status);
				const messages: Message[] = [
					{ type: 'user', text: 'Find docs' },
					{
						type: 'tool_call',
						callId: 'tc-1',
						toolName: 'mcp_search_google',
						args: { brief: 'Searching docs' },
						status: 'success',
						durationMs: 1500
					}
				];
				render(ChatMessageList, { props: { messages } });
				expect(screen.getByText('Searching docs')).toBeInTheDocument();
				expect(screen.queryByText('Worked for 1.5s')).not.toBeInTheDocument();
			}
		);

		it('keeps latest activity text when run is not terminal', () => {
			runStatus.set('idle');
			const messages: Message[] = [
				{ type: 'user', text: 'Find docs' },
				{
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'mcp_search_google',
					args: { brief: 'Searching docs' },
					status: 'success'
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Searching docs')).toBeInTheDocument();
			expect(screen.queryByText(/Worked/)).not.toBeInTheDocument();
		});

		it('keeps interim assistant text transient while run is active', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{ type: 'user', text: 'Do work' },
				{ type: 'assistant', text: 'Working on it...', isStreaming: false }
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.queryByText('Working on it...')).toBeInTheDocument();
			expect(screen.getByTestId('agent-message')).toBeInTheDocument();
		});

		it('keeps assistant text visible when run has concluded immediately after', () => {
			runStatus.set('completed');
			const messages: Message[] = [
				{ type: 'user', text: 'Do work' },
				{ type: 'assistant', text: 'Final answer', isStreaming: false }
			];
			render(ChatMessageList, {
				props: { messages }
			});
			expect(screen.getByText('Final answer')).toBeInTheDocument();
		});

		it('keeps mcp ask assistant messages visible even while running', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{ type: 'user', text: 'Do work' },
				{
					type: 'assistant',
					text: 'Which environment?',
					isStreaming: false,
					metadata: { source: 'human_input', message_type: 'ask' }
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Which environment?')).toBeInTheDocument();
		});

		it('renders user message with file attachments', () => {
			const messages: Message[] = [
				{
					type: 'user',
					text: 'Check this file',
					files: ['report.pdf', 'data.csv']
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Check this file')).toBeInTheDocument();
			expect(screen.getByText('report.pdf')).toBeInTheDocument();
			expect(screen.getByText('data.csv')).toBeInTheDocument();
		});
	});

	describe('mixed message sequence', () => {
		it('renders a full conversation flow', () => {
			const messages: Message[] = [
				{ type: 'user', text: 'Search for cats' },
				{ type: 'assistant', text: 'I will search for cats.', isStreaming: false },
				{
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'mcp_search_google',
					args: { query: 'cats' },
					status: 'success',
					durationMs: 800
				},
				{ type: 'assistant', text: 'Here are the results.', isStreaming: false },
				{ type: 'user', text: 'Thanks!' }
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Search for cats')).toBeInTheDocument();
			expect(screen.getByText(/Searched/)).toBeInTheDocument();
			expect(screen.getByText('Here are the results.')).toBeInTheDocument();
			expect(screen.getByText('Thanks!')).toBeInTheDocument();
		});
	});

	describe('load more', () => {
		it('shows load more button when hasMore is true', () => {
			const messages: Message[] = [{ type: 'user', text: 'Hello' }];
			render(ChatMessageList, { props: { messages, hasMore: true } });
			expect(screen.getByText('Load earlier messages')).toBeInTheDocument();
		});

		it('does not show load more when hasMore is false', () => {
			const messages: Message[] = [{ type: 'user', text: 'Hello' }];
			render(ChatMessageList, { props: { messages, hasMore: false } });
			expect(screen.queryByText('Load earlier messages')).not.toBeInTheDocument();
		});

		it('calls onLoadMore when load more button is clicked', async () => {
			const mockLoadMore = vi.fn();
			const messages: Message[] = [{ type: 'user', text: 'Hello' }];
			render(ChatMessageList, {
				props: { messages, hasMore: true, onLoadMore: mockLoadMore }
			});
			await fireEvent.click(screen.getByText('Load earlier messages'));
			expect(mockLoadMore).toHaveBeenCalled();
		});
	});

	describe('scroll behavior', () => {
		it('has chat messages container with role log', () => {
			const messages: Message[] = [{ type: 'user', text: 'Hello' }];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByRole('log')).toBeInTheDocument();
		});

		it('has aria-label for accessibility', () => {
			render(ChatMessageList, { props: { messages: [] } });
			expect(screen.getByLabelText('Chat messages')).toBeInTheDocument();
		});
	});

	describe('new messages indicator', () => {
		it('does not show indicator by default', () => {
			const messages: Message[] = [{ type: 'user', text: 'Hello' }];
			render(ChatMessageList, { props: { messages } });
			expect(screen.queryByText('New messages')).not.toBeInTheDocument();
		});
	});

	describe('branch switching', () => {
		it('passes onBranch callback to user messages', () => {
			const onBranch = vi.fn();
			const messages: Message[] = [{ type: 'user', text: 'Hello' }];
			render(ChatMessageList, { props: { messages, onBranch } });
			expect(screen.getByTestId('user-message')).toBeInTheDocument();
		});

		it('passes onBranch callback to agent messages', () => {
			const onBranch = vi.fn();
			const messages: Message[] = [{ type: 'assistant', text: 'Reply here', isStreaming: false }];
			render(ChatMessageList, { props: { messages, onBranch } });
			expect(screen.getByTestId('agent-message')).toBeInTheDocument();
		});

		it('renders branch point indicator on user message', () => {
			const messages: Message[] = [
				{ type: 'user', text: 'First message' },
				{ type: 'assistant', text: 'Response', isStreaming: false }
			];
			const { container } = render(ChatMessageList, {
				props: { messages, branchPointIndex: 0 }
			});
			// Branch point indicator should show a divider/marker
			const branchIndicators = container.querySelectorAll('[class*="border-accent"]');
			expect(branchIndicators.length).toBeGreaterThan(0);
		});

		it('renders branch point indicator on agent message', () => {
			const messages: Message[] = [
				{ type: 'user', text: 'Question' },
				{ type: 'assistant', text: 'Answer', isStreaming: false }
			];
			const { container } = render(ChatMessageList, {
				props: { messages, branchPointIndex: 1 }
			});
			const branchIndicators = container.querySelectorAll('[class*="border-accent"]');
			expect(branchIndicators.length).toBeGreaterThan(0);
		});

		it('does not show branch indicator when branchPointIndex is null', () => {
			const messages: Message[] = [
				{ type: 'user', text: 'Hello' },
				{ type: 'assistant', text: 'Hi', isStreaming: false }
			];
			render(ChatMessageList, {
				props: { messages, branchPointIndex: null }
			});
			// Branch point text should not appear
			expect(screen.queryByText('Branch point')).not.toBeInTheDocument();
		});
	});

	describe('streaming state rendering', () => {
		it('renders a single shared thinking indicator while streamed text is empty', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{ type: 'user', text: 'Hello' },
				{ type: 'assistant', text: '', isStreaming: true }
			];
			render(ChatMessageList, { props: { messages, runStatus: 'running' } });
			expect(screen.queryByTestId('agent-message')).not.toBeInTheDocument();
			expect(screen.getByText('Thinking...')).toBeInTheDocument();
			expect(screen.getAllByText('Thinking...')).toHaveLength(1);
		});

		it('does not show shared thinking indicator for completed stream', () => {
			runStatus.set('completed');
			const messages: Message[] = [
				{ type: 'user', text: 'Hello' },
				{ type: 'assistant', text: 'Done!', isStreaming: false }
			];
			render(ChatMessageList, { props: { messages, runStatus: 'completed' } });
			expect(screen.getByTestId('agent-message')).toBeInTheDocument();
			expect(screen.queryByText('Thinking...')).not.toBeInTheDocument();
		});

		it('renders streaming text as it arrives', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{ type: 'user', text: 'Tell me a story' },
				{ type: 'assistant', text: 'Once upon a time', isStreaming: true }
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('Once upon a time')).toBeInTheDocument();
		});

		it('updates streamed assistant text on rerender', async () => {
			runStatus.set('running');
			const { rerender } = render(ChatMessageList, {
				props: {
					messages: [
						{ type: 'user', text: 'Tell me a story' },
						{ type: 'assistant', text: 'First chunk', isStreaming: true }
					]
				}
			});

			expect(screen.getByText('First chunk')).toBeInTheDocument();

			await rerender({
				messages: [
					{ type: 'user', text: 'Tell me a story' },
					{ type: 'assistant', text: 'Second chunk', isStreaming: true }
				]
			});

			expect(screen.getByText('Second chunk')).toBeInTheDocument();
			expect(screen.queryByText('First chunk')).not.toBeInTheDocument();
		});

		it('renders multiple tool calls during streaming', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{ type: 'user', text: 'Do research' },
				{
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'mcp_search_google',
					args: { brief: 'Searching' },
					status: 'success',
					durationMs: 500
				},
				{
					type: 'tool_call',
					callId: 'tc-2',
					toolName: 'mcp_read_file',
					args: { brief: 'Reading' },
					status: 'running'
				}
			];
			render(ChatMessageList, { props: { messages } });
			const toolCalls = screen.getAllByTestId('tool-call-message');
			expect(toolCalls).toHaveLength(2);
		});

		it('keeps message tool call out of collapsed tool groups', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'mcp_search_google',
					args: {},
					status: 'success'
				},
				{
					type: 'tool_call',
					callId: 'tc-2',
					toolName: 'message',
					args: { type: 'info', text: 'I am checking the next step now.' },
					status: 'success'
				},
				{
					type: 'tool_call',
					callId: 'tc-3',
					toolName: 'mcp_run_shell_command',
					args: {},
					status: 'running'
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByText('I am checking the next step now.')).toBeInTheDocument();
			expect(screen.getAllByTestId('tool-call-message')).toHaveLength(3);
			expect(screen.queryByText(/actions$/)).not.toBeInTheDocument();
		});

		it('groups delegated executor output into a collapsible side thread', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Research the market size' },
					status: 'success',
					source_agent: 'planner'
				},
				{
					type: 'tool_call',
					callId: 'tc-exec-1',
					toolName: 'mcp_search_google',
					args: { brief: 'Researching market size sources' },
					status: 'success',
					source_agent: 'executor_1'
				},
				{
					type: 'assistant',
					text: 'Analyzed market reports and extracted key growth metrics.',
					isStreaming: false,
					source_agent: 'executor_1'
				},
				{
					type: 'assistant',
					text: 'I will now synthesize this into the final answer.',
					isStreaming: false,
					source_agent: 'planner'
				}
			];

			render(ChatMessageList, { props: { messages } });
			expect(screen.getByTestId('delegate-group')).toBeInTheDocument();
			expect(screen.getByTestId('delegate-group-complete')).toBeInTheDocument();
			const searchTool = document.querySelector('[data-tool-name="mcp_search_google"]');
			expect(searchTool).toBeInTheDocument();
			expect(
				screen.getByText('Analyzed market reports and extracted key growth metrics.')
			).toBeInTheDocument();
			expect(
				screen.getByText('I will now synthesize this into the final answer.')
			).toBeInTheDocument();
		});

		it('keeps planner tool calls outside the delegate executor thread', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Research references' },
					status: 'success',
					source_agent: 'main'
				},
				{
					type: 'tool_call',
					callId: 'tc-exec-1',
					toolName: 'mcp_search_google',
					args: { query: 'executor references' },
					status: 'success',
					source_agent: 'executor_1'
				},
				{
					type: 'tool_call',
					callId: 'tc-main-1',
					toolName: 'mcp_run_shell_command',
					args: { command: 'echo planner-step' },
					status: 'success',
					source_agent: 'main'
				}
			];

			render(ChatMessageList, { props: { messages } });

			const content = screen.getByTestId('delegate-group-content');
			expect(within(content).queryByText('echo planner-step')).not.toBeInTheDocument();
			expect(screen.getByText('echo planner-step')).toBeInTheDocument();
			expect(screen.getAllByTestId('tool-call-message')).toHaveLength(2);
		});

		it('keeps unattributed tool calls inside delegate after executor attribution appears', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Collect sources' },
					status: 'success',
					source_agent: 'planner'
				},
				{
					type: 'tool_call',
					callId: 'tc-exec-1',
					toolName: 'mcp_search_google',
					args: { query: 'executor first step' },
					status: 'success',
					source_agent: 'executor_1'
				},
				{
					type: 'tool_call',
					callId: 'tc-exec-2',
					toolName: 'mcp_run_shell_command',
					args: { command: 'echo exec-followup' },
					status: 'success'
				},
				{
					type: 'assistant',
					text: 'Planner resumes here.',
					isStreaming: false,
					source_agent: 'planner'
				}
			];

			render(ChatMessageList, { props: { messages } });

			const content = screen.getByTestId('delegate-group-content');
			expect(within(content).getByText(/executor first step/)).toBeInTheDocument();
			expect(within(content).getByText('echo exec-followup')).toBeInTheDocument();
			expect(screen.getByText('Planner resumes here.')).toBeInTheDocument();
		});

		it('renders executor tool cards even when call ids are empty', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: '',
					toolName: 'delegate',
					args: { brief: 'Write summary' },
					status: 'success',
					source_agent: 'planner'
				},
				{
					type: 'tool_call',
					callId: '',
					toolName: 'save_file',
					args: { path: '/workspace/product_design.md' },
					status: 'success',
					source_agent: 'executor_1'
				}
			];

			render(ChatMessageList, { props: { messages } });

			const content = screen.getByTestId('delegate-group-content');
			const toolCard = content.querySelector('[data-tool-name="save_file"]');
			expect(toolCard).toBeInTheDocument();
			expect(within(content).getByText('Saved product_design.md')).toBeInTheDocument();
		});

		it('toggles delegate thread content on header click', async () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Find references' },
					status: 'success',
					source_agent: 'planner'
				},
				{
					type: 'tool_call',
					callId: 'tc-exec-1',
					toolName: 'mcp_search_google',
					args: { brief: 'Searching references' },
					status: 'success',
					source_agent: 'executor_1'
				}
			];

			render(ChatMessageList, { props: { messages } });
			const toggle = screen.getByTestId('delegate-group-toggle');
			expect(screen.getByTestId('delegate-group-content')).toBeInTheDocument();

			await fireEvent.click(toggle);
			expect(screen.queryByTestId('delegate-group-content')).not.toBeInTheDocument();

			await fireEvent.click(toggle);
			expect(screen.getByTestId('delegate-group-content')).toBeInTheDocument();
		});

		it('shows running marker for in-progress delegate groups', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Collect facts' },
					status: 'running',
					source_agent: 'planner'
				}
			];
			render(ChatMessageList, { props: { messages } });
			expect(screen.getByTestId('delegate-group-running')).toBeInTheDocument();
		});

		it('connects consecutive delegate indicators with muted dotted lines', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Collect references' },
					status: 'success',
					source_agent: 'planner'
				},
				{
					type: 'tool_call',
					callId: 'delegate-2',
					toolName: 'delegate',
					args: { brief: 'Draft summary' },
					status: 'running',
					source_agent: 'planner'
				}
			];

			render(ChatMessageList, { props: { messages, runStatus: 'running' } });
			const groups = screen.getAllByTestId('delegate-group');
			expect(groups).toHaveLength(2);

			expect(
				within(groups[0]).queryByTestId('delegate-group-connector-above')
			).not.toBeInTheDocument();
			expect(within(groups[0]).getByTestId('delegate-group-connector-below')).toBeInTheDocument();
			expect(within(groups[1]).getByTestId('delegate-group-connector-above')).toBeInTheDocument();
			expect(
				within(groups[1]).queryByTestId('delegate-group-connector-below')
			).not.toBeInTheDocument();
		});

		it('keeps latest delegate indicator running while run is active even before child events', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Collect facts' },
					status: 'success',
					source_agent: 'planner'
				}
			];

			render(ChatMessageList, { props: { messages, runStatus: 'running' } });
			const group = screen.getByTestId('delegate-group');
			expect(within(group).getByTestId('delegate-group-running')).toBeInTheDocument();
			expect(within(group).queryByTestId('delegate-group-complete')).not.toBeInTheDocument();
			expect(screen.getByText('Thinking...')).toBeInTheDocument();
		});

		it('shows running delegate indicator when child executor activity is still running', () => {
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'delegate-1',
					toolName: 'delegate',
					args: { brief: 'Collect facts' },
					status: 'success',
					source_agent: 'planner'
				},
				{
					type: 'tool_call',
					callId: 'tc-exec-1',
					toolName: 'mcp_search_google',
					args: { brief: 'Searching sources' },
					status: 'running',
					source_agent: 'executor_1'
				}
			];

			render(ChatMessageList, { props: { messages } });
			const group = screen.getByTestId('delegate-group');
			expect(within(group).getByTestId('delegate-group-running')).toBeInTheDocument();
			expect(within(group).queryByTestId('delegate-group-complete')).not.toBeInTheDocument();
		});

		it('shows running spinner on active tool call', () => {
			runStatus.set('running');
			const messages: Message[] = [
				{
					type: 'tool_call',
					callId: 'tc-1',
					toolName: 'mcp_run_shell_command',
					args: {},
					status: 'running'
				}
			];
			const { container } = render(ChatMessageList, { props: { messages } });
			const spinner = container.querySelector('.animate-spin');
			expect(spinner).toBeInTheDocument();
		});

		it('updates tool call status on rerender', async () => {
			runStatus.set('running');
			const { container, rerender } = render(ChatMessageList, {
				props: {
					messages: [
						{
							type: 'tool_call',
							callId: 'tc-1',
							toolName: 'mcp_run_shell_command',
							args: {},
							status: 'running'
						}
					]
				}
			});

			expect(container.querySelector('.animate-spin')).toBeInTheDocument();

			await rerender({
				messages: [
					{
						type: 'tool_call',
						callId: 'tc-1',
						toolName: 'mcp_run_shell_command',
						args: {},
						status: 'success',
						durationMs: 1200
					}
				]
			});

			expect(screen.getByText('1.2s')).toBeInTheDocument();
			expect(container.querySelector('.animate-spin')).not.toBeInTheDocument();
		});
	});
});
