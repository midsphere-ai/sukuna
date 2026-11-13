import { expect, test, type Page } from '@playwright/test';

/**
 * Set up common API route mocks for public pages.
 */
async function mockCommonRoutes(page: Page): Promise<void> {
	// Catch-all fallback for unmatched API requests
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
	await page.route('**/cms/home-banner', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
	);
}

// =============================================================================
// Login page OAuth provider buttons (US-016)
// =============================================================================

test.describe('Login page OAuth provider buttons', () => {
	test('renders all 4 provider buttons: Google, GitHub, Microsoft, Apple', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/login');
		await page.waitForLoadState('domcontentloaded');

		// Verify all 4 OAuth provider buttons are visible
		await expect(page.getByText('Continue with Google')).toBeVisible();
		await expect(page.getByText('Continue with GitHub')).toBeVisible();
		await expect(page.getByText('Continue with Microsoft')).toBeVisible();
		await expect(page.getByText('Continue with Apple')).toBeVisible();
	});

	test('GitHub button links to allauth provider URL', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/login');
		await page.waitForLoadState('domcontentloaded');

		const githubLink = page.getByText('Continue with GitHub').locator('..');
		// GitHub uses an <a> tag linking to the allauth redirect URL
		const href = await githubLink.getAttribute('href');
		expect(href).toContain('/accounts/github/login/');
	});

	test('Microsoft button links to allauth provider URL', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/login');
		await page.waitForLoadState('domcontentloaded');

		const msLink = page.getByText('Continue with Microsoft').locator('..');
		const href = await msLink.getAttribute('href');
		expect(href).toContain('/accounts/microsoft/login/');
	});

	test('Apple button links to allauth provider URL', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/login');
		await page.waitForLoadState('domcontentloaded');

		const appleLink = page.getByText('Continue with Apple').locator('..');
		const href = await appleLink.getAttribute('href');
		expect(href).toContain('/accounts/apple/login/');
	});

	test('Google button is a clickable button element', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/login');
		await page.waitForLoadState('domcontentloaded');

		// Google uses a button (not <a>), since it uses the JS SDK
		const googleButton = page.getByText('Continue with Google').locator('..');
		await expect(googleButton).toBeEnabled();
	});

	test('provider buttons are also present on signup page', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/signup');
		await page.waitForLoadState('domcontentloaded');

		await expect(page.getByText('Continue with Google')).toBeVisible();
		await expect(page.getByText('Continue with GitHub')).toBeVisible();
		await expect(page.getByText('Continue with Microsoft')).toBeVisible();
		await expect(page.getByText('Continue with Apple')).toBeVisible();
	});
});
