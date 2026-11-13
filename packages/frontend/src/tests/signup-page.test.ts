import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import SignupPage from '../routes/(public)/signup/+page.svelte';

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
const mockSignup = vi.fn();
const mockLoginWithGoogle = vi.fn();
vi.mock('$api/auth', () => ({
	signup: (...args: unknown[]) => mockSignup(...args),
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

describe('Signup Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		localStorageMock.clear();
	});

	it('renders the signup form with all fields', () => {
		render(SignupPage);

		expect(screen.getByText('Create your account')).toBeTruthy();
		expect(screen.getByText('Get started with Jatayu AI in seconds')).toBeTruthy();
		expect(screen.getByLabelText(/Full name/)).toBeTruthy();
		expect(screen.getByLabelText(/Email/)).toBeTruthy();
		// Two password fields (Password and Confirm password)
		expect(screen.getByLabelText(/^Password/)).toBeTruthy();
		expect(screen.getByLabelText(/Confirm password/)).toBeTruthy();
		expect(screen.getByRole('button', { name: 'Create Account' })).toBeTruthy();
	});

	it('renders Google sign-up button', () => {
		render(SignupPage);

		expect(screen.getByText('Continue with Google')).toBeTruthy();
	});

	it('shows login link', () => {
		render(SignupPage);

		expect(screen.getByText('Already have an account?')).toBeTruthy();
		const loginLink = screen.getByText('Log in');
		expect(loginLink.getAttribute('href')).toBe('/login');
	});

	it('validates empty full name', async () => {
		render(SignupPage);

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Full name is required')).toBeTruthy();
		expect(mockSignup).not.toHaveBeenCalled();
	});

	it('validates empty email', async () => {
		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Email is required')).toBeTruthy();
	});

	it('validates invalid email format', async () => {
		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'notanemail' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Please enter a valid email address')).toBeTruthy();
	});

	it('validates short password', async () => {
		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'john@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: '1234567' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Password must be at least 8 characters')).toBeTruthy();
	});

	it('validates password mismatch', async () => {
		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'john@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const confirmInput = screen.getByLabelText(/Confirm password/);
		await fireEvent.input(confirmInput, { target: { value: 'different123' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Passwords do not match')).toBeTruthy();
	});

	it('validates empty confirm password', async () => {
		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'john@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		expect(screen.getByText('Please confirm your password')).toBeTruthy();
	});

	it('calls signup API with correct data on valid submit', async () => {
		mockSignup.mockResolvedValue({
			id: '1',
			name: 'John Doe',
			email: 'john@example.com',
			is_active: true,
			date_joined: '2026-01-01',
			last_login: null
		});

		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'john@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const confirmInput = screen.getByLabelText(/Confirm password/);
		await fireEvent.input(confirmInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		expect(mockSignup).toHaveBeenCalledWith({
			user_name: 'John Doe',
			user_email: 'john@example.com',
			password: 'password123'
		});
	});

	it('shows error message on signup failure (400 — duplicate email)', async () => {
		mockSignup.mockRejectedValue({ status: 400, message: 'Bad Request' });

		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'existing@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const confirmInput = screen.getByLabelText(/Confirm password/);
		await fireEvent.input(confirmInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			expect(screen.getByText('An account with this email already exists.')).toBeTruthy();
		});
	});

	it('shows generic error on server error', async () => {
		mockSignup.mockRejectedValue({ status: 500, message: 'Server Error' });

		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'john@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const confirmInput = screen.getByLabelText(/Confirm password/);
		await fireEvent.input(confirmInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			expect(screen.getByText('Something went wrong. Please try again later.')).toBeTruthy();
		});
	});

	it('shows loading state on submit button while signing up', async () => {
		mockSignup.mockReturnValue(new Promise(() => {}));

		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'john@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const confirmInput = screen.getByLabelText(/Confirm password/);
		await fireEvent.input(confirmInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			expect(screen.getByText('Creating account...')).toBeTruthy();
		});
	});

	it('disables submit button while loading', async () => {
		mockSignup.mockReturnValue(new Promise(() => {}));

		render(SignupPage);

		const nameInput = screen.getByLabelText(/Full name/);
		await fireEvent.input(nameInput, { target: { value: 'John Doe' } });

		const emailInput = screen.getByLabelText(/Email/);
		await fireEvent.input(emailInput, { target: { value: 'john@example.com' } });

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'password123' } });

		const confirmInput = screen.getByLabelText(/Confirm password/);
		await fireEvent.input(confirmInput, { target: { value: 'password123' } });

		const submitBtn = screen.getByRole('button', { name: 'Create Account' });
		await fireEvent.click(submitBtn);

		await vi.waitFor(() => {
			const loadingBtn = screen.getByRole('button', { name: /Creating account/ });
			expect(loadingBtn.hasAttribute('disabled')).toBe(true);
		});
	});

	it('shows password strength indicator for weak password', async () => {
		render(SignupPage);

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'short' } });

		expect(screen.getByText('Weak')).toBeTruthy();
	});

	it('shows password strength indicator for strong password', async () => {
		render(SignupPage);

		const passwordInput = screen.getByLabelText(/^Password/);
		await fireEvent.input(passwordInput, { target: { value: 'StrongPass1!' } });

		expect(screen.getByText('Strong')).toBeTruthy();
	});
});
