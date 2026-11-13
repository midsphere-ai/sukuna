<script lang="ts">
	/**
	 * Lazy-loaded PDF viewer for the `pdf` artifact type.
	 *
	 * Receives base64-encoded PDF bytes in `content` and renders every page
	 * into a stacked column of <canvas> elements at fit-width. Dynamic-imports
	 * pdfjs-dist so the ~300 KB library only loads when a pdf artifact
	 * actually arrives.
	 *
	 * Used by ArtifactCanvas for live document previews produced by the
	 * sandbox's live_preview.py loop — every officecli command that modifies
	 * the source .pptx/.docx/.xlsx causes a new base64 payload to arrive
	 * through SSE, and the $effect below re-renders this component in place.
	 */
	import { onDestroy, untrack } from 'svelte';

	type Props = {
		content: string;
		title: string;
	};
	let { content, title }: Props = $props();

	let container: HTMLDivElement | undefined = $state();
	let pages: HTMLCanvasElement[] = $state([]);
	let pageCount = $state(0);
	let status: 'idle' | 'loading' | 'ready' | 'error' = $state('idle');
	let errorMessage = $state('');

	// Cache the lazy-loaded pdfjs module so subsequent renders don't re-import
	// (dynamic import is cached by the browser, but holding the ref is cheaper).
	let pdfjsModule: typeof import('pdfjs-dist') | null = null;

	// Render generation — every new content triggers a new render; older
	// in-flight renders check this counter and abort when it advances.
	let renderGen = 0;

	async function ensurePdfjs(): Promise<typeof import('pdfjs-dist')> {
		if (pdfjsModule) return pdfjsModule;
		const [lib, worker] = await Promise.all([
			import('pdfjs-dist'),
			// Vite: append ?url to get a hashed URL string instead of executing the worker here.
			import('pdfjs-dist/build/pdf.worker.mjs?url')
		]);
		lib.GlobalWorkerOptions.workerSrc = worker.default;
		pdfjsModule = lib;
		return lib;
	}

	function base64ToBytes(b64: string): Uint8Array {
		const binary = atob(b64);
		const bytes = new Uint8Array(binary.length);
		for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
		return bytes;
	}

	async function renderPdf(): Promise<void> {
		const myGen = ++renderGen;
		if (!content) {
			pages = [];
			pageCount = 0;
			status = 'idle';
			return;
		}
		status = 'loading';
		errorMessage = '';

		let bytes: Uint8Array;
		try {
			bytes = base64ToBytes(content);
		} catch (err) {
			if (myGen !== renderGen) return;
			status = 'error';
			errorMessage = 'Failed to decode PDF payload';
			return;
		}

		let pdfjsLib: typeof import('pdfjs-dist');
		try {
			pdfjsLib = await ensurePdfjs();
		} catch (err) {
			if (myGen !== renderGen) return;
			status = 'error';
			errorMessage = 'Failed to load PDF renderer';
			return;
		}
		if (myGen !== renderGen) return;

		// Width budget — the container is inside a flex parent; fall back to 800 if it's not mounted yet.
		const containerWidth = container?.clientWidth ?? 800;

		try {
			const pdf = await pdfjsLib.getDocument({ data: bytes }).promise;
			if (myGen !== renderGen) {
				// Newer render took over; drop this document.
				pdf.destroy?.();
				return;
			}

			const canvases: HTMLCanvasElement[] = [];
			for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
				if (myGen !== renderGen) return;
				const page = await pdf.getPage(pageNum);
				if (myGen !== renderGen) return;
				const viewport1x = page.getViewport({ scale: 1 });
				// Fit width to container, accounting for device pixel ratio for crispness.
				const fitScale = Math.max(0.3, (containerWidth - 24) / viewport1x.width);
				const dpr = Math.min(window.devicePixelRatio || 1, 2);
				const viewport = page.getViewport({ scale: fitScale * dpr });

				const canvas = document.createElement('canvas');
				canvas.width = Math.floor(viewport.width);
				canvas.height = Math.floor(viewport.height);
				canvas.style.width = `${Math.floor(viewport.width / dpr)}px`;
				canvas.style.height = `${Math.floor(viewport.height / dpr)}px`;
				canvas.className = 'mb-3 rounded border border-border-subtle bg-white shadow-sm';
				const ctx = canvas.getContext('2d');
				if (!ctx) {
					throw new Error('Canvas 2D context unavailable');
				}
				await page.render({ canvasContext: ctx, viewport }).promise;
				if (myGen !== renderGen) return;
				canvases.push(canvas);
			}

			if (myGen !== renderGen) return;
			pages = canvases;
			pageCount = canvases.length;
			status = 'ready';
		} catch (err) {
			if (myGen !== renderGen) return;
			status = 'error';
			errorMessage = err instanceof Error ? err.message : 'Failed to render PDF';
		}
	}

	$effect(() => {
		// Track `content` so any update re-triggers rendering.
		content;
		// Avoid re-running on unrelated reactive state (pages, status, etc.).
		untrack(() => {
			void renderPdf();
		});
	});

	// Mount the rendered canvases into the DOM whenever `pages` changes.
	$effect(() => {
		if (!container) return;
		const scrollEl = container;
		// Preserve scroll position across updates so live refreshes don't jump to top.
		const prevTop = scrollEl.scrollTop;
		scrollEl.innerHTML = '';
		for (const canvas of pages) {
			scrollEl.appendChild(canvas);
		}
		scrollEl.scrollTop = prevTop;
	});

	onDestroy(() => {
		renderGen++; // cancel any in-flight render
		pages = [];
	});
</script>

<div class="flex h-full flex-col" data-testid="pdf-artifact-viewer">
	<div
		class="flex shrink-0 items-center justify-between border-b border-border-subtle bg-surface px-3 py-1"
	>
		<span class="font-mono text-[10px] uppercase tracking-wide text-subtle"> pdf preview </span>
		{#if status === 'ready'}
			<span class="font-mono text-[10px] text-muted">
				{pageCount}
				{pageCount === 1 ? 'page' : 'pages'}
			</span>
		{:else if status === 'loading'}
			<span class="flex items-center gap-1.5 font-mono text-[10px] text-muted">
				<span
					class="inline-block size-2 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
					aria-hidden="true"
				></span>
				rendering…
			</span>
		{:else if status === 'error'}
			<span class="font-mono text-[10px] text-accent">error</span>
		{/if}
	</div>

	<div
		bind:this={container}
		class="flex-1 overflow-auto bg-background p-3"
		data-testid="pdf-artifact-pages"
	>
		{#if status === 'loading' && pageCount === 0}
			<div class="flex h-full items-center justify-center gap-2 text-[12px] text-muted">
				<span
					class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
					aria-hidden="true"
				></span>
				Loading {title}…
			</div>
		{:else if status === 'error'}
			<div class="rounded border border-accent/30 bg-accent/5 px-3 py-2">
				<div class="font-mono text-[10px] font-medium uppercase text-accent">pdf error</div>
				<div class="mt-1 text-[12px] text-foreground">{errorMessage}</div>
			</div>
		{/if}
	</div>
</div>
