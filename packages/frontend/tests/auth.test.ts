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

/**
 * Set up common API route mocks that many tests need:
 * - CMS endpoints (public banner, tutorials, home banner)
 * - User addons/MCP configs
 * - Conversations list
 */
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

	// CMS endpoints — silently return empty
	await page.route('**/cms/public/**', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
	);

	// Authenticated CMS banner
	await page.route('**/cms/home-banner', (route) =>
		route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
	);

	// Info tutorials
	await page.route('**/cms/public/tutorials', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ items: [], count: 0 })
		})
	);

	// Addons
	await page.route('**/memory/addons**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ items: [], count: 0 })
		})
	);

	// MCP configs
	await page.route('**/memory/mcp-configs**', (route) =>
		route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ items: [], count: 0 })
		})
	);

	// Conversations list
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

	// SSE conversation stream — return empty
	await page.route('**/memory/conversations/stream/**', (route) =>
		route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
	);
}

/**
 * Simulate an authenticated session by injecting a token into sessionStorage
 * and mocking the /workspace/users/me/ endpoint.
 */
export async function setupAuthenticated(page: Page): Promise<void> {
	await mockCommonRoutes(page);

	// Mock user profile endpoint
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

	// Set auth token in sessionStorage before navigating
	await page.addInitScript((token) => {
		sessionStorage.setItem('midsphere-auth-token', token);
	}, MOCK_TOKEN);
}

// =============================================================================
// Signup flow
// =============================================================================

test.describe('Signup flow', () => {
	test('signs up with email and password and navigates to onboarding', async ({ page }) => {
		await mockCommonRoutes(page);

		// Mock POST /workspace/users (signup)
		await page.route('**/workspace/users', (route) => {
			if (route.request().method() === 'POST') {
				const body = route.request().postDataJSON();
				expect(body.user_name).toBe('Jane Doe');
				expect(body.user_email).toBe('jane@example.com');
				expect(body.password).toBeTruthy();
				return route.fulfill({
					status: 201,
					contentType: 'application/json',
					body: JSON.stringify('Created')
				});
			}
			return route.continue();
		});

		// Mock POST /authentication/login/ (auto-login after signup)
		await page.route('**/authentication/login/', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ key: MOCK_TOKEN })
			})
		);

		// Mock GET /workspace/users/me/ (fetch profile after login)
		const newUser = { ...MOCK_USER, name: 'Jane Doe', email: 'jane@example.com', last_login: null };
		await page.route('**/workspace/users/me/**', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(newUser)
			})
		);
		await page.route('**/workspace/users/me/', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify(newUser)
			})
		);

		await page.goto('/signup');

		// Verify page heading
		await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible();

		// Fill form fields
		await page.getByLabel(/Full name/i).fill('Jane Doe');
		await page.getByLabel(/^Email/i).fill('jane@example.com');
		await page
			.getByLabel(/^Password/i)
			.first()
			.fill('StrongP@ss123');
		await page.getByLabel(/Confirm password/i).fill('StrongP@ss123');

		// Submit
		await page.getByRole('button', { name: 'Create Account' }).click();

		// Should navigate to onboarding
		await page.waitForURL('**/onboarding', { timeout: 10000 });
		expect(page.url()).toContain('/onboarding');
	});

	test('shows validation errors for empty form', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/signup');

		// Click submit without filling anything
		await page.getByRole('button', { name: 'Create Account' }).click();

		// Should show validation errors (these are rendered by the Input component)
		await expect(page.getByText('Full name is required')).toBeVisible();
		await expect(page.getByText('Email is required')).toBeVisible();
		await expect(page.getByText('Password is required')).toBeVisible();
	});

	test('shows validation error for mismatched passwords', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/signup');

		await page.getByLabel(/Full name/i).fill('Jane Doe');
		await page.getByLabel(/^Email/i).fill('jane@example.com');
		await page
			.getByLabel(/^Password/i)
			.first()
			.fill('StrongP@ss123');
		await page.getByLabel(/Confirm password/i).fill('DifferentPass');

		await page.getByRole('button', { name: 'Create Account' }).click();

		await expect(page.getByText('Passwords do not match')).toBeVisible();
	});

	test('navigates to login page from signup', async ({ page }) => {
		await mockCommonRoutes(page);
		// Dismiss cookie consent banner that covers bottom links
		await page.addInitScript(() => {
			localStorage.setItem(
				'midsphere-cookie-consent',
				JSON.stringify({ essential: true, analytics: false, errorTracking: false })
			);
		});

		await page.goto('/signup');
		await page.waitForLoadState('networkidle');

		// Scope to the form-level "Already have an account? Log in" text
		await page.getByText('Already have an account?').getByRole('link', { name: 'Log in' }).click();
		await page.waitForURL('**/login');
		expect(page.url()).toContain('/login');
	});
});

// =============================================================================
// Login flow
// =============================================================================

test.describe('Login flow', () => {
	test('logs in with email and password and navigates to home', async ({ page }) => {
		await mockCommonRoutes(page);

		// Mock login
		await page.route('**/authentication/login/', (route) =>
			route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({ key: MOCK_TOKEN })
			})
		);

		// Mock user profile (returning user with name and last_login → goes to home)
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

		await page.goto('/login');

		// Verify page heading
		await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();

		// Fill form
		await page.getByLabel(/^Email/i).fill('test@example.com');
		await page.getByLabel(/^Password/i).fill('TestPass123');

		// Submit
		await page.getByRole('button', { name: 'Sign In' }).click();

		// Should navigate to home (since user has name and last_login)
		await page.waitForURL('**/', { timeout: 10000 });
	});

	test('shows error for invalid credentials', async ({ page }) => {
		await mockCommonRoutes(page);

		// Mock login failure
		await page.route('**/authentication/login/', (route) =>
			route.fulfill({
				status: 401,
				contentType: 'application/json',
				body: JSON.stringify({ detail: 'Invalid credentials' })
			})
		);

		await page.goto('/login');

		await page.getByLabel(/^Email/i).fill('wrong@example.com');
		await page.getByLabel(/^Password/i).fill('wrongpass');
		await page.getByRole('button', { name: 'Sign In' }).click();

		// Should show error
		await expect(page.getByText('Invalid email or password')).toBeVisible();
	});

	test('shows validation errors for empty form', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/login');
		await page.getByRole('button', { name: 'Sign In' }).click();

		await expect(page.getByText('Email is required')).toBeVisible();
		await expect(page.getByText('Password is required')).toBeVisible();
	});

	test('navigates to signup page from login', async ({ page }) => {
		await mockCommonRoutes(page);
		// Dismiss cookie consent banner that covers bottom links
		await page.addInitScript(() => {
			localStorage.setItem(
				'midsphere-cookie-consent',
				JSON.stringify({ essential: true, analytics: false, errorTracking: false })
			);
		});

		await page.goto('/login');
		await page.waitForLoadState('networkidle');
		// Use the form-level "Sign up" link (not the PublicNav "Sign Up" button)
		await page.locator('p').filter({ hasText: "Don't have an account?" }).getByRole('link').click();
		await page.waitForURL('**/signup');
		expect(page.url()).toContain('/signup');
	});

	test('navigates to forgot password page', async ({ page }) => {
		await mockCommonRoutes(page);

		await page.goto('/login');
		await page.getByRole('link', { name: 'Forgot password?' }).click();
		await page.waitForURL('**/forgot-password');
		expect(page.url()).toContain('/forgot-password');
	});
});
