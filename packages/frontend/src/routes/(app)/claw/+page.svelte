<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import {
		clawStatus,
		clawConversations,
		clawActivating,
		fetchClawStatus,
		fetchClawConversations,
		activateClaw,
		deactivateClaw,
		startClawStatusPolling,
		stopClawStatusPolling
	} from '$stores/claw';
	import { sendClawMessage, linkTelegram, linkSlack, getSlackInstallUrl } from '$api/claw';
	import type { ClawStatus, ClawConversation } from '$api/claw';
	import ClawStatusCard from '$components/claw/ClawStatusCard.svelte';
	import ClawConversationList from '$components/claw/ClawConversationList.svelte';
	import PlatformLinkCard from '$components/claw/PlatformLinkCard.svelte';
	import ClawChatInput from '$components/claw/ClawChatInput.svelte';

	let status: ClawStatus | null = $state(null);
	let conversations: ClawConversation[] = $state([]);
	let activating = $state(false);
	let statusLoading = $state(true);
	let conversationsLoading = $state(true);
	let quickSending = $state(false);

	// Platform linking state
	let telegramLinked = $state(false);
	let telegramUsername = $state('');
	let slackLinked = $state(false);
	let slackUsername = $state('');

	const unsubStatus = clawStatus.subscribe((s) => {
		status = s;
		if (s) statusLoading = false;
	});
	const unsubConversations = clawConversations.subscribe((c) => {
		conversations = c;
		conversationsLoading = false;
	});
	const unsubActivating = clawActivating.subscribe((a) => {
		activating = a;
	});

	onMount(() => {
		pageTitle.set('Claw Mode');
		showHeaderTitle.set(true);

		startClawStatusPolling();
		fetchClawConversations();

		// Initial load timeout — mark as loaded after delay if API hasn't responded
		const timeout = setTimeout(() => {
			statusLoading = false;
			conversationsLoading = false;
		}, 5000);

		return () => clearTimeout(timeout);
	});

	onDestroy(() => {
		stopClawStatusPolling();
		unsubStatus();
		unsubConversations();
		unsubActivating();
	});

	async function handleActivate(): Promise<void> {
		const success = await activateClaw();
		if (success) {
			toasts.success('Claw sandbox activated');
		} else {
			toasts.error('Failed to activate sandbox');
		}
	}

	async function handleDeactivate(): Promise<void> {
		const success = await deactivateClaw();
		if (success) {
			toasts.success('Claw sandbox deactivated');
		} else {
			toasts.error('Failed to deactivate sandbox');
		}
	}

	async function handleQuickMessage(text: string): Promise<void> {
		quickSending = true;
		try {
			const result = await sendClawMessage({ prompt: text });
			toasts.success('Message sent');
			goto(`/claw/${result.conversation_id}`);
		} catch {
			toasts.error('Failed to send message');
		} finally {
			quickSending = false;
		}
	}

	async function handleLinkTelegram(token: string): Promise<void> {
		try {
			const result = await linkTelegram({ token });
			telegramLinked = true;
			telegramUsername = result.telegram_username;
			toasts.success('Telegram linked successfully');
		} catch {
			toasts.error('Failed to link Telegram');
		}
	}

	async function handleLinkSlack(token: string): Promise<void> {
		try {
			const result = await linkSlack({ token });
			slackLinked = true;
			slackUsername = result.slack_username;
			toasts.success('Slack linked successfully');
		} catch {
			toasts.error('Failed to link Slack');
		}
	}

	async function handleSlackInstall(): Promise<void> {
		try {
			const result = await getSlackInstallUrl();
			if (result.authorize_url) {
				window.open(result.authorize_url, '_blank');
			}
		} catch {
			toasts.error('Failed to get Slack install URL');
		}
	}
</script>

<svelte:head>
	<title>Claw Mode - Jatayu AI</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-6 py-8">
	<h1 class="mb-6 text-2xl font-medium tracking-tight text-foreground">Claw Mode</h1>

	<div class="space-y-6">
		<!-- Section 1: Status Card -->
		<ClawStatusCard
			{status}
			loading={statusLoading}
			{activating}
			onactivate={handleActivate}
			ondeactivate={handleDeactivate}
		/>

		<!-- Section 2: Quick Message -->
		<div class="rounded-xl border border-border p-4" in:fade={{ duration: 100, delay: 30 }}>
			<h2 class="mb-3 text-sm font-medium text-foreground">Quick Message</h2>
			<p class="mb-3 text-xs text-muted">
				Send a message to Claw to start or continue a conversation.
			</p>
			<ClawChatInput
				disabled={quickSending}
				sending={quickSending}
				placeholder="Ask Claw something..."
				onsend={handleQuickMessage}
			/>
		</div>

		<!-- Section 3: Conversations List -->
		<ClawConversationList {conversations} loading={conversationsLoading} />

		<!-- Section 4: Platform Linking -->
		<div in:fade={{ duration: 100, delay: 30 }}>
			<h2 class="mb-3 text-sm font-medium text-foreground">Platform Linking</h2>
			<div class="grid gap-4 sm:grid-cols-3">
				<PlatformLinkCard
					platform="telegram"
					linked={telegramLinked}
					username={telegramUsername}
					onlink={handleLinkTelegram}
				/>
				<div class="flex flex-col gap-2">
					<PlatformLinkCard
						platform="slack"
						linked={slackLinked}
						username={slackUsername}
						onlink={handleLinkSlack}
					/>
					{#if !slackLinked}
						<button
							onclick={handleSlackInstall}
							class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface"
						>
							Add to Slack
						</button>
					{/if}
				</div>
				<PlatformLinkCard
					platform="discord"
					linked={false}
					username=""
					disabled={true}
					onlink={() => {}}
				/>
			</div>
		</div>
	</div>
</div>
