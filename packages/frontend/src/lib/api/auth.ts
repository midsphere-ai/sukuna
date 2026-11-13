import { api } from './client';
import { setAuth, clearAuth, currentUser, authToken, authLoading } from '$stores/auth';
import { toasts } from '$stores/toast';
import { browser } from '$app/environment';
import { goto } from '$app/navigation';
import type {
	LoginRequest,
	LoginResponse,
	CreateUserRequest,
	GoogleAuthRequest,
	GoogleAuthResponse,
	User,
	RequestOTPRequest,
	VerifyOTPRequest,
	OTPResponse,
	UserUpdateRequest,
	PasswordChangeRequest
} from './types';

export async function login(credentials: LoginRequest, rememberMe?: boolean): Promise<User> {
	const { key } = await api.post<LoginResponse>('/authentication/login/', credentials, {
		skipAuth: true,
		skipErrorHandling: true
	});
	authToken.set(key);

	// Fetch user profile - use skipErrorHandling to prevent the 401 handler
	// from clearing the token we just set (race condition protection)
	const user = await api.get<User>('/workspace/users/me/', { skipErrorHandling: true });
	setAuth(key, user, rememberMe);
	return user;
}

export async function signup(data: CreateUserRequest): Promise<User> {
	await api.post<string>('/workspace/users', data, { skipAuth: true, skipErrorHandling: true });

	return login({ email: data.user_email, password: data.password });
}

export async function loginWithGoogle(idToken: string, rememberMe?: boolean): Promise<User> {
	const data = await api.post<GoogleAuthResponse>(
		'/workspace/google-provider/verify',
		{ id_token: idToken } satisfies GoogleAuthRequest,
		{ skipAuth: true }
	);

	// Set token first so fetchCurrentUser works
	authToken.set(data.key);
	// Await full user profile instead of fabricating one
	const user = await fetchCurrentUser();
	setAuth(data.key, user, rememberMe);
	return user;
}

export async function logout(): Promise<void> {
	try {
		await api.post<unknown>('/authentication/logout/', {}, { skipErrorHandling: true });
	} catch {
		// Logout should clear local state regardless of API response
	}
	clearAuth();
	if (browser) {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto('/login');
	}
}

export async function fetchCurrentUser(): Promise<User> {
	const user = await api.get<User>('/workspace/users/me/');
	currentUser.set(user);
	authLoading.set(false);
	return user;
}

export async function updateUser(
	userId: string,
	data: UserUpdateRequest,
	options?: { skipErrorHandling?: boolean }
): Promise<void> {
	await api.patch<string>(`/workspace/users/${userId}`, data, options);
	// Refresh user data after update
	await fetchCurrentUser();
}

export async function deleteAccount(userId: string): Promise<void> {
	await api.delete<string>(`/workspace/users/${userId}`);
	clearAuth();
	if (browser) {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto('/login');
	}
}

export async function changePassword(data: PasswordChangeRequest): Promise<void> {
	await api.post<{ detail: string }>('/authentication/password/change/', data);
	toasts.success('Password changed successfully.');
}

export async function requestPasswordOTP(email: string): Promise<OTPResponse> {
	return api.post<OTPResponse>(
		'/workspace/password/request-otp',
		{ email } satisfies RequestOTPRequest,
		{ skipAuth: true, skipErrorHandling: true }
	);
}

export async function verifyPasswordOTPOnly(data: {
	email: string;
	otp: string;
}): Promise<OTPResponse> {
	return api.post<OTPResponse>('/workspace/password/verify-otp-only', data, {
		skipAuth: true,
		skipErrorHandling: true
	});
}

export async function verifyPasswordOTP(data: VerifyOTPRequest): Promise<OTPResponse> {
	return api.post<OTPResponse>('/workspace/password/verify-otp', data, {
		skipAuth: true,
		skipErrorHandling: true
	});
}

export async function initAuth(): Promise<void> {
	authLoading.set(true);
	try {
		await fetchCurrentUser();
	} catch (err) {
		// Only clear auth on definitive auth failures (401/403)
		// Network errors or server errors should not log the user out
		const status = (err as { status?: number }).status;
		if (status === 401 || status === 403) {
			clearAuth();
		} else {
			// Server/network error - keep the token, just mark loading done
			authLoading.set(false);
		}
		throw err;
	}
}
