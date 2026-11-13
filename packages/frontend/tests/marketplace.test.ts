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
	},
	{
		id: 'addon_notion',
		name: 'Notion',
		description: 'Search and manage your Notion pages and databases.',
		link: 'https://notion.so',
		logo: '',
		enum: 'NOTION',
		tags: ['Productivity', 'Documentation'],
		date_created: '2026-01-20T00:00:00Z'
	}
];

const MOCK_ADDON_DETAIL = {
	marketplace_addon: MOCK_ADDONS[0],
	user_addon: null as null | {
		id: string;
		enabled_addon: (typeof MOCK_ADDONS)[0];
		auth_complete: boolean;
		config_id: string | null;
		auth_link: string | null;
		auth_link_created_at: string | null;
	},
	features: [
		{ name: 'Send Message', description: 'Send messages to Slack channels' },
		{ name: 'Read Channels', description: 'List and read Slack channels' }
	]
};

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

/** Scoped to main content to avoid matching the desktop Header h1 */
function main(page: Page) {
	return page.getByRole('main');
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
// Marketplace browse
// =============================================================================

test.describe('Marketplace - Browse connectors', () => {
	test('loads and displays connector cards', async ({ page }) => {
		await setupAuthenticated(page);

		// Mock addons listing
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

		// Mock user addons (none installed)
		await page.route('**/memory/user-addons**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [], count: 0 })
			})
		);

		await page.goto('/connectors');
		await page.waitForLoadState('networkidle');

		// Verify page heading (scoped to main to avoid desktop Header h1)
		await expect(main(page).getByRole('heading', { name: 'Connectors' })).toBeVisible();
		await expect(page.getByText('Browse and install tools to extend your agent')).toBeVisible();

		// Verify addon cards are rendered (use heading role to avoid matching description text)
		await expect(main(page).getByRole('heading', { name: 'Slack' })).toBeVisible();
		await expect(main(page).getByRole('heading', { name: 'GitHub' })).toBeVisible();
		await expect(main(page).getByRole('heading', { name: 'Notion' })).toBeVisible();

		// Verify result count
		await expect(page.getByText('Showing 3 of 3 connectors')).toBeVisible();
	});

	test('filters connectors by category', async ({ page }) => {
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

		// Wait for categories to render
		await expect(page.getByRole('button', { name: 'Communication', exact: true })).toBeVisible();

		// Click Communication filter
		await page.getByRole('button', { name: 'Communication', exact: true }).click();

		// Slack should still be visible (it has Communication tag)
		await expect(main(page).getByRole('heading', { name: 'Slack' })).toBeVisible();

		// Notion should NOT be visible (it doesn't have Communication tag)
		await expect(main(page).getByRole('heading', { name: 'Notion' })).not.toBeVisible();

		// Result count should update
		await expect(page.getByText('Showing 1 of 3 connectors')).toBeVisible();
	});

	test('searches connectors', async ({ page }) => {
		await setupAuthenticated(page);

		// First load returns all addons
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

		// Search returns only GitHub
		await page.route('**/memory/addons/search**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [MOCK_ADDONS[1]], count: 1 })
			})
		);

		await page.goto('/connectors');
		await page.waitForLoadState('networkidle');

		// Type in search
		await page.getByPlaceholder('Search connectors...').fill('GitHub');

		// Wait for debounced search results
		await expect(page.getByText('Showing 1 of 1 connectors')).toBeVisible({
			timeout: 5000
		});
		await expect(page.getByRole('heading', { name: 'GitHub' })).toBeVisible();
	});
});

// =============================================================================
// Marketplace - Addon detail and install
// =============================================================================

test.describe('Marketplace - Install addon', () => {
	test('navigates to addon detail and installs it', async ({ page }) => {
		await setupAuthenticated(page);

		// Mock addons listing
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

		// Track install request count to return different data after install
		let installCalled = false;

		// Mock addon detail — first returns not installed, after install returns installed
		await page.route(`**/memory/addons/${MOCK_ADDONS[0].id}`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(
					installCalled
						? {
								...MOCK_ADDON_DETAIL,
								user_addon: {
									id: 'ua_test123',
									enabled_addon: MOCK_ADDONS[0],
									auth_complete: false,
									config_id: null,
									auth_link: null,
									auth_link_created_at: null
								}
							}
						: MOCK_ADDON_DETAIL
				)
			})
		);

		// Mock install endpoint
		await page.route('**/memory/addons/register', (route) => {
			installCalled = true;
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ user_addon_id: 'ua_test123', is_new: true })
			});
		});

		// Navigate to connectors page
		await page.goto('/connectors');
		await page.waitForLoadState('networkidle');

		// Click on Slack addon card
		await page.getByRole('heading', { name: 'Slack' }).click();
		await page.waitForURL('**/connectors/addon_slack');

		// Verify detail page (scoped to main to avoid desktop Header h1)
		await expect(main(page).getByRole('heading', { name: 'Slack' })).toBeVisible();
		await expect(page.getByText('About')).toBeVisible();
		await expect(page.getByText('Available Tools')).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Send Message' })).toBeVisible();
		await expect(page.getByRole('heading', { name: 'Read Channels' })).toBeVisible();

		// Install connector
		await expect(page.getByRole('button', { name: 'Install Connector' })).toBeVisible();
		await page.getByRole('button', { name: 'Install Connector' }).click();

		// After install, should show Authorise and Check Auth Status buttons
		await expect(page.getByRole('button', { name: 'Authorise' })).toBeVisible({
			timeout: 10000
		});
		await expect(page.getByRole('button', { name: 'Check Auth Status' })).toBeVisible();

		// Should show the "How to connect" guidance
		await expect(page.getByText('How to connect Slack')).toBeVisible();
	});

	test('checks auth status after authorization', async ({ page }) => {
		await setupAuthenticated(page);

		// Mock addons listing
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

		// Return installed but not authorized
		await page.route(`**/memory/addons/${MOCK_ADDONS[0].id}`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					...MOCK_ADDON_DETAIL,
					user_addon: {
						id: 'ua_test123',
						enabled_addon: MOCK_ADDONS[0],
						auth_complete: false,
						config_id: null,
						auth_link: null,
						auth_link_created_at: null
					}
				})
			})
		);

		// Mock check auth status — return authorized
		await page.route('**/memory/user-addons/ua_test123/refresh-auth', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ user_addon_id: 'ua_test123', is_authorised: true })
			})
		);

		await page.goto(`/connectors/${MOCK_ADDONS[0].id}`);
		await page.waitForLoadState('networkidle');

		// Should show "Installed" badge and auth buttons
		await expect(page.getByText('Installed')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Check Auth Status' })).toBeVisible();

		// Click check auth
		await page.getByRole('button', { name: 'Check Auth Status' }).click();

		// Should show connected state
		await expect(page.getByText('is connected and ready to use')).toBeVisible({
			timeout: 10000
		});
	});

	test('navigates back to connectors list', async ({ page }) => {
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
		await page.route(`**/memory/addons/${MOCK_ADDONS[0].id}`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_ADDON_DETAIL)
			})
		);

		await page.goto(`/connectors/${MOCK_ADDONS[0].id}`);
		await page.waitForLoadState('networkidle');

		// Click back
		await page.getByText('Back to Connectors').click();
		await page.waitForURL('**/connectors');
		expect(page.url()).toContain('/connectors');
	});
});
