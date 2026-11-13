import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get, writable, derived } from 'svelte/store';

const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args: unknown[]) => mockGoto(...args)
}));

vi.mock('$app/environment', () => ({
	browser: true
}));

const localStorageMock = (() => {
	let store: Record<string, string> = {};
	return {
		getItem: vi.fn((key: string) => store[key] ?? null),
		setItem: vi.fn((key: string, value: string) => {
			store[key] = value;
		}),
		removeItem: vi.fn((key: string) => {
			delete store[key];
		}),
		clear: vi.fn(() => {
			store = {};
		}),
		get length() {
			return Object.keys(store).length;
		},
		key: vi.fn((index: number) => Object.keys(store)[index] ?? null)
	};
})();

vi.stubGlobal('localStorage', localStorageMock);
vi.stubGlobal('sessionStorage', localStorageMock);

const mockUpdateUser = vi.fn();
const mockFetchCurrentUser = vi.fn();
vi.mock('$api/auth', () => ({
	updateUser: (...args: unknown[]) => mockUpdateUser(...args),
	login: vi.fn(),
	signup: vi.fn(),
	loginWithGoogle: vi.fn(),
	logout: vi.fn(),
	fetchCurrentUser: (...args: unknown[]) => mockFetchCurrentUser(...args),
	initAuth: vi.fn()
}));

const mockSaveSettingsImmediately = vi.fn(() => Promise.resolve());
vi.mock('$stores/settings', () => ({
	saveSettings: vi.fn(() => Promise.resolve()),
	saveSettingsImmediately: (...args: unknown[]) => mockSaveSettingsImmediately(...args),
	openSettings: vi.fn()
}));

vi.mock('$api/organizations', () => ({
	listOrganizations: vi.fn(() => Promise.resolve([])),
	createOrganization: vi.fn(() => Promise.resolve({ id: 'org-1', name: 'Team', slug: 'team' })),
	createInvitation: vi.fn(() => Promise.resolve({}))
}));

const mockGetUserConsent = vi.fn(() => Promise.resolve({}));
const mockUpdateUserConsent = vi.fn(() => Promise.resolve({}));
vi.mock('$api/compliance', () => ({
	getUserConsent: (...args: unknown[]) => mockGetUserConsent(...args),
	updateUserConsent: (...args: unknown[]) => mockUpdateUserConsent(...args)
}));

const mockGetUserSubscription = vi.fn(() => Promise.reject(new Error('no subscription')));
vi.mock('$api/billing', () => ({
	getUserSubscription: (...args: unknown[]) => mockGetUserSubscription(...args)
}));

const mockToasts = {
	success: vi.fn(),
	error: vi.fn(),
	warning: vi.fn(),
	info: vi.fn()
};
vi.mock('$stores/toast', () => ({
	toasts: mockToasts
}));

const mockAuthToken = writable<string | null>(null);
const mockCurrentUserStore = writable({
	id: 'user-123',
	name: 'Test User',
	email: 'test@example.com',
	avatar: '',
	is_active: true,
	date_joined: '2026-01-01',
	last_login: null,
	enterprise_mode: false
});
const mockAuthLoading = writable(false);

vi.mock('$stores/auth', () => ({
	authToken: mockAuthToken,
	currentUser: mockCurrentUserStore,
	authLoading: mockAuthLoading,
	isAuthenticated: derived(mockAuthToken, ($t: string | null) => $t !== null),
	setAuth: vi.fn(),
	clearAuth: vi.fn()
}));

describe('Onboarding Store', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		localStorageMock.clear();
	});

	it('starts with onboarding incomplete by default', async () => {
		const { onboardingComplete } = await import('$stores/onboarding');
		expect(get(onboardingComplete)).toBe(false);
	});

	it('markOnboardingComplete sets store to true and persists', async () => {
		const { markOnboardingComplete, onboardingComplete } = await import('$stores/onboarding');
		markOnboardingComplete();
		expect(get(onboardingComplete)).toBe(true);
		expect(localStorageMock.setItem).toHaveBeenCalledWith('midsphere-onboarding-complete', 'true');
	});

	it('resetOnboarding sets store to false and removes from storage', async () => {
		const { markOnboardingComplete, resetOnboarding, onboardingComplete } =
			await import('$stores/onboarding');
		markOnboardingComplete();
		resetOnboarding();
		expect(get(onboardingComplete)).toBe(false);
		expect(localStorageMock.removeItem).toHaveBeenCalledWith('midsphere-onboarding-complete');
	});
});

describe('Onboarding Page — Guided Flow', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		localStorageMock.clear();
		mockUpdateUser.mockResolvedValue(undefined);
		mockFetchCurrentUser.mockResolvedValue(undefined);
		mockAuthToken.set(null);
		mockCurrentUserStore.set({
			id: 'user-123',
			name: 'Test User',
			email: 'test@example.com',
			avatar: '',
			is_active: true,
			date_joined: '2026-01-01',
			last_login: null,
			enterprise_mode: false
		});
	});

	async function renderPage() {
		const OnboardingPage = (await import('../routes/onboarding/+page.svelte')).default;
		return render(OnboardingPage);
	}

	it('renders first step with name prompt', async () => {
		await renderPage();
		expect(screen.getByText(/what should i call you/i)).toBeTruthy();
		expect(screen.getByPlaceholderText('Enter your name')).toBeTruthy();
	});

	it('continue is disabled when name is too short', async () => {
		await renderPage();
		const nameInput = screen.getByPlaceholderText('Enter your name');
		await fireEvent.input(nameInput, { target: { value: 'A' } });
		const continueBtn = screen.getByRole('button', { name: '↗' });
		expect(continueBtn.hasAttribute('disabled')).toBe(true);
	});

	it('moves from name to topics to usage', async () => {
		await renderPage();

		const nameInput = screen.getByPlaceholderText('Enter your name');
		await fireEvent.input(nameInput, { target: { value: 'Affan' } });
		await fireEvent.click(screen.getByRole('button', { name: '↗' }));

		expect(screen.getByText(/pick three topics to explore/i)).toBeTruthy();

		await fireEvent.click(screen.getByRole('button', { name: /coding & developing/i }));
		await fireEvent.click(screen.getByRole('button', { name: /learning & studying/i }));
		await fireEvent.click(screen.getByRole('button', { name: /business & strategy/i }));

		expect(screen.getByText('3/3 selected')).toBeTruthy();

		await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

		expect(screen.getByText(/how are you planning to use midsphere/i)).toBeTruthy();
		expect(screen.getByRole('button', { name: /with my team/i }).hasAttribute('disabled')).toBe(
			true
		);
	});

	it('does not render a skip onboarding action', async () => {
		await renderPage();
		expect(screen.queryByRole('button', { name: /skip onboarding/i })).toBeNull();
	});

	it('bootstraps the current user on onboarding when a token exists', async () => {
		mockAuthToken.set('token-123');
		mockCurrentUserStore.set(null as never);
		mockFetchCurrentUser.mockImplementation(async () => {
			mockCurrentUserStore.set({
				id: 'user-123',
				name: 'Test User',
				email: 'test@example.com',
				avatar: '',
				is_active: true,
				date_joined: '2026-01-01',
				last_login: null,
				enterprise_mode: true
			});
		});

		await renderPage();

		expect(mockFetchCurrentUser).toHaveBeenCalled();
		await fireEvent.input(screen.getByPlaceholderText('Enter your name'), {
			target: { value: 'Affan' }
		});
		await fireEvent.click(screen.getByRole('button', { name: '↗' }));
		await fireEvent.click(screen.getByRole('button', { name: /coding & developing/i }));
		await fireEvent.click(screen.getByRole('button', { name: /learning & studying/i }));
		await fireEvent.click(screen.getByRole('button', { name: /business & strategy/i }));
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

		expect(screen.getByRole('button', { name: /with my team/i }).hasAttribute('disabled')).toBe(
			false
		);
		expect(
			screen.queryByText('Team mode becomes available after enabling enterprise mode.')
		).toBeNull();
	});

	async function advanceToCompliance() {
		await renderPage();
		await fireEvent.input(screen.getByPlaceholderText('Enter your name'), {
			target: { value: 'Affan' }
		});
		await fireEvent.click(screen.getByRole('button', { name: '↗' }));
		await fireEvent.click(screen.getByRole('button', { name: /coding & developing/i }));
		await fireEvent.click(screen.getByRole('button', { name: /learning & studying/i }));
		await fireEvent.click(screen.getByRole('button', { name: /business & strategy/i }));
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
		// usage step — personal is default
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
		// profile step — all fields optional
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
		// now on compliance
	}

	it('compliance step gates Continue until retention is acknowledged', async () => {
		await advanceToCompliance();

		expect(screen.getByText(/privacy & compliance/i)).toBeTruthy();
		const continueBtn = screen.getByRole('button', { name: 'Continue' });
		expect(continueBtn.hasAttribute('disabled')).toBe(true);

		const ack = screen.getByLabelText(/i acknowledge the data retention policy/i);
		await fireEvent.click(ack);

		expect(continueBtn.hasAttribute('disabled')).toBe(false);
	});

	it('plan step renders a View all plans link to /billing/plans', async () => {
		await advanceToCompliance();
		const ack = screen.getByLabelText(/i acknowledge the data retention policy/i);
		await fireEvent.click(ack);
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

		expect(screen.getByText(/your plan/i)).toBeTruthy();
		const link = screen.getByRole('link', { name: /view all plans/i });
		expect(link.getAttribute('href')).toBe('/billing/plans');
		expect(link.getAttribute('target')).toBe('_blank');
	});

	it('walks the personal flow to review and shows consents and plan rows', async () => {
		await advanceToCompliance();
		await fireEvent.click(screen.getByLabelText(/i acknowledge the data retention policy/i));
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // → plan
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // → review

		expect(screen.getByText(/everything looks good/i)).toBeTruthy();
		expect(screen.getByText('Consents')).toBeTruthy();
		expect(screen.getByText('Plan')).toBeTruthy();
		expect(screen.getByText('Free')).toBeTruthy();
	});

	it('finish persists consents and marks onboarding complete', async () => {
		mockSaveSettingsImmediately.mockClear();
		mockUpdateUserConsent.mockClear();

		await advanceToCompliance();
		await fireEvent.click(screen.getByLabelText(/i acknowledge the data retention policy/i));
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // → plan
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // → review
		await fireEvent.click(screen.getByRole('button', { name: /continue|finishing/i }));

		await new Promise((r) => setTimeout(r, 0));

		expect(mockUpdateUserConsent).toHaveBeenCalledTimes(3);
		expect(mockSaveSettingsImmediately).toHaveBeenCalledWith(
			expect.objectContaining({ onboarding_completed: true })
		);
	});

	it('selecting MFA later writes the dismiss flag to localStorage', async () => {
		await advanceToCompliance();
		await fireEvent.click(screen.getByLabelText(/i acknowledge the data retention policy/i));
		await fireEvent.click(screen.getByRole('button', { name: /i'll set it up later/i }));
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // → plan
		await fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // → review
		await fireEvent.click(screen.getByRole('button', { name: /continue|finishing/i }));

		await new Promise((r) => setTimeout(r, 0));

		expect(localStorage.getItem('midsphere-mfa-dismissed')).toBe('1');
	});
});
