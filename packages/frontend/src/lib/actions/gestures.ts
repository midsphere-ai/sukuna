/**
 * Mobile gesture actions for native-feeling touch interactions.
 *
 * - pullToRefresh: Pull-down-to-refresh on scrollable containers
 * - swipeEdge: Edge swipe from left screen edge to trigger callback
 * - haptic: Trigger haptic feedback via Vibration API
 */

// --- Haptic feedback utility ---

/**
 * Trigger a short haptic vibration if the Vibration API is available.
 * @param duration Vibration duration in ms (default 10ms for a light tap)
 */
export function haptic(duration = 10): void {
	if (typeof navigator !== 'undefined' && navigator.vibrate) {
		navigator.vibrate(duration);
	}
}

// --- Pull-to-refresh action ---

type PullToRefreshOptions = {
	/** Async callback to invoke on refresh */
	onRefresh: () => Promise<void>;
	/** Pull distance in px to trigger refresh (default 80) */
	threshold?: number;
};

/**
 * Svelte action: pull-to-refresh on a scrollable container.
 * Shows a visual indicator while pulling and triggers onRefresh when threshold is met.
 *
 * Usage: <div use:pullToRefresh={{ onRefresh: loadData }}>
 */
export function pullToRefresh(node: HTMLElement, options: PullToRefreshOptions) {
	let { onRefresh, threshold = 80 } = options;
	let startY = 0;
	let pulling = false;
	let pullDistance = 0;
	let refreshing = false;

	// Create the pull indicator element
	const indicator = document.createElement('div');
	indicator.className = 'ptr-indicator';
	indicator.setAttribute('aria-hidden', 'true');
	indicator.innerHTML = `
		<div class="ptr-spinner">
			<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M21 12a9 9 0 1 1-6.219-8.56" />
			</svg>
		</div>
	`;
	node.style.position = 'relative';
	node.insertBefore(indicator, node.firstChild);

	function handleTouchStart(e: TouchEvent): void {
		if (refreshing) return;
		// Only activate when scrolled to top
		if (node.scrollTop > 0) return;
		startY = e.touches[0].clientY;
		pulling = true;
		pullDistance = 0;
	}

	function handleTouchMove(e: TouchEvent): void {
		if (!pulling || refreshing) return;
		const currentY = e.touches[0].clientY;
		const dy = currentY - startY;

		// Only pull down
		if (dy <= 0) {
			pullDistance = 0;
			updateIndicator();
			return;
		}

		// Ignore if there's significant horizontal movement
		pullDistance = Math.min(dy * 0.5, threshold * 1.5); // Dampen the pull
		updateIndicator();

		if (pullDistance > 10) {
			e.preventDefault(); // Prevent native scroll while pulling
		}
	}

	async function handleTouchEnd(): Promise<void> {
		if (!pulling || refreshing) return;
		pulling = false;

		if (pullDistance >= threshold) {
			refreshing = true;
			haptic(15);
			indicator.classList.add('ptr-refreshing');
			updateIndicator();

			try {
				await onRefresh();
			} finally {
				refreshing = false;
				indicator.classList.remove('ptr-refreshing');
				pullDistance = 0;
				updateIndicator();
			}
		} else {
			pullDistance = 0;
			updateIndicator();
		}
	}

	function updateIndicator(): void {
		const height = pulling || refreshing ? Math.max(0, pullDistance) : 0;
		const opacity = Math.min(1, height / threshold);
		const rotation = (height / threshold) * 360;

		indicator.style.height = `${height}px`;
		indicator.style.opacity = String(opacity);

		const spinner = indicator.querySelector('.ptr-spinner') as HTMLElement;
		if (spinner) {
			if (refreshing) {
				spinner.style.transform = '';
				spinner.classList.add('ptr-spinning');
			} else {
				spinner.style.transform = `rotate(${rotation}deg)`;
				spinner.classList.remove('ptr-spinning');
			}
		}
	}

	node.addEventListener('touchstart', handleTouchStart, { passive: true });
	node.addEventListener('touchmove', handleTouchMove, { passive: false });
	node.addEventListener('touchend', handleTouchEnd, { passive: true });

	return {
		update(newOptions: PullToRefreshOptions) {
			onRefresh = newOptions.onRefresh;
			threshold = newOptions.threshold ?? 80;
		},
		destroy() {
			node.removeEventListener('touchstart', handleTouchStart);
			node.removeEventListener('touchmove', handleTouchMove);
			node.removeEventListener('touchend', handleTouchEnd);
			indicator.remove();
		}
	};
}

// --- Edge swipe action ---

type SwipeEdgeOptions = {
	/** Callback when edge swipe is detected */
	onSwipe: () => void;
	/** Edge zone width in px from left screen edge (default 20) */
	edgeWidth?: number;
	/** Minimum horizontal swipe distance to trigger (default 60) */
	threshold?: number;
};

/**
 * Svelte action: detect swipe from the left screen edge to trigger a callback (e.g. open sidebar).
 *
 * Usage: <div use:swipeEdge={{ onSwipe: openMobileSidebar }}>
 */
export function swipeEdge(node: HTMLElement, options: SwipeEdgeOptions) {
	let { onSwipe, edgeWidth = 20, threshold = 60 } = options;
	let startX = 0;
	let startY = 0;
	let tracking = false;

	function handleTouchStart(e: TouchEvent): void {
		const x = e.touches[0].clientX;
		// Only activate near the left edge of the screen
		if (x <= edgeWidth) {
			startX = x;
			startY = e.touches[0].clientY;
			tracking = true;
		}
	}

	function handleTouchEnd(e: TouchEvent): void {
		if (!tracking) return;
		tracking = false;
		const dx = e.changedTouches[0].clientX - startX;
		const dy = Math.abs(e.changedTouches[0].clientY - startY);

		// Must be primarily horizontal and exceed threshold
		if (dx >= threshold && dy < dx) {
			haptic();
			onSwipe();
		}
	}

	node.addEventListener('touchstart', handleTouchStart, { passive: true });
	node.addEventListener('touchend', handleTouchEnd, { passive: true });

	return {
		update(newOptions: SwipeEdgeOptions) {
			onSwipe = newOptions.onSwipe;
			edgeWidth = newOptions.edgeWidth ?? 20;
			threshold = newOptions.threshold ?? 60;
		},
		destroy() {
			node.removeEventListener('touchstart', handleTouchStart);
			node.removeEventListener('touchend', handleTouchEnd);
		}
	};
}
