import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ForgotPasswordPage from '../routes/(public)/forgot-password/+page.svelte';

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
const mockRequestPasswordOTP = vi.fn();
const mockVerifyPasswordOTPOnly = vi.fn();
const mockVerifyPasswordOTP = vi.fn();
vi.mock('$api/auth', () => ({
	requestPasswordOTP: (...args: unknown[]) => mockRequestPasswordOTP(...args),
	verifyPasswordOTPOnly: (...args: unknown[]) => mockVerifyPasswordOTPOnly(...args),
	verifyPasswordOTP: (...args: unknown[]) => mockVerifyPasswordOTP(...args)
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

describe('Forgot Password Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		localStorageMock.clear();
	});

	describe('Step 1: Email', () => {
		it('renders the email step by default', () => {
			render(ForgotPasswordPage);

			expect(screen.getByText('Reset your password')).toBeTruthy();
			expect(
				screen.getByText("Enter your email and we'll send you a verification code.")
			).toBeTruthy();
			expect(screen.getByLabelText(/Email/)).toBeTruthy();
			expect(screen.getByRole('button', { name: 'Send Verification Code' })).toBeTruthy();
		});

		it('renders the step indicator', () => {
			render(ForgotPasswordPage);

			const steps = document.querySelectorAll('.h-0\\.5.rounded-full');
			expect(steps.length).toBe(3);
		});

		it('shows sign in link', () => {
			render(ForgotPasswordPage);

			expect(screen.getByText('Remember your password?')).toBeTruthy();
			const signInLink = screen.getByText('Sign in');
			expect(signInLink.getAttribute('href')).toBe('/login');
		});

		it('validates empty email', async () => {
			render(ForgotPasswordPage);

			const submitBtn = screen.getByRole('button', {
				name: 'Send Verification Code'
			});
			await fireEvent.click(submitBtn);

			expect(screen.getByText('Email is required')).toBeTruthy();
			expect(mockRequestPasswordOTP).not.toHaveBeenCalled();
		});

		it('validates invalid email format', async () => {
			render(ForgotPasswordPage);

			const emailInput = screen.getByLabelText(/Email/);
			await fireEvent.input(emailInput, { target: { value: 'notanemail' } });

			const submitBtn = screen.getByRole('button', {
				name: 'Send Verification Code'
			});
			await fireEvent.click(submitBtn);

			expect(screen.getByText('Please enter a valid email address')).toBeTruthy();
		});

		it('calls requestPasswordOTP and advances to OTP step on valid email', async () => {
			mockRequestPasswordOTP.mockResolvedValue({
				success: true,
				message: 'OTP sent'
			});

			render(ForgotPasswordPage);

			const emailInput = screen.getByLabelText(/Email/);
			await fireEvent.input(emailInput, {
				target: { value: 'test@example.com' }
			});

			const submitBtn = screen.getByRole('button', {
				name: 'Send Verification Code'
			});
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(mockRequestPasswordOTP).toHaveBeenCalledWith('test@example.com');
				expect(screen.getByText('Check your email')).toBeTruthy();
			});
		});

		it('shows loading state while sending OTP', async () => {
			mockRequestPasswordOTP.mockReturnValue(new Promise(() => {}));

			render(ForgotPasswordPage);

			const emailInput = screen.getByLabelText(/Email/);
			await fireEvent.input(emailInput, {
				target: { value: 'test@example.com' }
			});

			const submitBtn = screen.getByRole('button', {
				name: 'Send Verification Code'
			});
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('Sending code...')).toBeTruthy();
			});
		});

		it('shows error for non-existent email', async () => {
			mockRequestPasswordOTP.mockRejectedValue({
				status: 404,
				message: 'Not found'
			});

			render(ForgotPasswordPage);

			const emailInput = screen.getByLabelText(/Email/);
			await fireEvent.input(emailInput, {
				target: { value: 'unknown@example.com' }
			});

			const submitBtn = screen.getByRole('button', {
				name: 'Send Verification Code'
			});
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('No account found with this email address.')).toBeTruthy();
			});
		});

		it('shows rate limit error', async () => {
			mockRequestPasswordOTP.mockRejectedValue({
				status: 429,
				message: 'Rate limited'
			});

			render(ForgotPasswordPage);

			const emailInput = screen.getByLabelText(/Email/);
			await fireEvent.input(emailInput, {
				target: { value: 'test@example.com' }
			});

			const submitBtn = screen.getByRole('button', {
				name: 'Send Verification Code'
			});
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('Too many attempts. Please try again later.')).toBeTruthy();
			});
		});
	});

	describe('Step 2: OTP', () => {
		async function advanceToOtpStep() {
			mockRequestPasswordOTP.mockResolvedValue({
				success: true,
				message: 'OTP sent'
			});

			render(ForgotPasswordPage);

			const emailInput = screen.getByLabelText(/Email/);
			await fireEvent.input(emailInput, {
				target: { value: 'test@example.com' }
			});

			const submitBtn = screen.getByRole('button', {
				name: 'Send Verification Code'
			});
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('Check your email')).toBeTruthy();
			});
		}

		it('displays OTP input fields', async () => {
			await advanceToOtpStep();

			const inputs = screen.getAllByRole('textbox');
			expect(inputs.length).toBe(6);
		});

		it('shows the email address', async () => {
			await advanceToOtpStep();

			expect(screen.getByText('test@example.com')).toBeTruthy();
		});

		it('shows resend cooldown timer', async () => {
			await advanceToOtpStep();

			expect(screen.getByText(/Resend in/)).toBeTruthy();
		});

		it('shows back to email button', async () => {
			await advanceToOtpStep();

			expect(screen.getByText('Back to email')).toBeTruthy();
		});

		it('disables verify button when OTP is incomplete', async () => {
			await advanceToOtpStep();

			const verifyBtn = screen.getByRole('button', { name: 'Verify Code' });
			expect(verifyBtn.hasAttribute('disabled')).toBe(true);
		});

		it('calls verifyPasswordOTPOnly and advances on valid OTP', async () => {
			mockVerifyPasswordOTPOnly.mockResolvedValue({
				success: true,
				message: 'OTP verified'
			});

			await advanceToOtpStep();

			const otpInputs = screen.getAllByRole('textbox');
			const digits = ['1', '2', '3', '4', '5', '6'];
			for (let i = 0; i < 6; i++) {
				await fireEvent.input(otpInputs[i], { target: { value: digits[i] } });
			}

			await fireEvent.click(screen.getByRole('button', { name: 'Verify Code' }));

			await vi.waitFor(() => {
				expect(mockVerifyPasswordOTPOnly).toHaveBeenCalledWith({
					email: 'test@example.com',
					otp: '123456'
				});
				expect(screen.getByText('Set new password')).toBeTruthy();
			});
		});

		it('shows error on invalid OTP', async () => {
			mockVerifyPasswordOTPOnly.mockResolvedValue({
				success: false,
				message: 'Invalid OTP or email.'
			});

			await advanceToOtpStep();

			const otpInputs = screen.getAllByRole('textbox');
			const digits = ['9', '9', '9', '9', '9', '9'];
			for (let i = 0; i < 6; i++) {
				await fireEvent.input(otpInputs[i], { target: { value: digits[i] } });
			}

			await fireEvent.click(screen.getByRole('button', { name: 'Verify Code' }));

			await vi.waitFor(() => {
				expect(mockVerifyPasswordOTPOnly).toHaveBeenCalled();
				expect(screen.getByText('Invalid OTP or email.')).toBeTruthy();
			});
		});

		it('shows error on expired OTP during verification', async () => {
			mockVerifyPasswordOTPOnly.mockRejectedValue({
				status: 400,
				message: 'OTP has expired'
			});

			await advanceToOtpStep();

			const otpInputs = screen.getAllByRole('textbox');
			const digits = ['1', '2', '3', '4', '5', '6'];
			for (let i = 0; i < 6; i++) {
				await fireEvent.input(otpInputs[i], { target: { value: digits[i] } });
			}

			await fireEvent.click(screen.getByRole('button', { name: 'Verify Code' }));

			await vi.waitFor(() => {
				expect(screen.getByText('OTP has expired. Please request a new code.')).toBeTruthy();
			});
		});

		it('navigates back to email step on back button click', async () => {
			await advanceToOtpStep();

			const backBtn = screen.getByText('Back to email');
			await fireEvent.click(backBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('Reset your password')).toBeTruthy();
			});
		});
	});

	describe('Step 3: New Password', () => {
		async function advanceToPasswordStep() {
			mockRequestPasswordOTP.mockResolvedValue({
				success: true,
				message: 'OTP sent'
			});
			mockVerifyPasswordOTPOnly.mockResolvedValue({
				success: true,
				message: 'OTP verified'
			});

			render(ForgotPasswordPage);

			// Step 1: Enter email
			const emailInput = screen.getByLabelText(/Email/);
			await fireEvent.input(emailInput, {
				target: { value: 'test@example.com' }
			});
			await fireEvent.click(screen.getByRole('button', { name: 'Send Verification Code' }));

			await vi.waitFor(() => {
				expect(screen.getByText('Check your email')).toBeTruthy();
			});

			// Step 2: Enter OTP digits
			const otpInputs = screen.getAllByRole('textbox');
			const digits = ['1', '2', '3', '4', '5', '6'];
			for (let i = 0; i < 6; i++) {
				await fireEvent.input(otpInputs[i], { target: { value: digits[i] } });
			}

			await fireEvent.click(screen.getByRole('button', { name: 'Verify Code' }));

			await vi.waitFor(() => {
				expect(screen.getByText('Set new password')).toBeTruthy();
			});
		}

		it('renders the new password form', async () => {
			await advanceToPasswordStep();

			expect(screen.getByText('Set new password')).toBeTruthy();
			expect(screen.getByLabelText(/New password/)).toBeTruthy();
			expect(screen.getByLabelText(/Confirm password/)).toBeTruthy();
			expect(screen.getByRole('button', { name: 'Reset Password' })).toBeTruthy();
		});

		it('validates empty password', async () => {
			await advanceToPasswordStep();

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			expect(screen.getByText('Password is required')).toBeTruthy();
		});

		it('validates short password', async () => {
			await advanceToPasswordStep();

			const pwInput = screen.getByLabelText(/New password/);
			await fireEvent.input(pwInput, { target: { value: 'short' } });

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			expect(screen.getByText('Password must be at least 8 characters')).toBeTruthy();
		});

		it('validates password mismatch', async () => {
			await advanceToPasswordStep();

			const pwInput = screen.getByLabelText(/New password/);
			await fireEvent.input(pwInput, { target: { value: 'validpassword123' } });

			const confirmInput = screen.getByLabelText(/Confirm password/);
			await fireEvent.input(confirmInput, {
				target: { value: 'differentpassword' }
			});

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			expect(screen.getByText('Passwords do not match')).toBeTruthy();
		});

		it('calls verifyPasswordOTP on valid submit', async () => {
			mockVerifyPasswordOTP.mockResolvedValue({
				success: true,
				message: 'Password reset'
			});

			await advanceToPasswordStep();

			const pwInput = screen.getByLabelText(/New password/);
			await fireEvent.input(pwInput, { target: { value: 'newpassword123' } });

			const confirmInput = screen.getByLabelText(/Confirm password/);
			await fireEvent.input(confirmInput, {
				target: { value: 'newpassword123' }
			});

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(mockVerifyPasswordOTP).toHaveBeenCalledWith({
					email: 'test@example.com',
					otp: '123456',
					new_password: 'newpassword123'
				});
			});
		});

		it('shows success toast and redirects on success', async () => {
			const { goto } = await import('$app/navigation');
			const { toasts } = await import('$stores/toast');
			mockVerifyPasswordOTP.mockResolvedValue({
				success: true,
				message: 'Password reset'
			});

			await advanceToPasswordStep();

			const pwInput = screen.getByLabelText(/New password/);
			await fireEvent.input(pwInput, { target: { value: 'newpassword123' } });

			const confirmInput = screen.getByLabelText(/Confirm password/);
			await fireEvent.input(confirmInput, {
				target: { value: 'newpassword123' }
			});

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(toasts.success).toHaveBeenCalledWith(
					'Password reset successfully! Please sign in with your new password.'
				);
				expect(goto).toHaveBeenCalledWith('/login');
			});
		});

		it('shows error on expired OTP', async () => {
			mockVerifyPasswordOTP.mockRejectedValue({
				status: 400,
				message: 'OTP has expired'
			});

			await advanceToPasswordStep();

			const pwInput = screen.getByLabelText(/New password/);
			await fireEvent.input(pwInput, { target: { value: 'newpassword123' } });

			const confirmInput = screen.getByLabelText(/Confirm password/);
			await fireEvent.input(confirmInput, {
				target: { value: 'newpassword123' }
			});

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('OTP has expired. Please request a new code.')).toBeTruthy();
			});
		});

		it('shows error on invalid OTP', async () => {
			mockVerifyPasswordOTP.mockRejectedValue({
				status: 400,
				message: 'Invalid OTP'
			});

			await advanceToPasswordStep();

			const pwInput = screen.getByLabelText(/New password/);
			await fireEvent.input(pwInput, { target: { value: 'newpassword123' } });

			const confirmInput = screen.getByLabelText(/Confirm password/);
			await fireEvent.input(confirmInput, {
				target: { value: 'newpassword123' }
			});

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('Invalid OTP code. Please check and try again.')).toBeTruthy();
			});
		});

		it('shows back to verification button', async () => {
			await advanceToPasswordStep();

			expect(screen.getByText('Back to verification')).toBeTruthy();
		});

		it('shows loading state while resetting password', async () => {
			mockVerifyPasswordOTP.mockReturnValue(new Promise(() => {}));

			await advanceToPasswordStep();

			const pwInput = screen.getByLabelText(/New password/);
			await fireEvent.input(pwInput, { target: { value: 'newpassword123' } });

			const confirmInput = screen.getByLabelText(/Confirm password/);
			await fireEvent.input(confirmInput, {
				target: { value: 'newpassword123' }
			});

			const submitBtn = screen.getByRole('button', { name: 'Reset Password' });
			await fireEvent.click(submitBtn);

			await vi.waitFor(() => {
				expect(screen.getByText('Resetting password...')).toBeTruthy();
			});
		});
	});
});
