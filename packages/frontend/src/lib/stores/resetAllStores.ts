import { disconnect as disconnectSSE, resetStores as resetSSEStores } from '$services/sse';
import { disconnect as disconnectConversationStream } from '$services/conversationStream';
import { clearChatCache } from '$services/chatCache';
import {
	conversations,
	conversationsLoading,
	conversationsError,
	conversationsPage,
	conversationsHasMore,
	activeConversationId,
	conversationFilter,
	favouriteIds
} from '$stores/conversations';
import {
	notifications,
	unreadCount,
	notificationTotal,
	notificationsLoaded
} from '$stores/notifications';
import { stopNotificationPolling } from '$services/notificationStream';
import { subscription } from '$stores/subscription';
import { creditBalance } from '$stores/credits';
import { branchMap } from '$stores/branches';
import { infoTutorials, tutorialContentCache } from '$stores/infoTutorials';
import { resetAllFlags } from '$stores/featureFlags';

export function resetAllUserStores(): void {
	// Disconnect SSE connections
	try {
		disconnectSSE();
	} catch {
		/* ignore */
	}
	try {
		disconnectConversationStream();
	} catch {
		/* ignore */
	}

	// Reset SSE stores
	try {
		resetSSEStores();
	} catch {
		/* ignore */
	}

	// Reset conversation stores + clear cache
	conversations.set([]);
	try {
		localStorage.removeItem('midsphere-conversations');
	} catch {
		/* ignore */
	}
	conversationsLoading.set(false);
	conversationsError.set(null);
	conversationsPage.set(1);
	conversationsHasMore.set(true);
	activeConversationId.set(null);
	conversationFilter.set('all');
	favouriteIds.set(new Set());

	// Reset subscription store + cache
	subscription.set(null);
	try {
		localStorage.removeItem('midsphere-subscription');
	} catch {
		/* ignore */
	}

	// Reset credit balance store + cache
	creditBalance.set(null);
	try {
		localStorage.removeItem('midsphere-credit-balance');
	} catch {
		/* ignore */
	}

	// Reset notifications
	notifications.set([]);
	unreadCount.set(0);
	notificationTotal.set(0);
	notificationsLoaded.set(false);
	stopNotificationPolling();

	// Reset chat cache
	clearChatCache();

	// Reset branch map
	branchMap.set({});

	// Reset tutorial cache
	infoTutorials.set([]);
	tutorialContentCache.set({});

	// Reset feature flags
	resetAllFlags();
	try {
		localStorage.removeItem('midsphere-feature-flags');
	} catch {
		/* ignore */
	}
}
