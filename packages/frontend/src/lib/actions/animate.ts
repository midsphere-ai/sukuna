/**
 * Scroll-triggered animation actions using IntersectionObserver.
 * Works with the CSS animations defined in app.css (zenReveal, zenFade, zenScale).
 *
 * Usage:
 *   <div use:zenReveal>...</div>
 *   <div use:zenFade={{ delay: 2 }}>...</div>
 *   <div use:zenScale={{ delay: 3, threshold: 0.3 }}>...</div>
 */

type AnimateOptions = {
	/** Stagger delay index (1-6), maps to data-delay attribute */
	delay?: number;
	/** IntersectionObserver threshold (0-1), default 0.15 */
	threshold?: number;
	/** Only animate once, default true */
	once?: boolean;
};

function createAnimateAction(animationType: string) {
	return function (node: HTMLElement, options: AnimateOptions = {}) {
		const { delay, threshold = 0.15, once = true } = options;

		node.setAttribute('data-animate', animationType);
		if (delay) {
			node.setAttribute('data-delay', String(delay));
		}

		const observer = new IntersectionObserver(
			(entries) => {
				for (const entry of entries) {
					if (entry.isIntersecting) {
						node.classList.add('is-visible');
						if (once) {
							observer.unobserve(node);
						}
					} else if (!once) {
						node.classList.remove('is-visible');
					}
				}
			},
			{ threshold }
		);

		observer.observe(node);

		return {
			destroy() {
				observer.disconnect();
			}
		};
	};
}

/** Slide up + fade + blur reveal animation */
export const zenReveal = createAnimateAction('');

/** Fade + blur animation (no translate) */
export const zenFade = createAnimateAction('fade');

/** Scale up + fade + blur animation */
export const zenScale = createAnimateAction('scale');

/**
 * Animate an element's width from 0% to a target.
 * The element must have a CSS transition on width (e.g. `transition-all duration-500`).
 * Pass the target width as the parameter (e.g. `use:animateWidth={'72%'}`).
 */
export function animateWidth(node: HTMLElement, targetWidth: string) {
	node.style.width = '0%';
	requestAnimationFrame(() => {
		requestAnimationFrame(() => {
			node.style.width = targetWidth;
		});
	});

	return {
		update(newWidth: string) {
			node.style.width = newWidth;
		}
	};
}

/**
 * Animate a number counting up from 0 to the target value.
 * Usage: `<span use:countUp={1234}></span>`
 */
export function countUp(node: HTMLElement, target: number) {
	const duration = 600;
	const start = performance.now();
	const format = (n: number) => Math.round(n).toLocaleString();
	let rafId: number;

	function easeOutCubic(t: number): number {
		return 1 - Math.pow(1 - t, 3);
	}

	function tick(now: number) {
		const elapsed = now - start;
		const progress = Math.min(elapsed / duration, 1);
		const value = target * easeOutCubic(progress);
		node.textContent = format(value);

		if (progress < 1) {
			rafId = requestAnimationFrame(tick);
		}
	}

	rafId = requestAnimationFrame(tick);

	return {
		update(newTarget: number) {
			// On value change, just snap to new value
			node.textContent = format(newTarget);
		},
		destroy() {
			cancelAnimationFrame(rafId);
		}
	};
}
