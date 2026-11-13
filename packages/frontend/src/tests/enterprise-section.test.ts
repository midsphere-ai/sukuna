import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import EnterpriseSection from '$components/settings/EnterpriseSection.svelte';

const mocks = vi.hoisted(() => ({
	getEnterpriseMode: vi.fn(),
	updateEnterpriseMode: vi.fn(),
	fetchCurrentUser: vi.fn(),
	goto: vi.fn(),
	usageLimitShow: vi.fn(),
	toastSuccess: vi.fn(),
	toastError: vi.fn()
}));

vi.mock('$api/enterprise', () => ({
	getEnterpriseMode: mocks.getEnterpriseMode,
	updateEnterpriseMode: mocks.updateEnterpriseMode
}));

vi.mock('$api/auth', () => ({
	fetchCurrentUser: mocks.fetchCurrentUser
}));

vi.mock('$app/navigation', () => ({
	goto: mocks.goto
}));

vi.mock('$stores/usageLimit', () => ({
	usageLimitModal: {
		show: mocks.usageLimitShow
	}
}));

vi.mock('$stores/toast', () => ({
	toasts: {
		success: mocks.toastSuccess,
		error: mocks.toastError
	}
}));

describe('EnterpriseSection', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('always shows enterprise toggle and prompts upgrade for unavailable plan', async () => {
		mocks.getEnterpriseMode.mockResolvedValue({ enabled: false, available: false });

		render(EnterpriseSection);

		const toggle = await screen.findByRole('switch', { name: 'Enterprise Mode' });
		expect(toggle).toBeInTheDocument();

		await fireEvent.click(toggle);

		expect(mocks.usageLimitShow).toHaveBeenCalledWith({
			limitType: 'enterprise_mode',
			message: 'Enterprise mode requires a paid subscription.'
		});
		expect(screen.queryByText('Confirm your password')).not.toBeInTheDocument();
	});

	it('asks for password when enabling is available on current plan', async () => {
		mocks.getEnterpriseMode.mockResolvedValue({ enabled: false, available: true });

		render(EnterpriseSection);

		const toggle = await screen.findByRole('switch', { name: 'Enterprise Mode' });
		await fireEvent.click(toggle);

		await waitFor(() => {
			expect(screen.getByText('Confirm your password')).toBeInTheDocument();
		});
		expect(mocks.usageLimitShow).not.toHaveBeenCalled();
	});

	it('disables the toggle and shows an error when enterprise status fails to load', async () => {
		mocks.getEnterpriseMode.mockRejectedValue(new Error('network'));

		render(EnterpriseSection);

		const toggle = await screen.findByRole('switch', { name: 'Enterprise Mode' });
		expect(toggle).toBeDisabled();
		expect(
			screen.getByText('Unable to load enterprise mode status right now.')
		).toBeInTheDocument();

		await fireEvent.click(toggle);

		expect(screen.queryByText('Confirm your password')).not.toBeInTheDocument();
		expect(mocks.usageLimitShow).not.toHaveBeenCalled();
	});
});
