/**
 * Accessible tooltip action using a portal DOM element.
 * Appends to document.body to avoid overflow clipping, with viewport-aware positioning.
 *
 * Usage:
 *   <button use:tooltip={'Save file'}>...</button>
 *   <button use:tooltip={{ text: 'Save file', position: 'bottom', shortcut: 'Ctrl+S' }}>...</button>
 */

export type TooltipPosition = 'top' | 'bottom' | 'left' | 'right';

export type TooltipOptions =
	| string
	| {
			text: string;
			position?: TooltipPosition;
			shortcut?: string;
	  };

function normalize(options: TooltipOptions): {
	text: string;
	position: TooltipPosition;
	shortcut?: string;
} {
	if (typeof options === 'string') {
		return { text: options, position: 'top' };
	}
	return { text: options.text, position: options.position ?? 'top', shortcut: options.shortcut };
}

const GAP = 6;
const VIEWPORT_PADDING = 8;

function positionTooltip(
	el: HTMLElement,
	rect: DOMRect,
	preferred: TooltipPosition
): TooltipPosition {
	const tw = el.offsetWidth;
	const th = el.offsetHeight;
	let pos = preferred;

	// Flip if tooltip would overflow the viewport
	if (pos === 'top' && rect.top - th - GAP < VIEWPORT_PADDING) pos = 'bottom';
	else if (pos === 'bottom' && rect.bottom + th + GAP > window.innerHeight - VIEWPORT_PADDING)
		pos = 'top';
	else if (pos === 'left' && rect.left - tw - GAP < VIEWPORT_PADDING) pos = 'right';
	else if (pos === 'right' && rect.right + tw + GAP > window.innerWidth - VIEWPORT_PADDING)
		pos = 'left';

	let top: number;
	let left: number;

	switch (pos) {
		case 'top':
			top = rect.top - th - GAP;
			left = rect.left + rect.width / 2 - tw / 2;
			break;
		case 'bottom':
			top = rect.bottom + GAP;
			left = rect.left + rect.width / 2 - tw / 2;
			break;
		case 'left':
			top = rect.top + rect.height / 2 - th / 2;
			left = rect.left - tw - GAP;
			break;
		case 'right':
			top = rect.top + rect.height / 2 - th / 2;
			left = rect.right + GAP;
			break;
	}

	// Clamp horizontally to keep within viewport
	left = Math.max(VIEWPORT_PADDING, Math.min(left, window.innerWidth - tw - VIEWPORT_PADDING));
	// Clamp vertically
	top = Math.max(VIEWPORT_PADDING, Math.min(top, window.innerHeight - th - VIEWPORT_PADDING));

	el.style.top = `${top}px`;
	el.style.left = `${left}px`;

	return pos;
}

export function tooltip(node: HTMLElement, options: TooltipOptions) {
	let opts = normalize(options);
	let showTimeout: ReturnType<typeof setTimeout> | undefined;
	let portalEl: HTMLDivElement | null = null;
	let visible = false;

	function show(): void {
		showTimeout = setTimeout(() => {
			if (portalEl) return;

			const label = opts.shortcut ? `${opts.text} (${opts.shortcut})` : opts.text;

			portalEl = document.createElement('div');
			portalEl.className = 'tooltip-portal';
			portalEl.textContent = label;
			portalEl.setAttribute('role', 'tooltip');
			document.body.appendChild(portalEl);

			// Position after appending so we can measure
			const rect = node.getBoundingClientRect();
			positionTooltip(portalEl, rect, opts.position);

			// Trigger animation on next frame
			requestAnimationFrame(() => {
				portalEl?.classList.add('tooltip-visible');
			});

			visible = true;
		}, 400);
	}

	function hide(): void {
		clearTimeout(showTimeout);
		if (portalEl) {
			portalEl.remove();
			portalEl = null;
		}
		visible = false;
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && visible) {
			hide();
		}
	}

	node.addEventListener('pointerenter', show);
	node.addEventListener('pointerleave', hide);
	node.addEventListener('pointerdown', hide);
	node.addEventListener('focus', show);
	node.addEventListener('blur', hide);
	node.addEventListener('keydown', handleKeydown);

	return {
		update(newOptions: TooltipOptions) {
			opts = normalize(newOptions);
			// If tooltip is currently visible, update its text
			if (portalEl) {
				const label = opts.shortcut ? `${opts.text} (${opts.shortcut})` : opts.text;
				portalEl.textContent = label;
				const rect = node.getBoundingClientRect();
				positionTooltip(portalEl, rect, opts.position);
			}
		},
		destroy() {
			clearTimeout(showTimeout);
			hide();
			node.removeEventListener('pointerenter', show);
			node.removeEventListener('pointerleave', hide);
			node.removeEventListener('pointerdown', hide);
			node.removeEventListener('focus', show);
			node.removeEventListener('blur', hide);
			node.removeEventListener('keydown', handleKeydown);
		}
	};
}
