import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import UserMessage from '../lib/components/chat/UserMessage.svelte';
import type { UserMessage as UserMessageType } from '$services/sse';

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

describe('UserMessage', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('text rendering', () => {
		it('renders plain text message', () => {
			const message: UserMessageType = { type: 'user', text: 'Hello world' };
			render(UserMessage, { props: { message } });
			expect(screen.getByText('Hello world')).toBeInTheDocument();
		});

		it('renders markdown bold text', () => {
			const message: UserMessageType = { type: 'user', text: 'This is **bold** text' };
			const { container } = render(UserMessage, { props: { message } });
			const strong = container.querySelector('strong');
			expect(strong).toBeInTheDocument();
			expect(strong?.textContent).toBe('bold');
		});

		it('renders markdown italic text', () => {
			const message: UserMessageType = { type: 'user', text: 'This is *italic* text' };
			const { container } = render(UserMessage, { props: { message } });
			const em = container.querySelector('em');
			expect(em).toBeInTheDocument();
			expect(em?.textContent).toBe('italic');
		});

		it('renders markdown inline code', () => {
			const message: UserMessageType = { type: 'user', text: 'Run `npm install`' };
			const { container } = render(UserMessage, { props: { message } });
			const code = container.querySelector('code');
			expect(code).toBeInTheDocument();
			expect(code?.textContent).toBe('npm install');
		});

		it('renders markdown links', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Visit [example](https://example.com)'
			};
			const { container } = render(UserMessage, { props: { message } });
			const link = container.querySelector('a');
			expect(link).toBeInTheDocument();
			expect(link?.getAttribute('href')).toBe('https://example.com');
			expect(link?.textContent).toBe('example');
		});

		it('has data-testid for identification', () => {
			const message: UserMessageType = { type: 'user', text: 'Test' };
			render(UserMessage, { props: { message } });
			expect(screen.getByTestId('user-message')).toBeInTheDocument();
		});

		it('renders message bubble with accent background', () => {
			const message: UserMessageType = { type: 'user', text: 'Test' };
			const { container } = render(UserMessage, { props: { message } });
			const bubble = container.querySelector('.bg-accent\\/\\[0\\.08\\]');
			expect(bubble).toBeInTheDocument();
		});
	});

	describe('file attachments', () => {
		it('renders file attachment chips', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Check these files',
				files: ['report.pdf', 'data.csv']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('report.pdf')).toBeInTheDocument();
			expect(screen.getByText('data.csv')).toBeInTheDocument();
		});

		it('does not render attachments section when no files', () => {
			const message: UserMessageType = { type: 'user', text: 'No files' };
			render(UserMessage, { props: { message } });
			expect(screen.queryByTestId('file-attachments')).not.toBeInTheDocument();
		});

		it('does not render attachments section when files array is empty', () => {
			const message: UserMessageType = { type: 'user', text: 'No files', files: [] };
			render(UserMessage, { props: { message } });
			expect(screen.queryByTestId('file-attachments')).not.toBeInTheDocument();
		});

		it('renders file chips as clickable buttons', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'File',
				files: ['photo.jpg']
			};
			render(UserMessage, { props: { message } });
			const button = screen.getByTitle('Preview photo.jpg');
			expect(button.tagName).toBe('BUTTON');
		});

		it('calls onFileClick when file chip is clicked', async () => {
			const onFileClick = vi.fn();
			const message: UserMessageType = {
				type: 'user',
				text: 'File',
				files: ['document.pdf']
			};
			render(UserMessage, { props: { message, onFileClick } });
			await fireEvent.click(screen.getByTitle('Preview document.pdf'));
			expect(onFileClick).toHaveBeenCalledWith('document.pdf');
		});

		it('does not throw when file clicked without onFileClick handler', async () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'File',
				files: ['test.txt']
			};
			render(UserMessage, { props: { message } });
			// Should not throw
			await fireEvent.click(screen.getByTitle('Preview test.txt'));
		});

		it('truncates long file names', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'File',
				files: ['very-long-filename-that-should-be-truncated.pdf']
			};
			const { container } = render(UserMessage, { props: { message } });
			const truncated = container.querySelector('.truncate');
			expect(truncated).toBeInTheDocument();
		});
	});

	describe('file type icons', () => {
		it('renders image icon for jpg files', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Image',
				files: ['photo.jpg']
			};
			const { container } = render(UserMessage, { props: { message } });
			// Image icon has circle and rect elements
			const svgs = container.querySelectorAll('svg');
			expect(svgs.length).toBeGreaterThan(0);
		});

		it('renders image icon for png files', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Image',
				files: ['screenshot.png']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('screenshot.png')).toBeInTheDocument();
		});

		it('renders PDF icon for pdf files', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Doc',
				files: ['report.pdf']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('report.pdf')).toBeInTheDocument();
		});

		it('renders video icon for mp4 files', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Video',
				files: ['clip.mp4']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('clip.mp4')).toBeInTheDocument();
		});

		it('renders audio icon for mp3 files', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Audio',
				files: ['song.mp3']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('song.mp3')).toBeInTheDocument();
		});

		it('renders code icon for ts files', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Code',
				files: ['app.ts']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('app.ts')).toBeInTheDocument();
		});

		it('renders archive icon for zip files', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Archive',
				files: ['bundle.zip']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('bundle.zip')).toBeInTheDocument();
		});

		it('renders document icon for unknown extensions', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Other',
				files: ['readme.xyz']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('readme.xyz')).toBeInTheDocument();
		});

		it('renders multiple files with different icons', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Multiple',
				files: ['photo.jpg', 'report.pdf', 'app.ts', 'clip.mp4']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('photo.jpg')).toBeInTheDocument();
			expect(screen.getByText('report.pdf')).toBeInTheDocument();
			expect(screen.getByText('app.ts')).toBeInTheDocument();
			expect(screen.getByText('clip.mp4')).toBeInTheDocument();
		});
	});

	describe('addon/MCP badge', () => {
		it('does not show badge when no addons or MCPs', () => {
			const message: UserMessageType = { type: 'user', text: 'Hello' };
			render(UserMessage, { props: { message } });
			expect(screen.queryByText(/addon/i)).not.toBeInTheDocument();
			expect(screen.queryByText(/MCP/i)).not.toBeInTheDocument();
		});

		it('shows addon count badge', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Hello',
				addons: ['github', 'slack', 'gmail']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('3 addons')).toBeInTheDocument();
		});

		it('shows singular addon text for one addon', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Hello',
				addons: ['github']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('1 addon')).toBeInTheDocument();
		});

		it('shows MCP count badge', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Hello',
				mcps: ['custom-server']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('1 MCP')).toBeInTheDocument();
		});

		it('shows plural MCPs text for multiple MCPs', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Hello',
				mcps: ['server1', 'server2']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('2 MCPs')).toBeInTheDocument();
		});

		it('shows combined addon and MCP count', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Hello',
				addons: ['github', 'slack', 'gmail'],
				mcps: ['custom-server']
			};
			render(UserMessage, { props: { message } });
			expect(screen.getByText('3 addons')).toBeInTheDocument();
			expect(screen.getByText('1 MCP')).toBeInTheDocument();
		});

		it('does not show badge when addons array is empty', () => {
			const message: UserMessageType = {
				type: 'user',
				text: 'Hello',
				addons: [],
				mcps: []
			};
			render(UserMessage, { props: { message } });
			expect(screen.queryByText(/addon/i)).not.toBeInTheDocument();
			expect(screen.queryByText(/MCP/i)).not.toBeInTheDocument();
		});
	});

	describe('layout', () => {
		it('renders message aligned to the right', () => {
			const message: UserMessageType = { type: 'user', text: 'Hello' };
			render(UserMessage, { props: { message } });
			const wrapper = screen.getByTestId('user-message');
			expect(wrapper.classList.contains('justify-end')).toBe(true);
		});

		it('limits message width to 85% of container', () => {
			const message: UserMessageType = { type: 'user', text: 'Hello' };
			const { container } = render(UserMessage, { props: { message } });
			const widthContainer = container.querySelector('.max-w-\\[85\\%\\]');
			expect(widthContainer).toBeInTheDocument();
		});
	});
});
