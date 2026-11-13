<script lang="ts">
	import { Badge } from '$components/ui';
	import {
		notificationsWithReadState,
		unreadCount,
		markAsRead,
		markAllAsRead,
		type AppNotification,
		type NotificationType
	} from '$stores/notifications';
	import { formatRelativeTime } from '$stores/conversations';

	let open = $state(false);
	let items: AppNotification[] = $state([]);
	let unread = $state(0);

	notificationsWithReadState.subscribe((v) => (items = v));
	unreadCount.subscribe((v) => (unread = v));

	function toggle(): void {
		open = !open;
	}

	function closePanel(): void {
		open = false;
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			closePanel();
		}
	}

	function handleNotificationClick(notification: AppNotification): void {
		if (!notification.read) {
			markAsRead(notification.id);
		}
		if (notification.href) {
			closePanel();
		}
	}

	function handleMarkAllRead(): void {
		markAllAsRead();
	}

	function getTypeColor(type: NotificationType): string {
		switch (type) {
			case 'injection':
				return 'text-accent';
			case 'mention':
				return 'text-purple-500 dark:text-purple-400';
			case 'agent_completed':
				return 'text-success';
			case 'invitation':
				return 'text-amber-500 dark:text-amber-400';
			case 'share':
				return 'text-accent';
			default:
				return 'text-subtle';
		}
	}

	function getIconBgColor(type: NotificationType): string {
		switch (type) {
			case 'injection':
				return 'bg-accent/[0.08]';
			case 'mention':
				return 'bg-purple-500/[0.08]';
			case 'agent_completed':
				return 'bg-success/[0.08]';
			case 'invitation':
				return 'bg-amber-500/[0.08]';
			case 'share':
				return 'bg-accent/[0.08]';
			default:
				return 'bg-surface-2';
		}
	}

	function getTypeBadgeVariant(
		type: NotificationType
	): 'default' | 'coral' | 'blue' | 'green' | 'warning' | 'muted' {
		switch (type) {
			case 'injection':
				return 'blue';
			case 'mention':
				return 'muted';
			case 'agent_completed':
				return 'green';
			case 'invitation':
				return 'warning';
			case 'share':
				return 'coral';
			default:
				return 'default';
		}
	}

	function getTypeLabel(type: NotificationType): string {
		switch (type) {
			case 'injection':
				return 'Message';
			case 'mention':
				return 'Mention';
			case 'agent_completed':
				return 'Completed';
			case 'invitation':
				return 'Invitation';
			case 'share':
				return 'Shared';
			default:
				return 'Notification';
		}
	}
</script>

<svelte:window
	onclick={(e) => {
		const target = e.target as HTMLElement;
		if (open && !target.closest('[data-notification-center]')) {
			closePanel();
		}
	}}
/>

<div class="relative" data-notification-center>
	<!-- Bell trigger button -->
	<button
		onclick={toggle}
		class="flex w-full items-center gap-2.5 rounded-[var(--radius-lg)] px-2.5 py-1.5 text-[14px] text-foreground transition-colors duration-150 hover:bg-surface-2"
		aria-label="Notifications"
		aria-expanded={open}
		aria-haspopup="true"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			width="16"
			height="16"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<path d="M6 8a6 6 0 0112 0c0 7 3 9 3 9H3s3-2 3-9" />
			<path d="M10.3 21a1.94 1.94 0 003.4 0" />
		</svg>
		<span>Notifications</span>
		{#if unread > 0}
			<span
				class="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[10px] font-medium leading-none text-white"
				data-testid="notification-badge"
			>
				{unread > 99 ? '99+' : unread}
			</span>
		{/if}
	</button>

	<!-- Dropdown panel -->
	{#if open}
		<!-- svelte-ignore a11y_interactive_supports_focus -->
		<div
			class="absolute bottom-full left-0 z-50 mb-2 w-[340px] max-w-[calc(100vw-2rem)] animate-[dropdownIn_0.15s_ease-out] rounded-[var(--radius-xl)] border border-border-subtle bg-surface-2 shadow-xl"
			role="dialog"
			aria-label="Notification center"
			onkeydown={handleKeydown}
		>
			<!-- Header -->
			<div class="flex items-center justify-between border-b border-border-subtle px-4 py-3">
				<div class="flex items-center gap-2">
					<h2 class="text-[14px] font-medium text-foreground">Notifications</h2>
					{#if unread > 0}
						<span
							class="flex h-5 min-w-5 items-center justify-center rounded-full bg-accent/10 px-1.5 text-[11px] font-medium text-accent"
						>
							{unread}
						</span>
					{/if}
				</div>
				{#if unread > 0}
					<button
						onclick={handleMarkAllRead}
						class="rounded-[var(--radius-md)] px-2 py-1 text-xs font-medium text-accent transition-all duration-200 hover:bg-accent/[0.06]"
					>
						Mark all as read
					</button>
				{/if}
			</div>

			<!-- Notification list -->
			<div class="max-h-[420px] overflow-y-auto">
				{#if items.length === 0}
					<div class="flex flex-col items-center gap-3 px-4 py-12 text-center">
						<div
							class="flex h-12 w-12 items-center justify-center rounded-[var(--radius-xl)] bg-surface-2"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="24"
								height="24"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
								class="text-muted"
							>
								<path d="M6 8a6 6 0 0112 0c0 7 3 9 3 9H3s3-2 3-9" />
								<path d="M10.3 21a1.94 1.94 0 003.4 0" />
							</svg>
						</div>
						<div>
							<p class="text-[14px] font-medium text-subtle">No notifications yet</p>
							<p class="mt-0.5 text-xs text-muted">We'll let you know when something arrives</p>
						</div>
					</div>
				{:else}
					{#each items as notification (notification.id)}
						{@const isUnread = !notification.read}
						<!-- eslint-disable svelte/no-navigation-without-resolve -->
						<a
							href={notification.href ?? '#'}
							class="group relative flex items-start gap-3 px-4 py-3.5 transition-colors duration-150 hover:bg-surface-2 {isUnread
								? 'bg-accent/[0.02]'
								: ''}"
							onclick={() => handleNotificationClick(notification)}
							data-testid="notification-item"
						>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->

							<!-- Unread indicator bar -->
							{#if isUnread}
								<div
									class="absolute top-0 left-0 h-full w-0.5 bg-accent"
									data-testid="unread-indicator"
								></div>
							{/if}

							<!-- Icon with colored background -->
							<div
								class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-lg)] {getIconBgColor(
									notification.type
								)}"
							>
								<span class={getTypeColor(notification.type)}>
									{#if notification.type === 'injection'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="16"
											height="16"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
										>
											<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
										</svg>
									{:else if notification.type === 'mention'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="16"
											height="16"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
										>
											<circle cx="12" cy="12" r="4" />
											<path d="M16 8v5a3 3 0 006 0v-1a10 10 0 10-3.92 7.94" />
										</svg>
									{:else if notification.type === 'agent_completed'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="16"
											height="16"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
										>
											<path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
											<polyline points="22 4 12 14.01 9 11.01" />
										</svg>
									{:else if notification.type === 'invitation'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="16"
											height="16"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
										>
											<rect x="2" y="4" width="20" height="16" rx="2" />
											<path d="m22 7-8.97 5.7a1.94 1.94 0 01-2.06 0L2 7" />
										</svg>
									{:else if notification.type === 'share'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											width="16"
											height="16"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"
										>
											<circle cx="18" cy="5" r="3" />
											<circle cx="6" cy="12" r="3" />
											<circle cx="18" cy="19" r="3" />
											<line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
											<line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
										</svg>
									{/if}
								</span>
							</div>

							<!-- Content -->
							<div class="min-w-0 flex-1">
								<div class="flex items-start justify-between gap-2">
									<p
										class="text-[13px] leading-snug {isUnread
											? 'font-medium text-foreground'
											: 'font-medium text-foreground'}"
									>
										{notification.title}
									</p>
								</div>
								<p class="mt-0.5 text-xs leading-relaxed text-muted">
									{notification.description}
								</p>
								<div class="mt-1.5 flex items-center gap-2">
									<Badge variant={getTypeBadgeVariant(notification.type)}
										>{getTypeLabel(notification.type)}</Badge
									>
									<span class="text-[11px] text-muted">
										{formatRelativeTime(notification.timestamp)}
									</span>
								</div>
							</div>
						</a>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>
