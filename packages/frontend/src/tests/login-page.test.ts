import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import LoginPage from '../routes/(public)/login/+page.svelte';

// Mock $app/navigation
vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

// Mock $app/environment
vi.mock('$app/environment', () => ({
	browser: true
}));

// Mock localStorage/sessionStorage for jsdom
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

// Mock auth API
const mockLogin = vi.fn();
const mockLoginWithGoogle = vi.fn();
vi.mock('$api/auth', () => ({
	login: (...args: unknown[]) => mockLogin(...args),
	loginWithGoogle: (...args: unknown[]) => mockLoginWithGoogle(...args)
}));

// Mock toast store
vi.mock('$stores/toast', () => ({
	toasts: {
		success: vi.fn(),
		error: vi.fn(),
		warning: vi.fn(),
		info: vi.fn()
	}
}));

describe('Login Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		localStorageMock.clear();
	});

	it('renders the login form with all fields', () => {
		render(LoginPage);

		expect(screen.getByText('Welcome back')).toBeTruthy();
		expect(screen.getByText('Sign in to continue to Jatayu AI')).toBeTruthy();
		// Labels include required * so use regex
		expect(screen.getByLabelText(/Email/)).toBeTruthy();
		expect(screen.getByLabelText(/Password/)).toBeTruthy();
		expect(screen.getByText('Remember me')).toBeTruthy();
		expect(screen.getByText('Forgot password?')).toBeTruthy();
		expect(screen.getByRole('button', { name: 'Sign In' })).toBeTruthy();
	});

	it('renders Google sign-in button', () => {
		render(LoginPage);

		expect(screen.getByText('Continue with Google')).toBeTruthy();
	});

	it('shows sign up link', () => {
		render(LoginPage);

		expect(screen.getByText("Don't have an account?")).toBeTruthy();
		const signUpLink = screen.getByText('Sign up');
		expect(signUpLink.getAttribute('href')).toBe('/signup');
	});

	it('shows forgot password link', () => {
		render(LoginPage);

		const forgotLink = screen.getByText('Forgot password?');
		expect(forgotLink.getAttribute('href')).toBe('/forgot-password');
	});

	it('validates empty email', async () => {
		render(LoginPage);

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Email is required')).toBeTruthy();
		expect(mockLogin).not.toHaveBeenCalled();
	});

	it('validates invalid email format', async () => {
		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'notanemail' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Please enter a valid email address')).toBeTruthy();
	});

	it('validates empty password', async () => {
		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'test@example.com' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Password is required')).toBeTruthy();
	});

	it('validates short password', async () => {
		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'test@example.com' } });

		const passwordInput = screen.getByLabelText(/Password/);
		await fireEvent.input(passwordInput, { target: { value: '12345' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Password must be at least 6 characters')).toBeTruthy();
	});

	it('calls login API with correct credentials on valid submit', async () => {
		mockLogin.mockResolvedValue({
			id: '1',
			name: 'Test User',
			email: 'test@example.com',
			is_active: true,
			date_joined: '2026-01-01',
			last_login: '2026-01-01'
		});

		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'test@example.com' } });

		const passwordInput = screen.getByLabelText(/Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		expect(mockLogin).toHaveBeenCalledWith(
			{
				email: 'test@example.com',
				password: 'password123'
			},
			false
		);
	});

	it('shows error message on login failure (401)', async () => {
		mockLogin.mockRejectedValue({ status: 401, message: 'Unauthorized' });

		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'test@example.com' } });

		const passwordInput = screen.getByLabelText(/Password/);
		await fireEvent.input(passwordInput, { target: { value: 'wrongpassword' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			expect(screen.getByText('Invalid email or password. Please try again.')).toBeTruthy();
		});
	});

	it('shows generic error on server error', async () => {
		mockLogin.mockRejectedValue({ status: 500, message: 'Server Error' });

		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'test@example.com' } });

		const passwordInput = screen.getByLabelText(/Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			expect(screen.getByText('Server error. Please try again later.')).toBeTruthy();
		});
	});

	it('shows loading state on submit button while logging in', async () => {
		mockLogin.mockReturnValue(new Promise(() => {}));

		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'test@example.com' } });

		const passwordInput = screen.getByLabelText(/Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			expect(screen.getByText('Signing in...')).toBeTruthy();
		});
	});

	it('disables submit button while loading', async () => {
		mockLogin.mockReturnValue(new Promise(() => {}));

		render(LoginPage);

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'test@example.com' } });

		const passwordInput = screen.getByLabelText(/Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Sign In' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			const loadingBtn = screen.getByRole('button', { name: /Signing in/ });
			expect(loadingBtn.hasAttribute('disabled')).toBe(true);
		});
	});

	it('has Remember me toggle', () => {
		render(LoginPage);

		const toggle = screen.getByRole('switch');
		expect(toggle).toBeTruthy();
		expect(screen.getByText('Remember me')).toBeTruthy();
	});
});
