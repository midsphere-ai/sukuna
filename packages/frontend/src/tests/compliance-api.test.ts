import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
	get: vi.fn()
}));

vi.mock('$api/client', () => ({
	api: {
		get: mocks.get
	}
}));

describe('compliance api', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('requests dashboard summary without global auth error handling', async () => {
		mocks.get.mockResolvedValue({});

		const { getDashboardSummary } = await import('$api/compliance');
		await getDashboardSummary();

		expect(mocks.get).toHaveBeenCalledWith('/compliance/dashboard/summary', {
			skipErrorHandling: true
		});
	});
});
