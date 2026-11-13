/**
 * E2E integration test: Home → type message → start conversation.
 * Tests the full end-to-end flow in a real browser with mocked API responses.
 * Note: Other page-level integration tests are in src/tests/integration-flows.test.ts
 * (Vitest-based) due to Vite preview server proxy interference with Playwright route mocking.
 */
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
const MOCK_CONVERSATION_ID = 'conv_int_001';
const MOCK_RUN_ID = 'run_int_001';
const MOCK_SANDBOX_HOST = 'https://sandbox-int.e2b.dev';

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

function json(data: unknown) {
	return {
		status: 200 as const,
		contentType: 'application/json' as const,
		body: JSON.stringify(data)
	};
}

async function mockCatchAll(page: Page): Promise<void> {
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
			return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
		}
		return route.continue();
	});
}

async function mockCommonRoutes(page: Page): Promise<void> {
	await page.route('**/cms/public/**', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
	);
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
	await page.route('**/memory/settings', (route) => route.fulfill(json(MOCK_SETTINGS)));
}

async function setupAuthenticated(page: Page): Promise<void> {
	await mockCatchAll(page);
	await mockCommonRoutes(page);
	await page.route('**/workspace/users/me/**', (route) => route.fulfill(json(MOCK_USER)));
	await page.route('**/workspace/users/me/', (route) => route.fulfill(json(MOCK_USER)));

	await page.addInitScript((token) => {
		sessionStorage.setItem('midsphere-auth-token', token);
		localStorage.setItem(
			'midsphere-cookie-consent',
			JSON.stringify({ essential: true, analytics: false, errorTracking: false })
		);
	}, MOCK_TOKEN);
}

test.describe('Integration: Home → message → conversation → streaming', () => {
	test('types prompt on home page, starts conversation, navigates to chat', async ({ page }) => {
		await setupAuthenticated(page);

		await page.route('**/chat/completions/start', (route) =>
			route.fulfill(
				json({
					conversation_id: MOCK_CONVERSATION_ID,
					run_id: MOCK_RUN_ID,
					sandbox_host: MOCK_SANDBOX_HOST
				})
			)
		);

		await page.route(`**/chat/completions/${MOCK_CONVERSATION_ID}/status`, (route) =>
			route.fulfill(
				json({
					conversation_id: MOCK_CONVERSATION_ID,
					run_id: MOCK_RUN_ID,
					sandbox_host: MOCK_SANDBOX_HOST,
					status: 'running'
				})
			)
		);

		await page.route(`**/memory/conversations/${MOCK_CONVERSATION_ID}`, (route) =>
			route.fulfill(
				json({
					id: MOCK_CONVERSATION_ID,
					title: 'Hello World Program',
					summary: '',
					on_going: true,
					has_error: false,
					metadata: {},
					date_created: '2026-02-24T00:00:00Z',
					date_updated: '2026-02-24T00:00:00Z',
					status: 'running'
				})
			)
		);

		await page.route(`${MOCK_SANDBOX_HOST}/**`, (route) => {
			const url = route.request().url();
			if (url.includes('/stream')) {
				return route.fulfill({
					status: 200,
					contentType: 'text/event-stream',
					body: [
						'event: text',
						'data: {"text":"Here is your hello world program!"}',
						'',
						'event: run_completed',
						'data: {"status":"completed"}',
						''
					].join('\n')
				});
			}
			return route.fulfill(
				json({
					events: [
						{ type: 'text', data: { text: 'Here is your hello world program!' }, sequence: 1 }
					]
				})
			);
		});

		await page.goto('/');
		await page.waitForLoadState('networkidle');

		const textarea = page.locator('textarea').first();
		await expect(textarea).toBeVisible({ timeout: 10000 });

		await textarea.fill('Write a hello world program');
		await textarea.press('Enter');

		await page.waitForURL(`**/chat/${MOCK_CONVERSATION_ID}`, { timeout: 15000 });
		expect(page.url()).toContain(`/chat/${MOCK_CONVERSATION_ID}`);
	});
});
