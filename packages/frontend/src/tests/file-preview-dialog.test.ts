import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import FilePreviewDialog from '../lib/components/chat/FilePreviewDialog.svelte';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock $stores/toast (transitive via marked → sse → toast)
vi.mock('$stores/toast', () => ({
	toasts: {
		success: vi.fn(),
		error: vi.fn(),
		warning: vi.fn(),
		info: vi.fn()
	}
}));

// Mock global fetch
const mockFetch = vi.fn().mockResolvedValue({
	ok: true,
	text: vi.fn().mockResolvedValue('console.log("hello");')
});
vi.stubGlobal('fetch', mockFetch);

describe('FilePreviewDialog', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetch.mockResolvedValue({
			ok: true,
			text: vi.fn().mockResolvedValue('console.log("hello");')
		});
		// Polyfill showModal/close for jsdom
		HTMLDialogElement.prototype.showModal = function () {
			this.setAttribute('open', '');
		};
		HTMLDialogElement.prototype.close = function () {
			this.removeAttribute('open');
		};
	});

	describe('rendering', () => {
		it('does not render content when closed', () => {
			render(FilePreviewDialog, {
				props: { open: false, filename: 'test.png', fileUrl: 'https://example.com/test.png' }
			});
			expect(screen.queryByTestId('file-preview-dialog')).toBeInTheDocument();
			expect(screen.queryByText('test.png')).not.toBeInTheDocument();
		});

		it('renders filename in header when open', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'photo.jpg', fileUrl: 'https://example.com/photo.jpg' }
			});
			expect(screen.getByText('photo.jpg')).toBeInTheDocument();
		});

		it('shows download button when open', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'file.txt', fileUrl: 'https://example.com/file.txt' }
			});
			expect(screen.getByTestId('download-button')).toBeInTheDocument();
			expect(screen.getByText('Download')).toBeInTheDocument();
		});

		it('shows close button when open', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'file.txt', fileUrl: 'https://example.com/file.txt' }
			});
			expect(screen.getByTestId('close-button')).toBeInTheDocument();
		});
	});

	describe('image preview', () => {
		it('renders image viewer for jpg files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'photo.jpg', fileUrl: 'https://example.com/photo.jpg' }
			});
			expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
			const img = screen.getByAltText('photo.jpg');
			expect(img).toBeInTheDocument();
			expect(img).toHaveAttribute('src', 'https://example.com/photo.jpg');
		});

		it('renders image viewer for png files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'icon.png', fileUrl: 'https://example.com/icon.png' }
			});
			expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
		});

		it('renders image viewer for webp files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'image.webp', fileUrl: 'https://example.com/image.webp' }
			});
			expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
		});

		it('renders image viewer for gif files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'anim.gif', fileUrl: 'https://example.com/anim.gif' }
			});
			expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
		});

		it('toggles zoom on click', async () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'photo.jpg', fileUrl: 'https://example.com/photo.jpg' }
			});
			const viewer = screen.getByTestId('image-viewer');
			expect(viewer).toHaveAttribute('aria-label', 'Zoom in');

			await fireEvent.click(viewer);
			expect(viewer).toHaveAttribute('aria-label', 'Zoom out');

			await fireEvent.click(viewer);
			expect(viewer).toHaveAttribute('aria-label', 'Zoom in');
		});
	});

	describe('PDF preview', () => {
		it('renders PDF viewer for pdf files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'document.pdf', fileUrl: 'https://example.com/document.pdf' }
			});
			expect(screen.getByTestId('pdf-viewer')).toBeInTheDocument();
			const iframe = screen.getByTitle('PDF preview: document.pdf');
			expect(iframe).toBeInTheDocument();
			expect(iframe).toHaveAttribute('src', 'https://example.com/document.pdf');
		});
	});

	describe('video preview', () => {
		it('renders video player for mp4 files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'clip.mp4', fileUrl: 'https://example.com/clip.mp4' }
			});
			expect(screen.getByTestId('video-player')).toBeInTheDocument();
		});

		it('renders video player for webm files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'clip.webm', fileUrl: 'https://example.com/clip.webm' }
			});
			expect(screen.getByTestId('video-player')).toBeInTheDocument();
		});
	});

	describe('audio preview', () => {
		it('renders audio player for mp3 files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'song.mp3', fileUrl: 'https://example.com/song.mp3' }
			});
			expect(screen.getByTestId('audio-player')).toBeInTheDocument();
			// Filename appears in both header and audio section
			const allMatches = screen.getAllByText('song.mp3');
			expect(allMatches.length).toBeGreaterThanOrEqual(2);
		});

		it('renders audio player for wav files', () => {
			render(FilePreviewDialog, {
				props: {
					open: true,
					filename: 'recording.wav',
					fileUrl: 'https://example.com/recording.wav'
				}
			});
			expect(screen.getByTestId('audio-player')).toBeInTheDocument();
		});
	});

	describe('code preview', () => {
		it('renders code viewer for js files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'app.js', fileUrl: 'https://example.com/app.js' }
			});
			expect(screen.getByTestId('code-viewer')).toBeInTheDocument();
		});

		it('renders code viewer for ts files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'index.ts', fileUrl: 'https://example.com/index.ts' }
			});
			expect(screen.getByTestId('code-viewer')).toBeInTheDocument();
		});

		it('renders code viewer for py files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'script.py', fileUrl: 'https://example.com/script.py' }
			});
			expect(screen.getByTestId('code-viewer')).toBeInTheDocument();
		});

		it('shows language label for code files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'app.ts', fileUrl: 'https://example.com/app.ts' }
			});
			expect(screen.getByText('TypeScript')).toBeInTheDocument();
		});

		it('fetches content for code files on open', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'app.js', fileUrl: 'https://example.com/app.js' }
			});
			expect(mockFetch).toHaveBeenCalledWith('https://example.com/app.js');
		});

		it('shows error when fetch fails', async () => {
			mockFetch.mockRejectedValueOnce(new Error('Network error'));

			render(FilePreviewDialog, {
				props: { open: true, filename: 'app.js', fileUrl: 'https://example.com/app.js' }
			});

			await vi.waitFor(() => {
				expect(screen.getByText('Network error')).toBeInTheDocument();
			});
		});
	});

	describe('markdown preview', () => {
		it('renders markdown viewer for md files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'README.md', fileUrl: 'https://example.com/README.md' }
			});
			expect(screen.getByTestId('markdown-viewer')).toBeInTheDocument();
		});

		it('fetches content for markdown files on open', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'README.md', fileUrl: 'https://example.com/README.md' }
			});
			expect(mockFetch).toHaveBeenCalledWith('https://example.com/README.md');
		});
	});

	describe('text preview', () => {
		it('renders text viewer for txt files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'notes.txt', fileUrl: 'https://example.com/notes.txt' }
			});
			expect(screen.getByTestId('text-viewer')).toBeInTheDocument();
		});

		it('renders text viewer for log files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'app.log', fileUrl: 'https://example.com/app.log' }
			});
			expect(screen.getByTestId('text-viewer')).toBeInTheDocument();
		});

		it('renders text viewer for csv files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'data.csv', fileUrl: 'https://example.com/data.csv' }
			});
			expect(screen.getByTestId('text-viewer')).toBeInTheDocument();
		});
	});

	describe('archive notice', () => {
		it('shows archive notice for zip files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'archive.zip', fileUrl: 'https://example.com/archive.zip' }
			});
			expect(screen.getByTestId('archive-notice')).toBeInTheDocument();
			expect(
				screen.getByText('Archive files cannot be previewed. Use the download button.')
			).toBeInTheDocument();
		});

		it('shows archive notice for tar.gz files', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'package.gz', fileUrl: 'https://example.com/package.gz' }
			});
			expect(screen.getByTestId('archive-notice')).toBeInTheDocument();
		});
	});

	describe('unknown file type', () => {
		it('shows unknown notice for unrecognized extensions', () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'data.xyz', fileUrl: 'https://example.com/data.xyz' }
			});
			expect(screen.getByTestId('unknown-notice')).toBeInTheDocument();
			expect(
				screen.getByText('This file type cannot be previewed. Use the download button.')
			).toBeInTheDocument();
		});
	});

	describe('close behavior', () => {
		it('calls onclose when close button clicked', async () => {
			const onclose = vi.fn();
			render(FilePreviewDialog, {
				props: {
					open: true,
					filename: 'test.png',
					fileUrl: 'https://example.com/test.png',
					onclose
				}
			});
			await fireEvent.click(screen.getByTestId('close-button'));
			expect(onclose).toHaveBeenCalled();
		});

		it('closes on Escape key', async () => {
			const onclose = vi.fn();
			render(FilePreviewDialog, {
				props: {
					open: true,
					filename: 'test.png',
					fileUrl: 'https://example.com/test.png',
					onclose
				}
			});
			const dialog = screen.getByTestId('file-preview-dialog');
			await fireEvent.keyDown(dialog, { key: 'Escape' });
			expect(onclose).toHaveBeenCalled();
		});
	});

	describe('download', () => {
		it('triggers download when download button clicked', async () => {
			render(FilePreviewDialog, {
				props: { open: true, filename: 'report.pdf', fileUrl: 'https://example.com/report.pdf' }
			});

			// Track anchor creation
			const clickSpy = vi.fn();
			const createElement = document.createElement.bind(document);
			vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
				const el = createElement(tag);
				if (tag === 'a') {
					el.click = clickSpy;
				}
				return el;
			});

			await fireEvent.click(screen.getByTestId('download-button'));

			expect(clickSpy).toHaveBeenCalled();

			vi.mocked(document.createElement).mockRestore();
		});
	});

	describe('file category detection', () => {
		it('detects all image extensions', () => {
			const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico'];
			for (const ext of imageExts) {
				const { unmount } = render(FilePreviewDialog, {
					props: { open: true, filename: `file.${ext}`, fileUrl: `https://example.com/file.${ext}` }
				});
				expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
				unmount();
			}
		});

		it('detects all video extensions', () => {
			const videoExts = ['mp4', 'webm', 'mov', 'avi', 'mkv'];
			for (const ext of videoExts) {
				const { unmount } = render(FilePreviewDialog, {
					props: { open: true, filename: `file.${ext}`, fileUrl: `https://example.com/file.${ext}` }
				});
				expect(screen.getByTestId('video-player')).toBeInTheDocument();
				unmount();
			}
		});

		it('detects all audio extensions', () => {
			const audioExts = ['mp3', 'wav', 'ogg', 'flac', 'aac'];
			for (const ext of audioExts) {
				const { unmount } = render(FilePreviewDialog, {
					props: { open: true, filename: `file.${ext}`, fileUrl: `https://example.com/file.${ext}` }
				});
				expect(screen.getByTestId('audio-player')).toBeInTheDocument();
				unmount();
			}
		});

		it('detects all code extensions', () => {
			const codeExts = [
				'js',
				'ts',
				'py',
				'go',
				'rs',
				'java',
				'json',
				'yaml',
				'html',
				'css',
				'sql',
				'sh'
			];
			for (const ext of codeExts) {
				const { unmount } = render(FilePreviewDialog, {
					props: { open: true, filename: `file.${ext}`, fileUrl: `https://example.com/file.${ext}` }
				});
				expect(screen.getByTestId('code-viewer')).toBeInTheDocument();
				unmount();
			}
		});
	});
});
