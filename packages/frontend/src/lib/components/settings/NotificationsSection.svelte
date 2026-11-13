<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getNotificationPreferences,
		updateNotificationPreferences,
		type PreferenceItem,
		type BackendNotificationType
	} from '$api/notifications';
	import { enterpriseMode } from '$stores/enterprise';
	import { getActiveOrg } from '$api/organizations';
	import { getSlackIntegration, getDiscordIntegration } from '$api/organizations';

	let preferences: PreferenceItem[] = $state([]);
	let loading = $state(true);
	let saving = $state(false);
	let hasSlack = $state(false);
	let hasDiscord = $state(false);
	let isEnterprise = $state(false);

	enterpriseMode.subscribe((v) => (isEnterprise = v));

	const TYPE_LABELS: Record<BackendNotificationType, { label: string; description: string }> = {
		injection: {
			label: 'Message Injections',
			description: 'When a teammate injects a message into your conversation'
		},
		mention: {
			label: 'Mentions',
			description: 'When someone mentions you in a conversation'
		},
		agent_completed: {
			label: 'Agent Completed',
			description: 'When an agent finishes running a task'
		},
		invitation: {
			label: 'Invitations',
			description: 'When you receive an organization invitation'
		},
		share: {
			label: 'Project Sharing',
			description: 'When someone shares a project or conversation with you'
		}
	};

	const CHANNELS: {
		key: keyof Pick<PreferenceItem, 'in_app' | 'email' | 'push'>;
		label: string;
	}[] = [
		{ key: 'in_app', label: 'In-app' },
		{ key: 'email', label: 'Email' },
		{ key: 'push', label: 'Push' }
	];

	const INTEGRATION_CHANNELS: {
		key: keyof Pick<PreferenceItem, 'slack' | 'discord'>;
		label: string;
	}[] = [
		{ key: 'slack', label: 'Slack' },
		{ key: 'discord', label: 'Discord' }
	];

	async function loadPreferences(): Promise<void> {
		loading = true;
		try {
			const resp = await getNotificationPreferences();
			preferences = resp.preferences;
		} catch {
			// Will show empty state
		} finally {
			loading = false;
		}
	}

	async function checkIntegrations(): Promise<void> {
		if (!isEnterprise) return;
		try {
			const activeOrg = await getActiveOrg();
			if (!activeOrg.organization_id) return;
			const orgId = activeOrg.organization_id;

			try {
				const slack = await getSlackIntegration(orgId);
				hasSlack = slack.is_active;
			} catch {
				hasSlack = false;
			}

			try {
				const discord = await getDiscordIntegration(orgId);
				hasDiscord = discord.is_active;
			} catch {
				hasDiscord = false;
			}
		} catch {
			// No active org
		}
	}

	async function handleToggle(
		notificationType: string,
		channel: string,
		checked: boolean
	): Promise<void> {
		// Optimistic update
		preferences = preferences.map((p) =>
			p.notification_type === notificationType ? { ...p, [channel]: checked } : p
		);

		saving = true;
		try {
			await updateNotificationPreferences([
				{ notification_type: notificationType, [channel]: checked }
			]);
		} catch {
			// Revert
			preferences = preferences.map((p) =>
				p.notification_type === notificationType ? { ...p, [channel]: !checked } : p
			);
		} finally {
			saving = false;
		}
	}

	onMount(() => {
		loadPreferences();
		checkIntegrations();
	});
</script>

<div class="space-y-5">
	<section>
		<div>
			<h3 class="text-sm font-medium text-foreground">Notification Preferences</h3>
			<p class="text-xs text-muted">Choose how you'd like to be notified for each event type.</p>
		</div>

		{#if loading}
			<div class="mt-4 flex items-center justify-center py-8">
				<svg
					class="h-5 w-5 animate-spin text-muted"
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
				>
					<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
					></circle>
					<path
						class="opacity-75"
						fill="currentColor"
						d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
					></path>
				</svg>
			</div>
		{:else}
			<div class="mt-4 space-y-1">
				{#each preferences as pref (pref.notification_type)}
					{@const info = TYPE_LABELS[pref.notification_type as BackendNotificationType]}
					{#if info}
						<div class="rounded-lg px-3 py-3">
							<div class="mb-2">
								<span class="text-sm font-medium text-foreground">{info.label}</span>
								<p class="mt-0.5 text-xs text-muted">{info.description}</p>
							</div>
							<div class="flex flex-wrap gap-x-5 gap-y-2">
								{#each CHANNELS as channel (channel.key)}
									<label
										for="pref-{pref.notification_type}-{channel.key}"
										class="flex cursor-pointer items-center gap-2"
									>
										<div class="relative shrink-0">
											<input
												id="pref-{pref.notification_type}-{channel.key}"
												type="checkbox"
												role="switch"
												checked={pref[channel.key]}
												onchange={(e: Event) =>
													handleToggle(
														pref.notification_type,
														channel.key,
														(e.target as HTMLInputElement).checked
													)}
												aria-checked={pref[channel.key]}
												class="peer sr-only"
												disabled={saving}
											/>
											<div
												class="h-5 w-9 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
											></div>
											<div
												class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-4"
											></div>
										</div>
										<span class="text-xs text-subtle">{channel.label}</span>
									</label>
								{/each}

								{#if isEnterprise && hasSlack}
									<label
										for="pref-{pref.notification_type}-slack"
										class="flex cursor-pointer items-center gap-2"
									>
										<div class="relative shrink-0">
											<input
												id="pref-{pref.notification_type}-slack"
												type="checkbox"
												role="switch"
												checked={pref.slack}
												onchange={(e: Event) =>
													handleToggle(
														pref.notification_type,
														'slack',
														(e.target as HTMLInputElement).checked
													)}
												aria-checked={pref.slack}
												class="peer sr-only"
												disabled={saving}
											/>
											<div
												class="h-5 w-9 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
											></div>
											<div
												class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-4"
											></div>
										</div>
										<span class="text-xs text-subtle">Slack</span>
									</label>
								{/if}

								{#if isEnterprise && hasDiscord}
									<label
										for="pref-{pref.notification_type}-discord"
										class="flex cursor-pointer items-center gap-2"
									>
										<div class="relative shrink-0">
											<input
												id="pref-{pref.notification_type}-discord"
												type="checkbox"
												role="switch"
												checked={pref.discord}
												onchange={(e: Event) =>
													handleToggle(
														pref.notification_type,
														'discord',
														(e.target as HTMLInputElement).checked
													)}
												aria-checked={pref.discord}
												class="peer sr-only"
												disabled={saving}
											/>
											<div
												class="h-5 w-9 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
											></div>
											<div
												class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-4"
											></div>
										</div>
										<span class="text-xs text-subtle">Discord</span>
									</label>
								{/if}
							</div>
						</div>
					{/if}
				{/each}
			</div>
		{/if}
	</section>
</div>
