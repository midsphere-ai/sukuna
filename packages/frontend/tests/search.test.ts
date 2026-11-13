import { expect, test, type Page } from '@playwright/test';

const MOCK_USER = {
	id: 'usr_test123',
	name: 'Test User',
	email: 'test@example.com',
	is_active: true,
	date_joined: '2026-01-01T00:00:00Z',
	last_login: '2026-02-24T00:00:00Z'
};

const MOCK_TOKEN = 'test-auth-token-abc123';

const MOCK_SEARCH_RESULTS = {
	items: [
		{
			id: 'conv_search001',
			title: 'Build a REST API',
			summary: 'Building REST APIs with Django',
			on_going: false,
			has_error: false,
			metadata: {},
			date_created: '2026-02-20T10:00:00Z',
			date_updated: '2026-02-20T11:00:00Z',
			status: 'completed'
		},
		{
			id: 'conv_search002',
			title: 'REST endpoint testing',
			summary: 'Testing REST endpoints',
			on_going: false,
			has_error: false,
			metadata: {},
			date_created: '2026-02-19T09:00:00Z',
			date_updated: '2026-02-19T10:00:00Z',
			status: 'completed'
		}
	],
	count: 2
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
		localStorage.setItem(
			'midsphere-cookie-consent',
			JSON.stringify({ essential: true, analytics: false, errorTracking: false })
		);
	}, MOCK_TOKEN);
}

test.describe('Search dialog', () => {
	test('opens with Ctrl+K, shows results, and navigates on click', async ({ page }) => {
		await setupAuthenticated(page);

		// Mock search endpoint
		await page.route('**/memory/conversations/search**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_SEARCH_RESULTS)
			})
		);

		// Mock the chat page for navigation target
		await page.route(`**/chat/completions/conv_search001/status`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					conversation_id: 'conv_search001',
					run_id: null,
					sandbox_host: null,
					status: 'completed'
				})
			})
		);
		await page.route(`**/memory/conversations/conv_search001`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_SEARCH_RESULTS.items[0])
			})
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		// Wait for app to be ready and blur any auto-focused input (textarea blocks shortcuts)
		await page.waitForTimeout(1000);
		await page.evaluate(() => (document.activeElement as HTMLElement)?.blur?.());

		// Open search with Ctrl+K
		await page.keyboard.press('Control+k');

		// Search dialog should be visible
		const searchInput = page.getByPlaceholder('Search conversations...');
		await expect(searchInput).toBeVisible({ timeout: 5000 });

		// Type search query
		await searchInput.fill('REST');

		// Wait for debounced search to complete
		await page.waitForTimeout(500);

		// Results should appear
		await expect(page.getByText('Build a REST API')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('REST endpoint testing')).toBeVisible();

		// Click the first result
		await page.getByText('Build a REST API').click();

		// Should navigate to the conversation
		await page.waitForURL('**/chat/conv_search001', { timeout: 10000 });
		expect(page.url()).toContain('/chat/conv_search001');
	});

	test('closes with Escape key', async ({ page }) => {
		await setupAuthenticated(page);

		await page.goto('/');
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(1000);
		await page.evaluate(() => (document.activeElement as HTMLElement)?.blur?.());

		// Open search
		await page.keyboard.press('Control+k');

		const searchInput = page.getByPlaceholder('Search conversations...');
		await expect(searchInput).toBeVisible({ timeout: 5000 });

		// Close with Escape
		await page.keyboard.press('Escape');

		// Dialog should be closed
		await expect(searchInput).not.toBeVisible({ timeout: 3000 });
	});

	test('shows no results message for empty search', async ({ page }) => {
		await setupAuthenticated(page);

		// Mock empty search results
		await page.route('**/memory/conversations/search**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ items: [], count: 0 })
			})
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(1000);
		await page.evaluate(() => (document.activeElement as HTMLElement)?.blur?.());

		await page.keyboard.press('Control+k');

		const searchInput = page.getByPlaceholder('Search conversations...');
		await expect(searchInput).toBeVisible({ timeout: 5000 });

		await searchInput.fill('nonexistent query xyz');

		// Wait for debounced search
		await page.waitForTimeout(500);

		// Should show no results message
		await expect(page.getByText(/No results for/)).toBeVisible({ timeout: 5000 });
	});

	test('navigates results with arrow keys and Enter', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/memory/conversations/search**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_SEARCH_RESULTS)
			})
		);

		await page.route(`**/chat/completions/conv_search002/status`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					conversation_id: 'conv_search002',
					run_id: null,
					sandbox_host: null,
					status: 'completed'
				})
			})
		);
		await page.route(`**/memory/conversations/conv_search002`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(MOCK_SEARCH_RESULTS.items[1])
			})
		);

		await page.goto('/');
		await page.waitForLoadState('networkidle');
		await page.waitForTimeout(1000);
		await page.evaluate(() => (document.activeElement as HTMLElement)?.blur?.());

		await page.keyboard.press('Control+k');

		const searchInput = page.getByPlaceholder('Search conversations...');
		await expect(searchInput).toBeVisible({ timeout: 5000 });

		await searchInput.fill('REST');
		await page.waitForTimeout(500);

		await expect(page.getByText('Build a REST API')).toBeVisible({ timeout: 5000 });

		// Navigate down twice to select second result
		await page.keyboard.press('ArrowDown');
		await page.keyboard.press('ArrowDown');

		// Press Enter to navigate
		await page.keyboard.press('Enter');

		await page.waitForURL('**/chat/conv_search002', { timeout: 10000 });
		expect(page.url()).toContain('/chat/conv_search002');
	});
});
