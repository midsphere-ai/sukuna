import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import AgentMessage from '../lib/components/chat/AgentMessage.svelte';
import type { TextMessage } from '$services/sse';

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

function createMessage(overrides: Partial<TextMessage> = {}): TextMessage {
	return {
		type: 'assistant',
		text: 'Hello world',
		isStreaming: false,
		...overrides
	};
}

describe('AgentMessage', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('has agent-message test id', () => {
		render(AgentMessage, { props: { message: createMessage() } });
		expect(screen.getByTestId('agent-message')).toBeInTheDocument();
	});

	it('renders plain text content', () => {
		render(AgentMessage, { props: { message: createMessage({ text: 'Simple response' }) } });
		expect(screen.getByText('Simple response')).toBeInTheDocument();
	});

	it('renders markdown elements', () => {
		const text = 'This is **bold** with `code` and [a link](https://example.com)';
		const { container } = render(AgentMessage, { props: { message: createMessage({ text }) } });
		expect(container.querySelector('strong')).toBeInTheDocument();
		expect(container.querySelector('code')).toBeInTheDocument();
		expect(container.querySelector('a')).toBeInTheDocument();
		expect(screen.getByText('bold')).toBeInTheDocument();
		expect(screen.getByText('code')).toBeInTheDocument();
		expect(screen.getByText('a link')).toBeInTheDocument();
	});

	it('renders multi-paragraph markdown text', () => {
		const text = 'Line one\n\nLine two';
		const { container } = render(AgentMessage, { props: { message: createMessage({ text }) } });
		const paragraphs = container.querySelectorAll('.prose p');
		expect(paragraphs.length).toBe(2);
		expect(screen.getByText('Line one')).toBeInTheDocument();
		expect(screen.getByText('Line two')).toBeInTheDocument();
	});

	it('shows started-by label when provided', () => {
		render(AgentMessage, {
			props: { message: createMessage({ text: 'Delegated output' }), startedByName: 'Alice' }
		});
		expect(screen.getByText('Started by Alice')).toBeInTheDocument();
	});

	it('applies muted/small text styling', () => {
		const { container } = render(AgentMessage, { props: { message: createMessage() } });
		const body = container.querySelector('.prose');
		expect(body?.className).toContain('text-[13px]');
		expect(body?.className).toContain('text-foreground/70');
	});

	it('uses same text color across markdown element types', () => {
		const { container } = render(AgentMessage, {
			props: {
				message: createMessage({ text: '# Heading\n\n**bold** `code` [link](https://example.com)' })
			}
		});
		const body = container.querySelector('.prose');
		expect(body?.className).toContain('[&_a]:text-current');
		expect(body?.className).toContain('[&_strong]:text-current');
		expect(body?.className).toContain('[&_h1]:text-current');
		expect(body?.className).toContain('[&_code]:text-current');
		expect(body?.className).toContain('[&_th]:text-current');
	});

	it('does not render placeholder content for empty streaming text', () => {
		render(AgentMessage, { props: { message: createMessage({ text: '', isStreaming: true }) } });
		expect(screen.queryByText('Thinking...')).not.toBeInTheDocument();
		expect(screen.queryByText('partial chunk')).not.toBeInTheDocument();
	});

	it('renders streamed text when available', () => {
		render(AgentMessage, {
			props: { message: createMessage({ text: 'partial chunk', isStreaming: true }) }
		});
		expect(screen.getByText('partial chunk')).toBeInTheDocument();
	});

	it('does not apply legacy streaming cursor class while streaming', () => {
		render(AgentMessage, {
			props: { message: createMessage({ text: 'in progress', isStreaming: true }) }
		});
		expect(screen.getByTestId('agent-message').className).not.toContain('streaming-cursor');
	});
});
