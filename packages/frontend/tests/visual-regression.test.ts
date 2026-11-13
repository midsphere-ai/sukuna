import { expect, test, type Page } from '@playwright/test';

// --- Mock data ---

const MOCK_USER = {
	id: 'usr_test123',
	name: 'Test User',
	email: 'test@example.com',
	is_active: true,
	date_joined: '2026-01-01T00:00:00Z',
	last_login: '2026-02-24T00:00:00Z'
};

const MOCK_TOKEN = 'test-auth-token-abc123';

const MOCK_ADDONS = [
	{
		id: 'addon_slack',
		name: 'Slack',
		description: 'Connect your Slack workspace to send and receive messages.',
		link: 'https://slack.com',
		logo: '',
		enum: 'SLACK',
		tags: ['Communication', 'Messaging'],
		date_created: '2026-01-15T00:00:00Z'
	},
	{
		id: 'addon_github',
		name: 'GitHub',
		description: 'Access your repositories, issues, and pull requests.',
		link: 'https://github.com',
		logo: '',
		enum: 'GITHUB',
		tags: ['Developer Tools', 'VCS'],
		date_created: '2026-01-10T00:00:00Z'
	}
];

const MOCK_SETTINGS = {
	id: 'settings_1',
	theme: 'system',
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

const MOCK_SUBSCRIPTION = {
	id: 'sub_test123',
	plan: {
		id: 'plan_basic',
		name: 'Basic',
		tier: 'basic',
		price: 29,
		features: {
			weekly_tasks: 100,
			max_sandbox_time: 7200,
			max_addons: 10,
			max_addons_per_task: 3,
			max_mcp_per_task: 3,
			max_concurrent_tasks: 3,
			max_scheduled_tasks: 5,
			can_schedule_tasks: true,
			use_custom_llm: false,
			use_custom_mcp: true,
			use_custom_e2b: false
		},
		is_active: true
	},
	status: 'active',
	start_date: '2026-02-01T00:00:00Z',
	end_date: '2026-03-01T00:00:00Z',
	auto_renew: true,
	dodo_subscription_id: 'sub_dodo_123',
	usage_schema: {
		tasks_remaining_week: { limit: 100, used: 42, label: 'Weekly tasks' },
		sandbox_time_remaining_month: { limit: 7200, used: 2400, label: 'Sandbox time' },
		addons_used: { limit: 10, used: 3, label: 'Addons' },
		mcp_servers_added: { limit: 3, used: 1, label: 'MCP servers' },
		concurrent_tasks: { limit: 3, used: 0, label: 'Concurrent tasks' }
	}
};

const MOCK_PLANS = [
	{
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
	MOCK_SUBSCRIPTION.plan,
	{
		id: 'plan_premium',
		name: 'Premium',
		tier: 'premium',
		price: 99,
		features: {
			weekly_tasks: 500,
			max_sandbox_time: 36000,
			max_addons: 50,
			max_addons_per_task: 10,
			max_mcp_per_task: 10,
			max_concurrent_tasks: 10,
			max_scheduled_tasks: 50,
			can_schedule_tasks: true,
			use_custom_llm: true,
			use_custom_mcp: true,
			use_custom_e2b: true
		},
		is_active: true
	}
];

const MOCK_PAYMENTS = [
	{
		id: 'pay_001',
		dodo_payment_id: 'pay_dodo_001',
		amount: 29.0,
		currency: 'USD',
		status: 'captured',
		created_at: '2026-02-01T10:00:00Z'
	}
];

async function mockCommonRoutes(page: Page): Promise<void> {
	// Catch-all fallback for unmatched API requests (registered first = lowest priority in LIFO)
	// Only intercept fetch/xhr — let page navigations (document) through
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
			url.includes('/authentication/')
		) {
			return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
		}
		return route.continue();
	});

	await page.route('**/cms/public/**', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
	);
	await page.route('**/cms/home-banner', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
	);
	await page.route('**/cms/public/tutorials', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ items: [], count: 0 })
		})
	);
	await page.route('**/memory/addons**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ items: [], count: 0 })
		})
	);
	await page.route('**/memory/mcp-configs**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ items: [], count: 0 })
		})
	);
	await page.route('**/memory/conversations/stream/**', (route) =>
		route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
	);
	await page.route('**/memory/conversations?**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ items: [], count: 0 })
		})
	);
	await page.route('**/memory/conversations', (route) => {
		if (route.request().method() === 'GET') {
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [], count: 0 })
			});
		}
		return route.continue();
	});
	await page.route('**/memory/settings', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_SETTINGS)
		})
	);
}

async function setupAuthenticated(page: Page): Promise<void> {
	await mockCommonRoutes(page);

	await page.route('**/workspace/users/me/**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_USER)
		})
	);
	await page.route('**/workspace/users/me/', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify(MOCK_USER)
		})
	);

	await page.addInitScript((token) => {
		sessionStorage.setItem('midsphere-auth-token', token);
		localStorage.setItem(
			'midsphere-cookie-consent',
			JSON.stringify({ essential: true, analytics: false, errorTracking: false })
		);
	}, MOCK_TOKEN);
}

// =============================================================================
// Visual Regression Baselines — Public Pages
// =============================================================================

test.describe('Visual regression — Public pages', () => {
	test('login page', async ({ page }) => {
		await mockCommonRoutes(page);
		await page.goto('/login');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('login-page.png', { fullPage: true });
	});

	test('signup page', async ({ page }) => {
		await mockCommonRoutes(page);
		await page.goto('/signup');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('signup-page.png', { fullPage: true });
	});

	test('forgot password page', async ({ page }) => {
		await mockCommonRoutes(page);
		await page.goto('/forgot-password');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('forgot-password-page.png', { fullPage: true });
	});
});

// =============================================================================
// Visual Regression Baselines — App Pages (Authenticated)
// =============================================================================

test.describe('Visual regression — App pages', () => {
	test('home page (empty state)', async ({ page }) => {
		await setupAuthenticated(page);
		await page.goto('/');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('home-empty.png', { fullPage: true });
	});

	test('connectors page', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/memory/addons?**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: MOCK_ADDONS, count: MOCK_ADDONS.length })
			})
		);
		await page.route('**/memory/addons', (route) => {
			if (route.request().method() === 'GET') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ items: MOCK_ADDONS, count: MOCK_ADDONS.length })
				});
			}
			return route.continue();
		});
		await page.route('**/memory/user-addons**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [], count: 0 })
			})
		);

		await page.goto('/connectors');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('connectors-page.png', { fullPage: true });
	});

	test('library page', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/memory/files**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [], count: 0 })
			})
		);

		await page.goto('/library');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('library-page.png', { fullPage: true });
	});

	test('billing page', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/billing/subscription', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_SUBSCRIPTION)
			})
		);
		await page.route('**/billing/payments', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: MOCK_PAYMENTS, count: MOCK_PAYMENTS.length })
			})
		);

		await page.goto('/billing');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('billing-page.png', { fullPage: true });
	});

	test('billing plans page', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/billing/plans', (route) => {
			if (route.request().resourceType() === 'fetch' || route.request().resourceType() === 'xhr') {
				return route.fulfill({
					status: 200,
					contentType: 'application/json',
					body: JSON.stringify({ items: MOCK_PLANS, count: MOCK_PLANS.length })
				});
			}
			return route.continue();
		});
		await page.route('**/billing/subscription', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_SUBSCRIPTION)
			})
		);

		await page.goto('/billing/plans');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('billing-plans-page.png', { fullPage: true });
	});

	test('support page', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/memory/support-tickets**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [], count: 0 })
			})
		);

		await page.goto('/support');
		await page.waitForLoadState('networkidle');
		await expect(page).toHaveScreenshot('support-page.png', { fullPage: true });
	});
});
