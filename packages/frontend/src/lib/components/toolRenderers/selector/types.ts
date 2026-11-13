/**
 * Type definitions for the in-preview component selector.
 *
 * The selector lets a user click an element inside the preview iframe, edit
 * its styles, and ship those edits back to the agent as a structured chat
 * message so the agent rewrites the source. A second tab lets the user edit
 * global design tokens the same way.
 *
 * The iframe-side client speaks a postMessage protocol. The types below describe
 * the shape of `selection` payloads emitted from the iframe and the payloads
 * the parent ships to the chat pipeline on "Apply".
 */

export interface SelectorSourceLoc {
	fileName: string;
	lineNumber: number;
	columnNumber: number;
}

export interface SelectorBoundingRect {
	x: number;
	y: number;
	width: number;
	height: number;
}

export interface Selection {
	sourceLoc: SelectorSourceLoc | null;
	tagName: string;
	classList: string[];
	outerHTMLSnippet: string;
	computedStyles: Record<string, string>;
	boundingRect: SelectorBoundingRect;
}

export interface ElementApplyPayload {
	sourceLoc: SelectorSourceLoc | null;
	tagName: string;
	classList: string[];
	/** CSS prop (camelCase or kebab-case) to requested value. */
	changes: Record<string, string>;
	outerHTMLSnippet: string;
}

export interface DesignSystemApplyPayload {
	framework: 'next' | 'expo' | string;
	/** Token name (e.g. `primary`, `fontSans`, `radius`) to requested value. */
	changes: Record<string, string>;
}

export interface DesignTokens {
	colors: Record<string, string>;
	fonts: { sans?: string; serif?: string; mono?: string };
	radius?: string;
	spacing?: string;
}

/** Parent -> iframe message union. */
export type SelectorOutboundMessage =
	| { type: 'sandbox-selector:enable' }
	| { type: 'sandbox-selector:disable' }
	| { type: 'sandbox-selector:apply-element-style'; styles: Record<string, string> }
	| { type: 'sandbox-selector:clear-element-styles' }
	| { type: 'sandbox-selector:apply-root-css'; css: string }
	| { type: 'sandbox-selector:clear-root-css' }
	| { type: 'sandbox-selector:restore-selection'; sourceLoc: SelectorSourceLoc };

/** Iframe -> parent message union. */
export type SelectorInboundMessage =
	| { type: 'sandbox-selector:ready'; framework: 'react' | 'unknown' }
	| { type: 'sandbox-selector:hover'; rect: SelectorBoundingRect }
	| { type: 'sandbox-selector:picked'; selection: Selection }
	| { type: 'sandbox-selector:cleared' }
	| { type: 'sandbox-selector:restored'; selection: Selection | null };
