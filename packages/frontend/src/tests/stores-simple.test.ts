import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock $app/navigation
vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

// Mock localStorage
const mockStorage: Record<string, string> = {};
vi.stubGlobal('localStorage', {
	getItem: vi.fn((key: string) => mockStorage[key] ?? null),
	setItem: vi.fn((key: string, value: string) => {
		mockStorage[key] = value;
	}),
	removeItem: vi.fn((key: string) => {
		delete mockStorage[key];
	}),
	clear: vi.fn(() => {
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	}),
	length: 0,
	key: vi.fn()
});

// Mock sessionStorage (needed by auth store dependency chain)
vi.stubGlobal('sessionStorage', {
	getItem: vi.fn(() => null),
	setItem: vi.fn(),
	removeItem: vi.fn(),
	clear: vi.fn(),
	length: 0,
	key: vi.fn()
});

describe('toast store', () => {
	beforeEach(async () => {
		vi.useFakeTimers();
		vi.resetModules();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('starts empty', async () => {
		const { toasts } = await import('$stores/toast');
		expect(get(toasts)).toEqual([]);
	});

	it('adds a success toast', async () => {
		const { toasts } = await import('$stores/toast');
		toasts.success('Done!');
		const items = get(toasts);
		expect(items).toHaveLength(1);
		expect(items[0].type).toBe('success');
		expect(items[0].message).toBe('Done!');
	});

	it('adds error, warning, info toasts', async () => {
		const { toasts } = await import('$stores/toast');
		toasts.error('Fail');
		toasts.warning('Watch out');
		toasts.info('FYI');
		const items = get(toasts);
		expect(items).toHaveLength(3);
		expect(items.map((t) => t.type)).toEqual(['error', 'warning', 'info']);
	});

	it('removes a toast by id', async () => {
		const { toasts } = await import('$stores/toast');
		const id = toasts.success('temp');
		expect(get(toasts)).toHaveLength(1);
		toasts.remove(id);
		expect(get(toasts)).toHaveLength(0);
	});

	it('auto-removes toast after duration', async () => {
		const { toasts } = await import('$stores/toast');
		toasts.success('Auto', 1000);
		expect(get(toasts)).toHaveLength(1);
		// Duration (1000ms) triggers dismiss, then 250ms exit animation before removal
		vi.advanceTimersByTime(1250);
		expect(get(toasts)).toHaveLength(0);
	});

	it('does not auto-remove toast with duration 0', async () => {
		const { toasts } = await import('$stores/toast');
		toasts.success('Sticky', 0);
		expect(get(toasts)).toHaveLength(1);
		vi.advanceTimersByTime(10000);
		expect(get(toasts)).toHaveLength(1);
	});
});

describe('sidebar store', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it('starts with sidebar visible and mobile closed', async () => {
		const { sidebarHidden, sidebarMobileOpen } = await import('$stores/sidebar');
		expect(get(sidebarHidden)).toBe(false);
		expect(get(sidebarMobileOpen)).toBe(false);
	});

	it('toggleSidebar toggles hidden state', async () => {
		const { sidebarHidden, toggleSidebar } = await import('$stores/sidebar');
		toggleSidebar();
		expect(get(sidebarHidden)).toBe(true);
		toggleSidebar();
		expect(get(sidebarHidden)).toBe(false);
	});

	it('openMobileSidebar and closeMobileSidebar work', async () => {
		const { sidebarMobileOpen, openMobileSidebar, closeMobileSidebar } =
			await import('$stores/sidebar');
		openMobileSidebar();
		expect(get(sidebarMobileOpen)).toBe(true);
		closeMobileSidebar();
		expect(get(sidebarMobileOpen)).toBe(false);
	});
});

describe('search store', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it('starts closed', async () => {
		const { searchOpen } = await import('$stores/search');
		expect(get(searchOpen)).toBe(false);
	});

	it('openSearch / closeSearch work', async () => {
		const { searchOpen, openSearch, closeSearch } = await import('$stores/search');
		openSearch();
		expect(get(searchOpen)).toBe(true);
		closeSearch();
		expect(get(searchOpen)).toBe(false);
	});

	it('toggleSearch toggles state', async () => {
		const { searchOpen, toggleSearch } = await import('$stores/search');
		toggleSearch();
		expect(get(searchOpen)).toBe(true);
		toggleSearch();
		expect(get(searchOpen)).toBe(false);
	});
});

describe('page store', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it('has default values', async () => {
		const { pageTitle, showHeaderTitle } = await import('$stores/page');
		expect(get(pageTitle)).toBe('Home');
		expect(get(showHeaderTitle)).toBe(true);
	});

	it('can update page title', async () => {
		const { pageTitle } = await import('$stores/page');
		pageTitle.set('Settings');
		expect(get(pageTitle)).toBe('Settings');
	});
});

describe('chatInput store', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it('starts with empty prefill and no auto-submit', async () => {
		const { chatInputPrefill, chatInputAutoSubmit } = await import('$stores/chatInput');
		expect(get(chatInputPrefill)).toBe('');
		expect(get(chatInputAutoSubmit)).toBe(false);
	});

	it('can set prefill and auto-submit', async () => {
		const { chatInputPrefill, chatInputAutoSubmit } = await import('$stores/chatInput');
		chatInputPrefill.set('Hello');
		chatInputAutoSubmit.set(true);
		expect(get(chatInputPrefill)).toBe('Hello');
		expect(get(chatInputAutoSubmit)).toBe(true);
	});
});

describe('onboarding store', () => {
	beforeEach(() => {
		vi.resetModules();
		Object.keys(mockStorage).forEach((key) => delete mockStorage[key]);
	});

	it('starts not complete', async () => {
		const { onboardingComplete } = await import('$stores/onboarding');
		expect(get(onboardingComplete)).toBe(false);
	});

	it('markOnboardingComplete sets true and persists', async () => {
		const { onboardingComplete, markOnboardingComplete } = await import('$stores/onboarding');
		markOnboardingComplete();
		expect(get(onboardingComplete)).toBe(true);
		expect(mockStorage['midsphere-onboarding-complete']).toBe('true');
	});

	it('resetOnboarding sets false and removes storage', async () => {
		const { onboardingComplete, markOnboardingComplete, resetOnboarding } =
			await import('$stores/onboarding');
		markOnboardingComplete();
		resetOnboarding();
		expect(get(onboardingComplete)).toBe(false);
		expect(mockStorage['midsphere-onboarding-complete']).toBeUndefined();
	});

	it('loads from localStorage on init', async () => {
		mockStorage['midsphere-onboarding-complete'] = 'true';
		const { onboardingComplete } = await import('$stores/onboarding');
		expect(get(onboardingComplete)).toBe(true);
	});
});

describe('usageLimit store', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it('starts with null modal', async () => {
		const { usageLimitModal } = await import('$stores/usageLimit');
		expect(get(usageLimitModal)).toBeNull();
	});

	it('show and dismiss work', async () => {
		const { usageLimitModal } = await import('$stores/usageLimit');
		usageLimitModal.show({ limitType: 'credits', message: 'Limit reached' });
		expect(get(usageLimitModal)).toEqual({
			limitType: 'credits',
			message: 'Limit reached'
		});
		usageLimitModal.dismiss();
		expect(get(usageLimitModal)).toBeNull();
	});

	it('detectLimitError matches known patterns', async () => {
		const { detectLimitError } = await import('$stores/usageLimit');
		expect(detectLimitError('Too many concurrent tasks running')).toEqual({
			limitType: 'concurrent_tasks',
			message: 'Too many concurrent tasks running'
		});
		expect(detectLimitError('Cannot use custom LLM on this plan')).toEqual({
			limitType: 'custom_llm',
			message: 'Cannot use custom LLM on this plan'
		});
		expect(detectLimitError('Cannot use custom MCP on this plan')).toEqual({
			limitType: 'custom_mcp',
			message: 'Cannot use custom MCP on this plan'
		});
		expect(detectLimitError('Enterprise features require a paid subscription.')).toEqual({
			limitType: 'enterprise_mode',
			message: 'Enterprise features require a paid subscription.'
		});
		expect(
			detectLimitError(
				'Insufficient credits. Purchase more credits or upgrade your plan to continue.'
			)
		).toEqual({
			limitType: 'credits',
			message: 'Insufficient credits. Purchase more credits or upgrade your plan to continue.'
		});
	});

	it('detectLimitError returns null for unmatched messages', async () => {
		const { detectLimitError } = await import('$stores/usageLimit');
		expect(detectLimitError('Some random error')).toBeNull();
	});
});
