import { marked, Marked } from 'marked';
import { hljs } from './highlightSetup';

// LRU cache for parsed markdown — avoids re-parsing identical text on
// re-renders and when scrolling through already-loaded messages.
const CACHE_MAX = 256;
const mdCache = new Map<string, string>();

// Configure marked with syntax highlighting renderer
marked.use({
	renderer: {
		code({ text, lang }: { text: string; lang?: string }) {
			const language = lang?.trim().toLowerCase();
			let highlighted: string;
			try {
				if (language && hljs.getLanguage(language)) {
					highlighted = hljs.highlight(text, { language }).value;
				} else {
					// No language specified or unknown — auto-detect
					highlighted = hljs.highlightAuto(text).value;
				}
			} catch {
				// Fallback to escaped text
				highlighted = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
			}
			const langClass = language ? ` language-${language}` : '';
			return `<pre><code class="hljs${langClass}">${highlighted}</code></pre>`;
		}
	}
});

export function renderMarkdown(text: string, skipCache = false): string {
	if (!skipCache) {
		const cached = mdCache.get(text);
		if (cached !== undefined) return cached;
	}

	let html: string;
	try {
		html = marked.parse(text, { async: false, breaks: true, gfm: true }) as string;
	} catch {
		// Fallback to escaped plain text if markdown parsing fails
		html = text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/\n/g, '<br>');
	}

	if (!skipCache) {
		// Evict oldest entries when cache is full
		if (mdCache.size >= CACHE_MAX) {
			const first = mdCache.keys().next().value;
			if (first !== undefined) mdCache.delete(first);
		}
		mdCache.set(text, html);
	}
	return html;
}

// --- Experimental markdown renderer ---

const expMdCache = new Map<string, string>();

const experimentalMarked = new Marked({
	breaks: true,
	gfm: true,
	renderer: {
		code({ text, lang }: { text: string; lang?: string }) {
			const language = lang?.trim().toLowerCase();
			let highlighted: string;
			try {
				if (language && hljs.getLanguage(language)) {
					highlighted = hljs.highlight(text, { language }).value;
				} else {
					highlighted = hljs.highlightAuto(text).value;
				}
			} catch {
				highlighted = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
			}
			const langClass = language ? ` language-${language}` : '';
			const escaped = text.replace(/`/g, '\\`').replace(/\$/g, '\\$');
			return `<div class="relative group"><button onclick="navigator.clipboard.writeText(this.parentElement.querySelector('code').textContent)" class="absolute right-2 top-2 rounded-md bg-surface border border-border-subtle px-2 py-1 text-[10px] text-muted opacity-0 transition-opacity group-hover:opacity-100 hover:text-accent">Copy</button><pre><code class="hljs${langClass}">${highlighted}</code></pre></div>`;
		},
		link({ href, text }: { href: string; text: string }) {
			const isExternal = href.startsWith('http');
			const attrs = isExternal ? ' target="_blank" rel="noopener noreferrer"' : '';
			return `<a href="${href}"${attrs}>${text}</a>`;
		},
		listitem({ text }: { text: string }) {
			// Task list support: detect [ ] and [x] at start
			if (text.startsWith('[x] ') || text.startsWith('[X] ')) {
				return `<li class="list-none"><label class="inline-flex items-center gap-1.5"><input type="checkbox" checked disabled class="rounded" /><span>${text.slice(4)}</span></label></li>`;
			}
			if (text.startsWith('[ ] ')) {
				return `<li class="list-none"><label class="inline-flex items-center gap-1.5"><input type="checkbox" disabled class="rounded" /><span>${text.slice(4)}</span></label></li>`;
			}
			return `<li>${text}</li>`;
		}
	}
});

export function renderMarkdownExperimental(text: string, skipCache = false): string {
	if (!skipCache) {
		const cached = expMdCache.get(text);
		if (cached !== undefined) return cached;
	}

	let html: string;
	try {
		html = experimentalMarked.parse(text, { async: false }) as string;
	} catch {
		html = text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/\n/g, '<br>');
	}

	if (!skipCache) {
		if (expMdCache.size >= CACHE_MAX) {
			const first = expMdCache.keys().next().value;
			if (first !== undefined) expMdCache.delete(first);
		}
		expMdCache.set(text, html);
	}
	return html;
}
