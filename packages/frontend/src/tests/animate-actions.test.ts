import { describe, it, expect, vi, beforeEach } from 'vitest';
import { zenReveal, zenFade, zenScale } from '$lib/actions/animate';

// Mock IntersectionObserver using a class (vi.fn arrow functions are not constructable)
let observerCallback: IntersectionObserverCallback;
const mockObserve = vi.fn();
const mockUnobserve = vi.fn();
const mockDisconnect = vi.fn();

beforeEach(() => {
	mockObserve.mockClear();
	mockUnobserve.mockClear();
	mockDisconnect.mockClear();

	class MockIntersectionObserver {
		constructor(callback: IntersectionObserverCallback) {
			observerCallback = callback;
		}
		observe = mockObserve;
		unobserve = mockUnobserve;
		disconnect = mockDisconnect;
	}
	vi.stubGlobal('IntersectionObserver', MockIntersectionObserver);
});

function createEntry(isIntersecting: boolean, target: HTMLElement): IntersectionObserverEntry {
	return {
		isIntersecting,
		target,
		boundingClientRect: {} as DOMRectReadOnly,
		intersectionRatio: isIntersecting ? 1 : 0,
		intersectionRect: {} as DOMRectReadOnly,
		rootBounds: null,
		time: Date.now()
	};
}

describe('zenReveal', () => {
	it('sets data-animate attribute on node', () => {
		const node = document.createElement('div');
		zenReveal(node);
		expect(node.getAttribute('data-animate')).toBe('');
	});

	it('adds is-visible class when intersecting', () => {
		const node = document.createElement('div');
		zenReveal(node);
		observerCallback([createEntry(true, node)], {} as IntersectionObserver);
		expect(node.classList.contains('is-visible')).toBe(true);
	});

	it('unobserves after first intersection by default (once=true)', () => {
		const node = document.createElement('div');
		zenReveal(node);
		observerCallback([createEntry(true, node)], {} as IntersectionObserver);
		expect(mockUnobserve).toHaveBeenCalledWith(node);
	});

	it('sets data-delay when delay option provided', () => {
		const node = document.createElement('div');
		zenReveal(node, { delay: 3 });
		expect(node.getAttribute('data-delay')).toBe('3');
	});

	it('disconnects observer on destroy', () => {
		const node = document.createElement('div');
		const result = zenReveal(node);
		result.destroy();
		expect(mockDisconnect).toHaveBeenCalled();
	});
});

describe('zenFade', () => {
	it('sets data-animate to fade', () => {
		const node = document.createElement('div');
		zenFade(node);
		expect(node.getAttribute('data-animate')).toBe('fade');
	});

	it('adds is-visible class when intersecting', () => {
		const node = document.createElement('div');
		zenFade(node);
		observerCallback([createEntry(true, node)], {} as IntersectionObserver);
		expect(node.classList.contains('is-visible')).toBe(true);
	});
});

describe('zenScale', () => {
	it('sets data-animate to scale', () => {
		const node = document.createElement('div');
		zenScale(node);
		expect(node.getAttribute('data-animate')).toBe('scale');
	});

	it('removes is-visible when not intersecting and once=false', () => {
		const node = document.createElement('div');
		zenScale(node, { once: false });
		observerCallback([createEntry(true, node)], {} as IntersectionObserver);
		expect(node.classList.contains('is-visible')).toBe(true);
		observerCallback([createEntry(false, node)], {} as IntersectionObserver);
		expect(node.classList.contains('is-visible')).toBe(false);
	});

	it('does not unobserve when once=false', () => {
		const node = document.createElement('div');
		zenScale(node, { once: false });
		observerCallback([createEntry(true, node)], {} as IntersectionObserver);
		expect(mockUnobserve).not.toHaveBeenCalled();
	});
});
