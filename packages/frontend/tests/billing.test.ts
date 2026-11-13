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
	{
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

const MOCK_SUBSCRIPTION = {
	id: 'sub_test123',
	plan: MOCK_PLANS[1], // Basic plan
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

const MOCK_PAYMENTS = [
	{
		id: 'pay_001',
		dodo_payment_id: 'pay_dodo_001',
		amount: 29.0,
		currency: 'USD',
		status: 'captured',
		created_at: '2026-02-01T10:00:00Z'
	},
	{
		id: 'pay_002',
		dodo_payment_id: 'pay_dodo_002',
		amount: 29.0,
		currency: 'USD',
		status: 'captured',
		created_at: '2026-01-01T10:00:00Z'
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
			body: JSON.stringify({
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
			})
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
		// Dismiss cookie consent banner
		localStorage.setItem(
			'midsphere-cookie-consent',
			JSON.stringify({ essential: true, analytics: false, errorTracking: false })
		);
	}, MOCK_TOKEN);
}

// =============================================================================
// Billing overview
// =============================================================================

test.describe('Billing - Overview', () => {
	test('loads billing page with subscription and usage', async ({ page }) => {
		await setupAuthenticated(page);

		// Mock subscription
		await page.route('**/billing/subscription', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_SUBSCRIPTION)
			})
		);

		// Mock payments
		await page.route('**/billing/payments', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: MOCK_PAYMENTS, count: MOCK_PAYMENTS.length })
			})
		);

		await page.goto('/billing');
		await page.waitForLoadState('networkidle');

		// Verify page heading (scoped to main to avoid desktop Header h1)
		await expect(
			page.getByRole('main').getByRole('heading', { name: 'Billing & Usage' })
		).toBeVisible();
		await expect(page.getByText('Manage your subscription, view usage metrics')).toBeVisible();

		// Verify plan card
		await expect(page.getByText('Basic').first()).toBeVisible();
		await expect(page.getByText('active').first()).toBeVisible();
		await expect(page.getByText('$29')).toBeVisible();
		await expect(page.getByText('/month')).toBeVisible();

		// Verify action buttons
		await expect(page.getByText('Change plan')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();

		// Verify usage section
		await expect(page.getByRole('heading', { name: 'Usage', exact: true })).toBeVisible();
		// Scope to usage section (avoid matching plan features "weekly tasks" lowercase)
		const usageSection = page.getByRole('heading', { name: 'Usage', exact: true }).locator('..');
		await expect(usageSection.getByText('Weekly tasks')).toBeVisible();
		await expect(usageSection.getByText('42 / 100 used')).toBeVisible();
		await expect(usageSection.getByText('Sandbox time')).toBeVisible();
		await expect(usageSection.getByText('Addons installed')).toBeVisible();

		// Verify plan features section
		await expect(page.getByText('Plan features')).toBeVisible();

		// Verify transactions
		await expect(page.getByText('Transactions')).toBeVisible();
		await expect(page.getByText('USD 29.00').first()).toBeVisible();
		await expect(page.getByText('Paid').first()).toBeVisible();

		// Verify subscription history
		await expect(page.getByText('Subscription history')).toBeVisible();
	});

	test('shows empty transactions state', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/billing/subscription', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					...MOCK_SUBSCRIPTION,
					plan: MOCK_PLANS[0], // Free plan
					usage_schema: null
				})
			})
		);

		// No payments
		await page.route('**/billing/payments', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [], count: 0 })
			})
		);

		await page.goto('/billing');
		await page.waitForLoadState('networkidle');

		// Verify free plan
		await expect(page.getByText('Free plan')).toBeVisible();

		// Verify no cancel button for free plans
		await expect(page.getByRole('button', { name: 'Cancel' })).not.toBeVisible();

		// Verify empty transactions
		await expect(page.getByText('No transactions yet')).toBeVisible();
	});

	test('shows help link to support', async ({ page }) => {
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

		// Verify support link
		await expect(page.getByText('Having billing issues?')).toBeVisible();
		await expect(page.getByText('Contact Support')).toBeVisible();
	});
});

// =============================================================================
// Plans comparison
// =============================================================================

test.describe('Billing - Plans comparison', () => {
	test('loads plans page with all plan cards', async ({ page }) => {
		await setupAuthenticated(page);

		// Only intercept API (fetch) calls — let page navigations through
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

		// Verify heading (scoped to main to avoid desktop Header h1)
		await expect(
			page.getByRole('main').getByRole('heading', { name: 'Choose a plan' })
		).toBeVisible();
		await expect(
			page.getByText('Compare features and pick the plan that fits your workflow')
		).toBeVisible();

		// Verify all plan names
		await expect(page.getByText('Free').first()).toBeVisible();
		await expect(page.getByText('Basic').first()).toBeVisible();
		await expect(page.getByText('Premium').first()).toBeVisible();

		// Verify pricing
		await expect(page.getByText('forever')).toBeVisible();
		await expect(page.getByText('$29')).toBeVisible();
		await expect(page.getByText('$99')).toBeVisible();

		// Verify "Current" badge on the Basic plan
		await expect(page.getByText('Current').first()).toBeVisible();

		// Verify "Popular" badge on Premium plan
		await expect(page.getByText('Popular').first()).toBeVisible();

		// Verify action buttons
		await expect(page.getByRole('button', { name: 'Downgrade' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Current plan' })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Upgrade' })).toBeVisible();

		// Verify promo code section
		await expect(page.getByText('Have a promo code?')).toBeVisible();
		await expect(page.getByPlaceholder('Enter promo code')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Apply' })).toBeVisible();

		// Verify back link
		await expect(page.getByText('Back to Billing')).toBeVisible();
	});

	test('applies promo code successfully', async ({ page }) => {
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

		// Mock promo validation
		await page.route('**/billing/promo/validate', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					valid: true,
					discount_percent: 20,
					message: 'Code "SAVE20" applied. 20% discount.'
				})
			})
		);

		await page.goto('/billing/plans');
		await page.waitForLoadState('networkidle');

		// Enter promo code
		await page.getByPlaceholder('Enter promo code').fill('SAVE20');
		await page.getByRole('button', { name: 'Apply' }).click();

		// Verify success message (scoped to main to avoid toast duplicate)
		await expect(page.getByRole('main').getByText('20% discount')).toBeVisible({
			timeout: 5000
		});

		// Verify Clear button appears
		await expect(page.getByRole('button', { name: 'Clear' })).toBeVisible();
	});

	test('shows promo code error for invalid code', async ({ page }) => {
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

		await page.route('**/billing/promo/validate', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					valid: false,
					discount_percent: 0,
					message: 'Invalid promo code.'
				})
			})
		);

		await page.goto('/billing/plans');
		await page.waitForLoadState('networkidle');

		await page.getByPlaceholder('Enter promo code').fill('BADCODE');
		await page.getByRole('button', { name: 'Apply' }).click();

		// Should show error
		await expect(page.getByText('Invalid promo code.')).toBeVisible({ timeout: 5000 });
	});

	test('navigates back to billing overview', async ({ page }) => {
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
		await page.route('**/billing/payments', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: MOCK_PAYMENTS, count: MOCK_PAYMENTS.length })
			})
		);

		await page.goto('/billing/plans');
		await page.waitForLoadState('networkidle');

		// Click back link
		await page.getByText('Back to Billing').click();
		await page.waitForURL('**/billing', { timeout: 10000 });
		expect(page.url()).toContain('/billing');
	});
});
