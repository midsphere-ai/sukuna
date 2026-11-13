/**
 * Friendly, non-technical labels for selector elements.
 *
 * The selector feature is user-facing, so we avoid CSS jargon, tag names,
 * and class lists. Prefer the element's own visible text (e.g. the button
 * copy "Get started") when present, otherwise fall back to a category name
 * based on the tag ("Heading", "Button", "Image", ...).
 */
import type { Selection } from './types';

const TAG_CATEGORY: Record<string, string> = {
	h1: 'Heading',
	h2: 'Heading',
	h3: 'Heading',
	h4: 'Heading',
	h5: 'Heading',
	h6: 'Heading',
	button: 'Button',
	a: 'Link',
	img: 'Image',
	svg: 'Icon',
	input: 'Input',
	textarea: 'Input',
	select: 'Input',
	section: 'Section',
	article: 'Article',
	main: 'Main area',
	header: 'Header',
	footer: 'Footer',
	nav: 'Navigation',
	aside: 'Sidebar',
	ul: 'List',
	ol: 'List',
	li: 'List item',
	p: 'Paragraph',
	form: 'Form'
};

export function getFriendlyElementLabel(selection: Selection): string {
	// 1. Prefer visible text content parsed from the snippet.
	const snippet = selection.outerHTMLSnippet ?? '';
	const visible = snippet
		.replace(/<[^>]*>/g, ' ')
		.replace(/\s+/g, ' ')
		.trim();
	if (visible.length > 0) {
		return visible.length > 30 ? visible.slice(0, 29) + '…' : visible;
	}
	// 2. Tag-category fallback.
	const tag = (selection.tagName ?? '').toLowerCase();
	return TAG_CATEGORY[tag] ?? 'Block';
}
