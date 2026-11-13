<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		EditorView,
		keymap,
		lineNumbers,
		highlightActiveLine,
		drawSelection,
		highlightActiveLineGutter,
		type ViewUpdate
	} from '@codemirror/view';
	import { EditorState, type Extension } from '@codemirror/state';
	import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
	import {
		syntaxHighlighting,
		defaultHighlightStyle,
		bracketMatching,
		foldGutter,
		indentOnInput,
		LanguageSupport
	} from '@codemirror/language';
	import { oneDark } from '@codemirror/theme-one-dark';
	import { javascript } from '@codemirror/lang-javascript';
	import { python } from '@codemirror/lang-python';
	import { html } from '@codemirror/lang-html';
	import { css } from '@codemirror/lang-css';
	import { json } from '@codemirror/lang-json';
	import { markdown } from '@codemirror/lang-markdown';
	import { xml } from '@codemirror/lang-xml';
	import { sql } from '@codemirror/lang-sql';
	import { rust } from '@codemirror/lang-rust';
	import { cpp } from '@codemirror/lang-cpp';
	import { java } from '@codemirror/lang-java';
	import { php } from '@codemirror/lang-php';
	import { go } from '@codemirror/lang-go';

	type Props = {
		content: string;
		language?: string;
		readonly?: boolean;
		wordWrap?: boolean;
		onchange?: (content: string) => void;
		onsave?: () => void;
	};

	let {
		content,
		language = 'text',
		readonly = true,
		wordWrap = false,
		onchange,
		onsave
	}: Props = $props();

	let editorContainer: HTMLDivElement | undefined = $state();
	let view: EditorView | undefined;
	let currentContent = '';

	function getLanguageExtension(lang: string): Extension[] {
		const langMap: Record<string, () => LanguageSupport> = {
			javascript: () => javascript(),
			typescript: () => javascript({ typescript: true }),
			jsx: () => javascript({ jsx: true }),
			tsx: () => javascript({ jsx: true, typescript: true }),
			python: () => python(),
			html: () => html(),
			svelte: () => html(),
			vue: () => html(),
			css: () => css(),
			scss: () => css(),
			json: () => json(),
			markdown: () => markdown(),
			xml: () => xml(),
			sql: () => sql(),
			rust: () => rust(),
			c: () => cpp(),
			cpp: () => cpp(),
			java: () => java(),
			kotlin: () => java(),
			php: () => php(),
			go: () => go(),
			bash: () => [] as unknown as LanguageSupport,
			shell: () => [] as unknown as LanguageSupport
		};
		const factory = langMap[lang];
		if (factory) {
			const result = factory();
			if (result instanceof LanguageSupport) return [result];
		}
		return [];
	}

	function isDarkMode(): boolean {
		if (typeof document === 'undefined') return false;
		return document.documentElement.getAttribute('data-theme') === 'dark';
	}

	/** Monochrome light theme */
	const replitLightTheme = EditorView.theme({
		'&': {
			backgroundColor: 'var(--ms-surface)',
			color: 'var(--ms-dark)',
			fontSize: '13px',
			fontFamily: 'var(--font-mono)'
		},
		'.cm-content': {
			caretColor: 'var(--ms-blue)',
			padding: '8px 0'
		},
		'.cm-cursor': {
			borderLeftColor: 'var(--ms-blue)',
			borderLeftWidth: '2px'
		},
		'&.cm-focused .cm-cursor': {
			borderLeftColor: 'var(--ms-blue)'
		},
		'.cm-gutters': {
			backgroundColor: 'var(--ms-elevated)',
			color: 'var(--ms-muted-text)',
			borderRight: '1px solid var(--ms-border-subtle)',
			fontSize: '12px',
			minWidth: '40px'
		},
		'.cm-gutter.cm-lineNumbers .cm-gutterElement': {
			padding: '0 8px 0 12px'
		},
		'.cm-activeLineGutter': {
			backgroundColor: 'var(--ms-elevated)',
			color: 'var(--ms-subtle-text)'
		},
		'.cm-activeLine': {
			backgroundColor: 'rgba(0, 0, 0, 0.03)'
		},
		'.cm-selectionBackground': {
			backgroundColor: 'rgba(0, 129, 242, 0.15) !important'
		},
		'&.cm-focused .cm-selectionBackground': {
			backgroundColor: 'rgba(0, 129, 242, 0.2) !important'
		},
		'.cm-matchingBracket': {
			backgroundColor: 'rgba(0, 129, 242, 0.12)',
			outline: '1px solid rgba(0, 129, 242, 0.3)'
		},
		'.cm-foldGutter .cm-gutterElement': {
			color: 'var(--ms-muted-text)',
			padding: '0 4px'
		},
		'.cm-line': {
			padding: '0 12px'
		},
		'.cm-scroller': {
			overflow: 'auto'
		}
	});

	/** Monochrome dark theme */
	const replitDarkTheme = EditorView.theme(
		{
			'&': {
				backgroundColor: 'var(--ms-surface)',
				color: 'var(--ms-dark)',
				fontSize: '13px',
				fontFamily: 'var(--font-mono)'
			},
			'.cm-content': {
				caretColor: 'var(--ms-blue)',
				padding: '8px 0'
			},
			'.cm-cursor': {
				borderLeftColor: 'var(--ms-blue)',
				borderLeftWidth: '2px'
			},
			'&.cm-focused .cm-cursor': {
				borderLeftColor: 'var(--ms-blue)'
			},
			'.cm-gutters': {
				backgroundColor: 'var(--ms-paper)',
				color: 'var(--ms-muted-text)',
				borderRight: '1px solid var(--ms-border)',
				fontSize: '12px',
				minWidth: '40px'
			},
			'.cm-gutter.cm-lineNumbers .cm-gutterElement': {
				padding: '0 8px 0 12px'
			},
			'.cm-activeLineGutter': {
				backgroundColor: 'var(--ms-elevated)',
				color: 'var(--ms-subtle-text)'
			},
			'.cm-activeLine': {
				backgroundColor: 'rgba(255, 255, 255, 0.03)'
			},
			'.cm-selectionBackground': {
				backgroundColor: 'rgba(77, 166, 255, 0.2) !important'
			},
			'&.cm-focused .cm-selectionBackground': {
				backgroundColor: 'rgba(77, 166, 255, 0.3) !important'
			},
			'.cm-matchingBracket': {
				backgroundColor: 'rgba(77, 166, 255, 0.15)',
				outline: '1px solid rgba(77, 166, 255, 0.3)'
			},
			'.cm-foldGutter .cm-gutterElement': {
				color: 'var(--ms-muted-text)',
				padding: '0 4px'
			},
			'.cm-line': {
				padding: '0 12px'
			},
			'.cm-scroller': {
				overflow: 'auto'
			}
		},
		{ dark: true }
	);

	function buildExtensions(): Extension[] {
		const dark = isDarkMode();
		const extensions: Extension[] = [
			lineNumbers(),
			highlightActiveLineGutter(),
			history(),
			foldGutter(),
			drawSelection(),
			indentOnInput(),
			bracketMatching(),
			highlightActiveLine(),
			keymap.of([...defaultKeymap, ...historyKeymap]),
			dark ? replitDarkTheme : replitLightTheme,
			dark ? oneDark : syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
			EditorState.readOnly.of(readonly),
			...getLanguageExtension(language)
		];

		if (wordWrap) {
			extensions.push(EditorView.lineWrapping);
		}

		if (onchange && !readonly) {
			extensions.push(
				EditorView.updateListener.of((update: ViewUpdate) => {
					if (update.docChanged) {
						currentContent = update.state.doc.toString();
						onchange(currentContent);
					}
				})
			);
		}

		if (onsave && !readonly) {
			extensions.push(
				keymap.of([
					{
						key: 'Mod-s',
						run: () => {
							onsave();
							return true;
						}
					}
				])
			);
		}

		return extensions;
	}

	function createEditor(): void {
		if (!editorContainer) return;
		destroyEditor();

		const state = EditorState.create({
			doc: content,
			extensions: buildExtensions()
		});

		view = new EditorView({
			state,
			parent: editorContainer
		});
		currentContent = content;
	}

	function destroyEditor(): void {
		if (view) {
			view.destroy();
			view = undefined;
		}
	}

	// Recreate editor when container mounts
	$effect(() => {
		if (editorContainer) {
			createEditor();
		}
	});

	// Update content externally without recreating the whole editor
	$effect(() => {
		if (view && content !== currentContent) {
			const transaction = view.state.update({
				changes: {
					from: 0,
					to: view.state.doc.length,
					insert: content
				}
			});
			view.dispatch(transaction);
			currentContent = content;
		}
	});

	// Recreate when language, readonly, or wordWrap changes
	$effect(() => {
		// Track these reactive values
		void language;
		void readonly;
		void wordWrap;
		if (view && editorContainer) {
			createEditor();
		}
	});

	// Watch for theme changes
	let themeObserver: MutationObserver | undefined;
	$effect(() => {
		if (editorContainer && typeof document !== 'undefined') {
			themeObserver?.disconnect();
			themeObserver = new MutationObserver(() => {
				if (view) createEditor();
			});
			themeObserver.observe(document.documentElement, {
				attributes: true,
				attributeFilter: ['data-theme']
			});
			return () => themeObserver?.disconnect();
		}
	});

	onDestroy(() => {
		destroyEditor();
		themeObserver?.disconnect();
	});
</script>

<div
	bind:this={editorContainer}
	class="code-mirror-editor h-full w-full overflow-hidden"
	data-testid="codemirror-editor"
></div>

<style>
	.code-mirror-editor :global(.cm-editor) {
		height: 100%;
		outline: none;
	}
	.code-mirror-editor :global(.cm-scroller) {
		font-family: var(--font-mono);
		line-height: 1.6;
	}
	.code-mirror-editor :global(.cm-focused) {
		outline: none;
	}
</style>
