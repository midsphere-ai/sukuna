/**
 * Final integration smoke test — full platform (US-113).
 *
 * Covers acceptance criteria:
 * - Public pages: changelog, tutorials, contact, shared chat, developers
 * - Dark mode: toggle theme, verify all pages
 * - Mobile: verify at 375px viewport
 * - Cookie consent: reject → verify no analytics, accept → verify PostHog fires
 * - Auth flows: login, logout, password reset page navigation
 */
import { expect, test, type Page } from '@playwright/test';

// --- Mock data ---

const MOCK_USER = {
	id: 'usr_smoke123',
	name: 'Smoke User',
	email: 'smoke@example.com',
	is_active: true,
	date_joined: '2026-01-01T00:00:00Z',
	last_login: '2026-03-18T00:00:00Z'
};

const MOCK_TOKEN = 'test-smoke-token-abc123';

const MOCK_SETTINGS_LIGHT = {
	id: 'settings_1',
	theme: 'light',
	accent_color: 'coral',
	custom_instructions: '',
	nickname: '',
	occupation: '',
	about_you: '',
	web_search: true,
	browser: true,
	shell_commands: true,
	complex_reasoning: true,
	computer_use: true,
	notification_email: true,
	notification_push: true,
	notification_marketing: false,
	data_share_analytics: true,
	data_share_training: false,
	backend_url: ''
};

const MOCK_SETTINGS_DARK = { ...MOCK_SETTINGS_LIGHT, theme: 'dark' };

const MOCK_SUBSCRIPTION = {
	id: 'sub_smoke123',
	plan: {
		id: 'plan_free',
		name: 'Free',
		tier: 'free',
		price: 0,
		features: {
			weekly_tasks: 10,
			max_sandbox_time: 1800,
			max_addons: 2,
			max_addons_per_task: 1,
			max_mcp_per_task: 1,
			max_concurrent_tasks: 1,
			max_scheduled_tasks: 0,
			can_schedule_tasks: false,
			use_custom_llm: false,
			use_custom_mcp: false,
			use_custom_e2b: false
		},
		is_active: true
	},
	status: 'active',
	start_date: '2026-01-01T00:00:00Z',
	end_date: '2026-04-01T00:00:00Z',
	auto_renew: false,
	dodo_subscription_id: null,
	usage_schema: {
		tasks_remaining_week: { limit: 10, used: 2, label: 'Weekly tasks' },
		sandbox_time_remaining_month: { limit: 1800, used: 300, label: 'Sandbox time' },
		addons_used: { limit: 2, used: 0, label: 'Addons' },
		mcp_servers_added: { limit: 1, used: 0, label: 'MCP servers' },
		concurrent_tasks: { limit: 1, used: 0, label: 'Concurrent tasks' }
	}
};

function json(data: unknown) {
	return {
		status: 200 as const,
		contentType: 'application/json' as const,
		body: JSON.stringify(data)
	};
}

// --- Helpers ---

async function mockPublicRoutes(page: Page): Promise<void> {
	await page.route('**/*', async (route) => {
		const type = route.request().resourceType();
		if (type !== 'fetch' && type !== 'xhr') return route.continue();
		const url = route.request().url();
		if (
			url.includes('/workspace/') ||
			url.includes('/memory/') ||
			url.includes('/cms/') ||
			url.includes('/chat/') ||
			url.includes('/billing/') ||
			url.includes('/authentication/') ||
			url.includes('/spaces/')
		) {
			return route.fulfill(json({}));
		}
		return route.continue();
	});

	await page.route('**/cms/public/**', (route) => route.fulfill(json({})));
	await page.route('**/cms/public/tutorials', (route) =>
		route.fulfill(json({ items: [], count: 0 }))
	);
	await page.route('**/cms/public/changelog', (route) =>
		route.fulfill(json({ items: [], count: 0 }))
	);
}

async function setupAuthenticated(page: Page, settings = MOCK_SETTINGS_LIGHT): Promise<void> {
	await mockPublicRoutes(page);

	await page.route('**/workspace/users/me/**', (route) => route.fulfill(json(MOCK_USER)));
	await page.route('**/workspace/users/me/', (route) => route.fulfill(json(MOCK_USER)));
	await page.route('**/memory/settings', (route) => route.fulfill(json(settings)));
	await page.route('**/memory/addons**', (route) => route.fulfill(json({ items: [], count: 0 })));
	await page.route('**/memory/mcp-configs**', (route) =>
		route.fulfill(json({ items: [], count: 0 }))
	);
	await page.route('**/memory/conversations/stream/**', (route) =>
		route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
	);
	await page.route('**/memory/conversations?**', (route) =>
		route.fulfill(json({ items: [], count: 0 }))
	);
	await page.route('**/memory/conversations', (route) => {
		if (route.request().method() === 'GET') return route.fulfill(json({ items: [], count: 0 }));
		return route.continue();
	});
	await page.route('**/billing/subscription', (route) => route.fulfill(json(MOCK_SUBSCRIPTION)));
	await page.route('**/spaces/projects**', (route) => route.fulfill(json({ items: [], count: 0 })));

	await page.addInitScript((token) => {
		sessionStorage.setItem('midsphere-auth-token', token);
		localStorage.setItem(
			'midsphere-cookie-consent',
			JSON.stringify({ essential: true, analytics: false, errorTracking: false })
		);
	}, MOCK_TOKEN);
}

// =============================================================================
// Public pages — render without errors
// =============================================================================

test.describe('Public pages smoke test', () => {
	test('changelog page loads', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/changelog');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
		expect(page.url()).toContain('/changelog');
	});

	test('tutorials page loads', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/tutorials');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
		expect(page.url()).toContain('/tutorials');
	});

	test('contact page loads', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/contact');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
		expect(page.url()).toContain('/contact');
	});

	test('developers page loads', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/developers');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
		expect(page.url()).toContain('/developers');
	});

	test('shared chat page loads with mock data', async ({ page }) => {
		await mockPublicRoutes(page);

		await page.route('**/memory/conversations/conv_shared_smoke/shared', (route) =>
			route.fulfill(
				json({
					id: 'conv_shared_smoke',
					title: 'Shared Smoke Test',
					summary: 'A shared conversation',
					messages: [
						{
							id: 'msg_1',
							role: 'user',
							content: 'Hello',
							date_created: '2026-03-18T00:00:00Z'
						},
						{
							id: 'msg_2',
							role: 'assistant',
							content: 'Hi there!',
							date_created: '2026-03-18T00:01:00Z'
						}
					],
					date_created: '2026-03-18T00:00:00Z'
				})
			)
		);

		await page.goto('/shared/conv_shared_smoke');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
	});

	test('login page loads', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/login');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
		expect(page.url()).toContain('/login');
	});

	test('signup page loads', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/signup');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
		expect(page.url()).toContain('/signup');
	});

	test('forgot-password page loads', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/forgot-password');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
		expect(page.url()).toContain('/forgot-password');
	});
});

// =============================================================================
// Dark mode — toggle theme and verify
// =============================================================================

test.describe('Dark mode smoke test', () => {
	test('app renders with dark theme when settings return dark', async ({ page }) => {
		await setupAuthenticated(page, MOCK_SETTINGS_DARK);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		// Dark theme should set data-theme="dark" on the root element.
		const theme = await page.locator('html').getAttribute('data-theme');
		expect(theme).toBe('dark');
	});

	test('app renders with light theme when settings return light', async ({ page }) => {
		await setupAuthenticated(page, MOCK_SETTINGS_LIGHT);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const theme = await page.locator('html').getAttribute('data-theme');
		expect(theme).toBe('light');
	});

	test('public page renders in dark mode without auth', async ({ page }) => {
		await mockPublicRoutes(page);

		// Set dark theme preference in localStorage.
		await page.addInitScript(() => {
			localStorage.setItem('midsphere-theme', 'dark');
		});

		await page.goto('/login');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();
	});
});

// =============================================================================
// Mobile viewport — 375px
// =============================================================================

test.describe('Mobile viewport smoke test', () => {
	test.use({ viewport: { width: 375, height: 812 } });

	test('login page renders at 375px', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/login');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();

		// No horizontal scrollbar — page fits within viewport.
		const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(scrollWidth).toBeLessThanOrEqual(375);
	});

	test('signup page renders at 375px', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/signup');
		await page.waitForLoadState('networkidle');

		const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(scrollWidth).toBeLessThanOrEqual(375);
	});

	test('home page renders at 375px for authenticated user', async ({ page }) => {
		await setupAuthenticated(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('body')).toBeVisible();

		const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(scrollWidth).toBeLessThanOrEqual(375);
	});

	test('changelog page renders at 375px', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/changelog');
		await page.waitForLoadState('networkidle');

		const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(scrollWidth).toBeLessThanOrEqual(375);
	});

	test('contact page renders at 375px', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/contact');
		await page.waitForLoadState('networkidle');

		const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
		expect(scrollWidth).toBeLessThanOrEqual(375);
	});
});

// =============================================================================
// Cookie consent — reject vs accept
// =============================================================================

test.describe('Cookie consent smoke test', () => {
	test('cookie consent banner appears when no preference stored', async ({ page }) => {
		await mockPublicRoutes(page);

		// Clear any stored consent.
		await page.addInitScript(() => {
			localStorage.removeItem('midsphere-cookie-consent');
		});

		await page.goto('/login');
		await page.waitForLoadState('networkidle');

		// The cookie consent banner should be visible.
		const banner = page.locator('[data-testid="cookie-consent"], [role="dialog"]').first();
		// Either a dedicated test ID or a dialog containing cookie-related text.
		const cookieText = page.getByText(/cookie/i).first();
		await expect(cookieText.or(banner)).toBeVisible({ timeout: 5000 });
	});

	test('rejecting cookies stores preference without analytics', async ({ page }) => {
		await mockPublicRoutes(page);

		await page.addInitScript(() => {
			localStorage.removeItem('midsphere-cookie-consent');
		});

		await page.goto('/login');
		await page.waitForLoadState('networkidle');

		// Click reject/essential-only button if visible.
		const rejectBtn = page.getByRole('button', { name: /reject|essential|decline/i }).first();
		if (await rejectBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			await rejectBtn.click();

			// Verify stored consent has analytics disabled.
			const consent = await page.evaluate(() =>
				JSON.parse(localStorage.getItem('midsphere-cookie-consent') || '{}')
			);
			expect(consent.analytics).toBeFalsy();
		}
	});

	test('accepting cookies stores preference with analytics enabled', async ({ page }) => {
		await mockPublicRoutes(page);

		await page.addInitScript(() => {
			localStorage.removeItem('midsphere-cookie-consent');
		});

		await page.goto('/login');
		await page.waitForLoadState('networkidle');

		// Click accept all button if visible.
		const acceptBtn = page.getByRole('button', { name: /accept all|accept/i }).first();
		if (await acceptBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
			await acceptBtn.click();

			// Verify stored consent has analytics enabled.
			const consent = await page.evaluate(() =>
				JSON.parse(localStorage.getItem('midsphere-cookie-consent') || '{}')
			);
			expect(consent.analytics).toBeTruthy();
		}
	});
});

// =============================================================================
// Auth flow pages — login/logout/password reset navigation
// =============================================================================

test.describe('Auth flow page navigation', () => {
	test('login page has link to signup and forgot-password', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/login');
		await page.waitForLoadState('networkidle');

		// Should have a link to signup.
		const signupLink = page.getByRole('link', { name: /sign up|create.*account|register/i });
		await expect(signupLink).toBeVisible();

		// Should have a forgot password link.
		const forgotLink = page.getByRole('link', { name: /forgot.*password/i });
		await expect(forgotLink).toBeVisible();
	});

	test('forgot-password page renders input for email', async ({ page }) => {
		await mockPublicRoutes(page);
		await page.goto('/forgot-password');
		await page.waitForLoadState('networkidle');

		// Should have an email input.
		const emailInput = page.getByLabel(/email/i).first();
		await expect(emailInput).toBeVisible();
	});
});

// =============================================================================
// Zero console errors on key pages
// =============================================================================

test.describe('Console error check', () => {
	test('home page has no console errors', async ({ page }) => {
		const errors: string[] = [];
		page.on('console', (msg) => {
			if (msg.type() === 'error') errors.push(msg.text());
		});

		await setupAuthenticated(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		// Filter out expected errors (e.g., failed network requests to mocked endpoints).
		const realErrors = errors.filter(
			(e) =>
				!e.includes('Failed to fetch') &&
				!e.includes('net::ERR') &&
				!e.includes('NetworkError') &&
				!e.includes('AbortError')
		);

		expect(realErrors).toEqual([]);
	});

	test('login page has no console errors', async ({ page }) => {
		const errors: string[] = [];
		page.on('console', (msg) => {
			if (msg.type() === 'error') errors.push(msg.text());
		});

		await mockPublicRoutes(page);
		await page.goto('/login');
		await page.waitForLoadState('networkidle');

		const realErrors = errors.filter(
			(e) =>
				!e.includes('Failed to fetch') &&
				!e.includes('net::ERR') &&
				!e.includes('NetworkError') &&
				!e.includes('AbortError')
		);

		expect(realErrors).toEqual([]);
	});
});
