import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import HitlMessage from '../lib/components/chat/HitlMessage.svelte';
import HitlInputBar from '../lib/components/chat/HitlInputBar.svelte';
import ChatMessageList from '../lib/components/chat/ChatMessageList.svelte';
import type { HitlMessage as HitlMessageType, HitlRequest, Message } from '$services/sse';

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

describe('HitlMessage (status-only inline)', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('prompt display', () => {
		it('renders prompt text', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Should I continue with this approach?'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.getByText('Should I continue with this approach?')).toBeInTheDocument();
		});

		it('has hitl-message test id', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Continue?'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.getByTestId('hitl-message')).toBeInTheDocument();
		});
	});

	describe('waiting indicator', () => {
		it('shows waiting indicator when no response', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Continue?'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.getByTestId('hitl-waiting')).toBeInTheDocument();
			expect(screen.getByText('Respond below')).toBeInTheDocument();
		});

		it('waiting indicator has pulse animation', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Continue?'
			};
			const { container } = render(HitlMessage, { props: { message } });
			const pulseDot = container.querySelector('.animate-pulse');
			expect(pulseDot).toBeInTheDocument();
		});

		it('hides waiting indicator when response is set', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Continue?',
				response: 'Yes'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.queryByTestId('hitl-waiting')).not.toBeInTheDocument();
		});
	});

	describe('submitted response display', () => {
		it('shows submitted response when response field is set', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Approve deploy?',
				choices: ['Yes', 'No'],
				response: 'Yes'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.getByTestId('hitl-response')).toBeInTheDocument();
			expect(screen.getByText('Yes')).toBeInTheDocument();
		});

		it('shows green checkmark icon with response', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Continue?',
				response: 'Go ahead'
			};
			const { container } = render(HitlMessage, { props: { message } });
			const greenCheck = container.querySelector('.text-success');
			expect(greenCheck).toBeInTheDocument();
		});

		it('shows "Your response:" label', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Pick:',
				response: 'Option A'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.getByText(/Your response:/)).toBeInTheDocument();
		});

		it('hides waiting indicator when response exists', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Enter name:',
				response: 'John'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.queryByTestId('hitl-waiting')).not.toBeInTheDocument();
		});
	});

	describe('no input controls in inline message', () => {
		it('does not render choice buttons inline', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Pick:',
				choices: ['A', 'B']
			};
			render(HitlMessage, { props: { message } });
			expect(screen.queryByTestId('hitl-choices')).not.toBeInTheDocument();
			expect(screen.queryByTestId('hitl-bar-choices')).not.toBeInTheDocument();
		});

		it('does not render free-text input inline', () => {
			const message: HitlMessageType = {
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Enter filename:'
			};
			render(HitlMessage, { props: { message } });
			expect(screen.queryByTestId('hitl-free-text')).not.toBeInTheDocument();
			expect(screen.queryByPlaceholderText('Type your response...')).not.toBeInTheDocument();
		});
	});
});

describe('HitlInputBar (bottom-anchored input)', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('rendering', () => {
		it('renders with hitl-input-bar test id', () => {
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Continue?'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit: vi.fn() } });
			expect(screen.getByTestId('hitl-input-bar')).toBeInTheDocument();
		});

		it('shows "Agent needs your input" header', () => {
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Continue?'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit: vi.fn() } });
			expect(screen.getByText('Agent needs your input')).toBeInTheDocument();
		});

		it('shows prompt text', () => {
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Should I deploy to production?'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit: vi.fn() } });
			expect(screen.getByText('Should I deploy to production?')).toBeInTheDocument();
		});
	});

	describe('choice buttons', () => {
		it('renders choice buttons when choices provided', () => {
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Pick target:',
				choices: ['Production', 'Staging', 'Development']
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit: vi.fn() } });
			expect(screen.getByTestId('hitl-bar-choices')).toBeInTheDocument();
			expect(screen.getByText('Production')).toBeInTheDocument();
			expect(screen.getByText('Staging')).toBeInTheDocument();
			expect(screen.getByText('Development')).toBeInTheDocument();
		});

		it('calls onSubmit with choice when button clicked', async () => {
			const onSubmit = vi.fn();
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Approve?',
				choices: ['Yes', 'No']
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit } });
			await fireEvent.click(screen.getByText('Yes'));
			expect(onSubmit).toHaveBeenCalledWith('req-1', 'Yes');
		});

		it('disables choice buttons after clicking one', async () => {
			const onSubmit = vi.fn();
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Pick:',
				choices: ['A', 'B']
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit } });
			await fireEvent.click(screen.getByText('A'));

			const buttons = screen.getAllByRole('button');
			buttons.forEach((btn) => {
				expect(btn).toBeDisabled();
			});
		});
	});

	describe('free-text input', () => {
		it('renders textarea when no choices provided', () => {
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'What should the filename be?'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit: vi.fn() } });
			expect(screen.getByTestId('hitl-bar-free-text')).toBeInTheDocument();
			expect(screen.getByPlaceholderText('Type your response...')).toBeInTheDocument();
		});

		it('has a Send button', () => {
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Enter value:'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit: vi.fn() } });
			expect(screen.getByText('Send')).toBeInTheDocument();
		});

		it('Send button is disabled when textarea is empty', () => {
			const hitlRequest: HitlRequest = {
				requestId: 'req-1',
				prompt: 'Enter value:'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit: vi.fn() } });
			expect(screen.getByTestId('hitl-bar-send')).toBeDisabled();
		});

		it('calls onSubmit with text when Send clicked', async () => {
			const onSubmit = vi.fn();
			const hitlRequest: HitlRequest = {
				requestId: 'req-2',
				prompt: 'Enter filename:'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit } });

			const textarea = screen.getByPlaceholderText('Type your response...');
			await fireEvent.input(textarea, { target: { value: 'report.pdf' } });

			await fireEvent.click(screen.getByTestId('hitl-bar-send'));
			expect(onSubmit).toHaveBeenCalledWith('req-2', 'report.pdf');
		});

		it('calls onSubmit on Enter key press', async () => {
			const onSubmit = vi.fn();
			const hitlRequest: HitlRequest = {
				requestId: 'req-3',
				prompt: 'Enter value:'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit } });

			const textarea = screen.getByPlaceholderText('Type your response...');
			await fireEvent.input(textarea, { target: { value: 'my-value' } });
			await fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

			expect(onSubmit).toHaveBeenCalledWith('req-3', 'my-value');
		});

		it('does not submit on Shift+Enter (allows multiline)', async () => {
			const onSubmit = vi.fn();
			const hitlRequest: HitlRequest = {
				requestId: 'req-4',
				prompt: 'Enter value:'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit } });

			const textarea = screen.getByPlaceholderText('Type your response...');
			await fireEvent.input(textarea, { target: { value: 'line 1' } });
			await fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

			expect(onSubmit).not.toHaveBeenCalled();
		});

		it('trims whitespace before submitting', async () => {
			const onSubmit = vi.fn();
			const hitlRequest: HitlRequest = {
				requestId: 'req-5',
				prompt: 'Enter value:'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit } });

			const textarea = screen.getByPlaceholderText('Type your response...');
			await fireEvent.input(textarea, { target: { value: '  hello world  ' } });

			await fireEvent.click(screen.getByTestId('hitl-bar-send'));
			expect(onSubmit).toHaveBeenCalledWith('req-5', 'hello world');
		});

		it('does not submit empty/whitespace-only text', async () => {
			const onSubmit = vi.fn();
			const hitlRequest: HitlRequest = {
				requestId: 'req-6',
				prompt: 'Enter value:'
			};
			render(HitlInputBar, { props: { hitlRequest, onSubmit } });

			const textarea = screen.getByPlaceholderText('Type your response...');
			await fireEvent.input(textarea, { target: { value: '   ' } });

			await fireEvent.click(screen.getByTestId('hitl-bar-send'));
			expect(onSubmit).not.toHaveBeenCalled();
		});
	});
});

describe('HitlMessage type integration', () => {
	it('HitlMessage type is part of Message union', () => {
		const msg: Message = {
			type: 'hitl',
			requestId: 'req-1',
			prompt: 'Continue?',
			choices: ['Yes', 'No']
		};
		expect(msg.type).toBe('hitl');
	});

	it('HitlMessage has all optional fields', () => {
		const msg: HitlMessageType = {
			type: 'hitl',
			requestId: 'req-1',
			prompt: 'Continue?',
			choices: ['Yes', 'No'],
			response: 'Yes'
		};
		expect(msg.choices).toEqual(['Yes', 'No']);
		expect(msg.response).toBe('Yes');
	});
});

describe('SSE Service - hitl_request handling', () => {
	beforeEach(async () => {
		const sse = await import('$services/sse');
		sse.resetStores();
	});

	it('replays hitl_request events into messages', async () => {
		const { replayEvents, messages: messagesStore } = await import('$services/sse');
		const events = [
			{
				sequence: 0,
				type: 'hitl_request',
				data: {
					type: 'hitl_request',
					request_id: 'req-1',
					prompt: 'Approve deploy?',
					choices: ['Yes', 'No']
				}
			}
		];

		replayEvents(events as import('$services/sse').PersistedEvent[]);

		const msgs = get(messagesStore);
		expect(msgs).toHaveLength(1);
		expect(msgs[0].type).toBe('hitl');
		if (msgs[0].type === 'hitl') {
			expect(msgs[0].requestId).toBe('req-1');
			expect(msgs[0].prompt).toBe('Approve deploy?');
			expect(msgs[0].choices).toEqual(['Yes', 'No']);
		}
	});

	it('sets runStatus to waiting_for_input on hitl_request', async () => {
		const { replayEvents, runStatus } = await import('$services/sse');
		const events = [
			{
				sequence: 0,
				type: 'hitl_request',
				data: {
					type: 'hitl_request',
					request_id: 'req-1',
					prompt: 'Continue?'
				}
			}
		];

		replayEvents(events as import('$services/sse').PersistedEvent[]);
		expect(get(runStatus)).toBe('waiting_for_input');
	});

	it('updateHitlResponse updates message and clears hitlRequest', async () => {
		const {
			replayEvents,
			updateHitlResponse,
			messages: messagesStore,
			hitlRequest
		} = await import('$services/sse');
		const events = [
			{
				sequence: 0,
				type: 'hitl_request',
				data: {
					type: 'hitl_request',
					request_id: 'req-1',
					prompt: 'Continue?',
					choices: ['Yes', 'No']
				}
			}
		];

		replayEvents(events as import('$services/sse').PersistedEvent[]);

		// Verify HITL request is set
		expect(get(hitlRequest)).not.toBeNull();

		// Submit response
		updateHitlResponse('req-1', 'Yes');

		// Verify message updated
		const msgs = get(messagesStore);
		expect(msgs[0].type).toBe('hitl');
		if (msgs[0].type === 'hitl') {
			expect(msgs[0].response).toBe('Yes');
		}

		// Verify hitlRequest cleared
		expect(get(hitlRequest)).toBeNull();
	});

	it('updateHitlResponse only updates matching requestId', async () => {
		const {
			replayEvents,
			updateHitlResponse,
			messages: messagesStore
		} = await import('$services/sse');
		const events = [
			{
				sequence: 0,
				type: 'hitl_request',
				data: {
					type: 'hitl_request',
					request_id: 'req-1',
					prompt: 'First question'
				}
			},
			{
				sequence: 1,
				type: 'hitl_request',
				data: {
					type: 'hitl_request',
					request_id: 'req-2',
					prompt: 'Second question'
				}
			}
		];

		replayEvents(events as import('$services/sse').PersistedEvent[]);

		updateHitlResponse('req-2', 'Answer 2');

		const msgs = get(messagesStore);
		expect(msgs[0].type).toBe('hitl');
		if (msgs[0].type === 'hitl') {
			expect(msgs[0].response).toBeUndefined();
		}
		expect(msgs[1].type).toBe('hitl');
		if (msgs[1].type === 'hitl') {
			expect(msgs[1].response).toBe('Answer 2');
		}
	});

	it('hitl_request without choices creates message without choices', async () => {
		const { replayEvents, messages: messagesStore } = await import('$services/sse');
		const events = [
			{
				sequence: 0,
				type: 'hitl_request',
				data: {
					type: 'hitl_request',
					request_id: 'req-free',
					prompt: 'What should the file be named?'
				}
			}
		];

		replayEvents(events as import('$services/sse').PersistedEvent[]);

		const msgs = get(messagesStore);
		expect(msgs[0].type).toBe('hitl');
		if (msgs[0].type === 'hitl') {
			expect(msgs[0].choices).toBeUndefined();
		}
	});
});

describe('ChatMessageList - HitlMessage rendering', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('renders HITL message in message list', () => {
		const messages: Message[] = [
			{
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Should I continue with this approach?'
			}
		];
		render(ChatMessageList, { props: { messages } });
		expect(screen.getByTestId('hitl-message')).toBeInTheDocument();
		expect(screen.getByText('Should I continue with this approach?')).toBeInTheDocument();
	});

	it('renders HITL with "Respond below" indicator when pending', () => {
		const messages: Message[] = [
			{
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Confirm action?'
			}
		];
		render(ChatMessageList, { props: { messages } });
		expect(screen.getByText('Respond below')).toBeInTheDocument();
	});

	it('renders HITL with submitted response', () => {
		const messages: Message[] = [
			{
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Approve?',
				choices: ['Yes', 'No'],
				response: 'Yes'
			}
		];
		render(ChatMessageList, { props: { messages } });
		expect(screen.getByTestId('hitl-response')).toBeInTheDocument();
		expect(screen.getByText('Yes')).toBeInTheDocument();
	});

	it('renders mixed messages with HITL correctly', () => {
		const messages: Message[] = [
			{ type: 'user', text: 'Deploy the app' },
			{ type: 'assistant', text: 'Starting deployment...', isStreaming: false },
			{
				type: 'hitl',
				requestId: 'req-1',
				prompt: 'Which environment?',
				choices: ['Production', 'Staging']
			}
		];
		render(ChatMessageList, { props: { messages } });

		expect(screen.getByTestId('user-message')).toBeInTheDocument();
		expect(screen.getByTestId('agent-message')).toBeInTheDocument();
		expect(screen.getByTestId('hitl-message')).toBeInTheDocument();
		expect(screen.getByText('Which environment?')).toBeInTheDocument();
	});
});
