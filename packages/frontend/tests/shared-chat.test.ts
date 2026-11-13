import { expect, test, type Page } from '@playwright/test';

const MOCK_CONVERSATION_ID = 'conv_shared123';
const MOCK_RUN_ID = 'run_shared456';
const MOCK_SANDBOX_HOST = 'https://sandbox-shared.e2b.dev';

async function mockPublicRoutes(page: Page): Promise<void> {
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

	// CMS endpoints
	await page.route('**/cms/public/**', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
	);
}

test.describe('Shared chat page', () => {
	test('renders shared conversation without authentication', async ({ page }) => {
		await mockPublicRoutes(page);

		// Mock shared conversation info
		await page.route(`**/memory/conversations/${MOCK_CONVERSATION_ID}/shared`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					id: MOCK_CONVERSATION_ID,
					title: 'Shared AI Conversation',
					date_created: '2026-02-20T10:00:00Z',
					date_updated: '2026-02-20T11:00:00Z'
				})
			})
		);

		// Mock shared conversation status
		await page.route(`**/chat/completions/${MOCK_CONVERSATION_ID}/status`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					conversation_id: MOCK_CONVERSATION_ID,
					run_id: MOCK_RUN_ID,
					sandbox_host: MOCK_SANDBOX_HOST,
					status: 'completed'
				})
			})
		);

		// Mock run events with conversation history
		await page.route(`${MOCK_SANDBOX_HOST}/runs/${MOCK_RUN_ID}`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					events: [
						{
							type: 'user_message',
							data: { content: 'What is the meaning of life?' },
							sequence: 1
						},
						{
							type: 'text_delta',
							data: { text: 'The meaning of life is a profound philosophical question.' },
							sequence: 2
						},
						{
							type: 'status',
							data: { status: 'completed' },
							sequence: 3
						}
					]
				})
			})
		);

		// Navigate to shared page — no auth token set
		await page.goto(`/shared/${MOCK_CONVERSATION_ID}`);
		await page.waitForLoadState('networkidle');

		// Should show the shared banner
		await expect(page.getByText('This is a shared conversation.')).toBeVisible({ timeout: 10000 });

		// Should show conversation title
		await expect(page.getByRole('heading', { name: 'Shared AI Conversation' })).toBeVisible({
			timeout: 10000
		});

		// Should show the date
		await expect(page.getByText('February 20, 2026')).toBeVisible();

		// Should show task completed status
		await expect(page.getByText('Task completed')).toBeVisible({ timeout: 10000 });

		// Should have sign up links
		await expect(page.getByText('Sign up').first()).toBeVisible();
	});

	test('shows error for unavailable shared conversation', async ({ page }) => {
		await mockPublicRoutes(page);

		const badId = 'conv_nonexistent';

		// Mock shared conversation info — fail
		await page.route(`**/memory/conversations/${badId}/shared`, (route) =>
			route.fulfill({
				status: 404,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Not found' })
			})
		);

		// Mock status — fail
		await page.route(`**/chat/completions/${badId}/status`, (route) =>
			route.fulfill({
				status: 404,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Not found' })
			})
		);

		await page.goto(`/shared/${badId}`);
		await page.waitForLoadState('networkidle');

		// Should show error message
		await expect(
			page.getByText('This conversation is not available or has not been shared.')
		).toBeVisible({ timeout: 10000 });

		// Should show sign up button
		await expect(page.getByText('Sign up for Midsphere')).toBeVisible();
	});

	test('shows running status for live shared conversation', async ({ page }) => {
		await mockPublicRoutes(page);

		// Mock shared conversation info
		await page.route(`**/memory/conversations/${MOCK_CONVERSATION_ID}/shared`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					id: MOCK_CONVERSATION_ID,
					title: 'Live Shared Conversation',
					date_created: '2026-02-24T10:00:00Z',
					date_updated: '2026-02-24T10:00:00Z'
				})
			})
		);

		// Mock status — running
		await page.route(`**/chat/completions/${MOCK_CONVERSATION_ID}/status`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({
					conversation_id: MOCK_CONVERSATION_ID,
					run_id: MOCK_RUN_ID,
					sandbox_host: MOCK_SANDBOX_HOST,
					status: 'running'
				})
			})
		);

		// Mock SSE stream for live connection
		await page.route(`${MOCK_SANDBOX_HOST}/runs/${MOCK_RUN_ID}/stream`, (route) =>
			route.fulfill({
				status: 200,
				contentType: 'text/event-stream',
				body: [
					'event: text_delta',
					'data: {"text":"I am working on your request..."}',
					'',
					''
				].join('\n')
			})
		);

		await page.goto(`/shared/${MOCK_CONVERSATION_ID}`);
		await page.waitForLoadState('networkidle');

		// Should show shared banner
		await expect(page.getByText('This is a shared conversation.')).toBeVisible({ timeout: 10000 });

		// Should show conversation title
		await expect(page.getByRole('heading', { name: 'Live Shared Conversation' })).toBeVisible({
			timeout: 10000
		});
	});

	test('signup link navigates to signup page', async ({ page }) => {
		await mockPublicRoutes(page);

		// Mock with error so the signup button is shown
		await page.route(`**/memory/conversations/conv_test/shared`, (route) =>
			route.fulfill({
				status: 404,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Not found' })
			})
		);
		await page.route(`**/chat/completions/conv_test/status`, (route) =>
			route.fulfill({
				status: 404,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Not found' })
			})
		);

		await page.goto('/shared/conv_test');
		await page.waitForLoadState('networkidle');

		// Wait for error state
		await expect(page.getByText('Sign up for Midsphere')).toBeVisible({ timeout: 10000 });

		// Click signup link
		await page.getByText('Sign up for Midsphere').click();
		await page.waitForURL('**/signup', { timeout: 5000 });
		expect(page.url()).toContain('/signup');
	});
});
