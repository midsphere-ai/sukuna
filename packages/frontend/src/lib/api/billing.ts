import { api } from './client';
import type {
	ActionResponse,
	CreditBalance,
	CreditPurchaseResponse,
	CreditTransaction,
	CreditUsageSummary,
	SubscriptionPlan,
	UserSubscription,
	Payment,
	SupportTicket,
	PaginatedResponse
} from './types';

export async function getSubscriptionPlans(): Promise<PaginatedResponse<SubscriptionPlan>> {
	return api.get<PaginatedResponse<SubscriptionPlan>>('/billing/plans');
}

export async function getUserSubscription(options?: {
	skipErrorHandling?: boolean;
}): Promise<UserSubscription> {
	return api.get<UserSubscription>('/billing/subscription', options);
}

export async function createSubscription(planId: string): Promise<{
	checkout_url: string;
	subscription_id: string;
	message?: string;
}> {
	return api.post('/billing/subscription/create', { plan_id: planId });
}

export async function cancelSubscription(immediate = false): Promise<ActionResponse> {
	return api.post('/billing/subscription/cancel', { immediate });
}

export async function cancelPendingSubscription(): Promise<ActionResponse> {
	return api.post('/billing/subscription/cancel-pending', {});
}

export async function changePlan(newPlanId: string, immediate = false): Promise<ActionResponse> {
	return api.post('/billing/subscription/change', {
		new_plan_id: newPlanId,
		immediate
	});
}

export async function reactivateSubscription(): Promise<ActionResponse> {
	return api.post('/billing/subscription/reactivate', {});
}

export async function retryPayment(): Promise<{ payment_link: string | null; message: string }> {
	return api.post('/billing/payment/retry', {});
}

export async function requestRefund(paymentId: string, reason: string): Promise<ActionResponse> {
	return api.post('/billing/refund', { payment_id: paymentId, reason });
}

export async function getPaymentHistory(): Promise<PaginatedResponse<Payment>> {
	return api.get<PaginatedResponse<Payment>>('/billing/payments');
}

export async function getGracePeriodStatus(): Promise<{
	in_grace_period: boolean;
	grace_period_end: string | null;
}> {
	return api.get('/billing/subscription/grace-period');
}

// Promo Code

export async function validatePromoCode(
	code: string
): Promise<{ valid: boolean; discount_percent: number; message: string }> {
	return api.post('/billing/promo/validate', { code });
}

// Support Tickets

export async function getSupportTickets(): Promise<PaginatedResponse<SupportTicket>> {
	return api.get<PaginatedResponse<SupportTicket>>('/billing/support/tickets');
}

export async function getSupportTicket(ticketId: string): Promise<SupportTicket> {
	return api.get<SupportTicket>(`/billing/support/tickets/${ticketId}`);
}

export async function createSupportTicket(title: string, message: string): Promise<SupportTicket> {
	return api.post('/billing/support/tickets', { title, message });
}

export async function updateSupportTicket(
	ticketId: string,
	data: { title?: string; message?: string; status?: string }
): Promise<SupportTicket> {
	return api.put(`/billing/support/tickets/${ticketId}`, data);
}

export async function deleteSupportTicket(ticketId: string): Promise<ActionResponse> {
	return api.delete(`/billing/support/tickets/${ticketId}`);
}

// Credits

export async function getCreditBalance(): Promise<CreditBalance> {
	return api.get<CreditBalance>('/billing/credits/balance');
}

export async function getCreditTransactions(
	page = 1,
	category?: string
): Promise<PaginatedResponse<CreditTransaction>> {
	const params = new URLSearchParams({ page: String(page) });
	if (category) params.set('category', category);
	return api.get<PaginatedResponse<CreditTransaction>>(
		`/billing/credits/transactions?${params.toString()}`
	);
}

export async function getCreditUsageSummary(): Promise<CreditUsageSummary> {
	return api.get<CreditUsageSummary>('/billing/credits/usage');
}

export async function purchaseCredits(packs = 1): Promise<CreditPurchaseResponse> {
	return api.post('/billing/credits/purchase', { packs });
}
