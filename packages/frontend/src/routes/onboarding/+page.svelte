<script lang="ts">
	import { goto } from '$app/navigation';
	import { onDestroy, onMount } from 'svelte';
	import { fetchCurrentUser } from '$api/auth';
	import { get } from 'svelte/store';
	import { authToken, currentUser } from '$stores/auth';
	import { saveSettingsImmediately } from '$stores/settings';
	import { updateUser } from '$api/auth';
	import {
		listOrganizations,
		createOrganization,
		createInvitation,
		type Organization
	} from '$api/organizations';
	import { toasts } from '$stores/toast';
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';
	import Textarea from '$lib/components/ui/Textarea.svelte';
	import Select from '$lib/components/ui/Select.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import { getUserConsent, updateUserConsent } from '$api/compliance';
	import { getUserSubscription } from '$api/billing';
	import type { UserSubscription } from '$api/types';

	type UsageMode = 'personal' | 'team';
	type RoleType = 'viewer' | 'member' | 'admin';
	type Step =
		| 'name'
		| 'topics'
		| 'usage'
		| 'profile'
		| 'team'
		| 'orgCompliance'
		| 'invite'
		| 'compliance'
		| 'plan'
		| 'review';

	interface ConsentType {
		id: string;
		label: string;
		description: string;
		required: boolean;
		version: string;
	}

	const CONSENT_TYPES: ConsentType[] = [
		{
			id: 'data_processing',
			label: 'Data processing',
			description: 'Required — we need this to run the service and store your work.',
			required: true,
			version: '1.0'
		},
		{
			id: 'marketing',
			label: 'Marketing communications',
			description: 'Product updates, release notes, occasional announcements.',
			required: false,
			version: '1.0'
		},
		{
			id: 'analytics',
			label: 'Product analytics',
			description: 'Anonymous usage data that helps us improve the product.',
			required: false,
			version: '1.0'
		}
	];
	interface TopicOption {
		id: string;
		label: string;
		icon: string;
	}

	const topicOptions: TopicOption[] = [
		{ id: 'coding', label: 'Coding & developing', icon: '</>' },
		{ id: 'learning', label: 'Learning & studying', icon: '[]' },
		{ id: 'writing', label: 'Writing & content creation', icon: '✎' },
		{ id: 'business', label: 'Business & strategy', icon: '↗' },
		{ id: 'design', label: 'Design & creativity', icon: '◇' },
		{ id: 'life', label: 'Life stuff', icon: '☕' },
		{ id: 'choice', label: "Agent's choice", icon: '○' }
	];

	const roleOptions: { value: RoleType; label: string }[] = [
		{ value: 'viewer', label: 'Viewer' },
		{ value: 'member', label: 'Member' },
		{ value: 'admin', label: 'Admin' }
	];

	let currentUserId = $state<string | null>(null);
	let enterpriseEnabled = $state(false);

	let preferredName = $state('');
	let selectedTopics = $state<string[]>([]);
	let usageMode = $state<UsageMode>('personal');
	let roleTitle = $state('');
	let focusArea = $state('');
	let workStyle = $state('');

	let organizationName = $state('');
	let organizationId = $state<string | null>(null);
	let existingOrganizations = $state<Organization[]>([]);
	let usingExistingOrganization = $state(false);

	let inviteEmail = $state('');
	let inviteRole = $state<RoleType>('member');
	let invitedMembers = $state<{ email: string; role: RoleType }[]>([]);

	let loadingOrganizations = $state(false);
	let creatingOrganization = $state(false);
	let sendingInvite = $state(false);
	let finishing = $state(false);
	let orgsLoaded = $state(false);

	let consents = $state<Record<string, boolean>>({
		data_processing: true,
		marketing: false,
		analytics: true
	});
	let retentionAcknowledged = $state(false);
	let mfaInterest = $state<'now' | 'later' | null>(null);

	let orgRetentionDays = $state(365);
	let enableAuditExport = $state(false);

	let currentSubscription = $state<UserSubscription | null>(null);
	let subscriptionLoading = $state(false);

	let isEnterpriseEntry = $state(false);
	let stepIndex = $state(0);

	const steps = $derived.by(() => {
		const flow: Step[] = ['name', 'topics', 'usage', 'profile'];
		if (usageMode === 'team') {
			flow.push('team', 'orgCompliance', 'invite');
		}
		flow.push('compliance', 'plan', 'review');
		return flow;
	});

	const requiredConsentsSatisfied = $derived(
		CONSENT_TYPES.filter((c) => c.required).every((c) => consents[c.id])
	);

	const currentStep = $derived(steps[Math.min(stepIndex, steps.length - 1)] ?? 'review');
	const canGoBack = $derived(stepIndex > 0 && !finishing);
	const canGoNext = $derived.by(() => {
		if (finishing || creatingOrganization || sendingInvite) return false;
		if (currentStep === 'name') return preferredName.trim().length > 1;
		if (currentStep === 'topics') return selectedTopics.length === 3;
		if (currentStep === 'usage') return usageMode === 'personal' || enterpriseEnabled;
		if (currentStep === 'team') {
			if (!enterpriseEnabled) return true;
			if (usingExistingOrganization) return organizationId !== null;
			return organizationName.trim().length > 1;
		}
		if (currentStep === 'orgCompliance') {
			return orgRetentionDays >= 30 && orgRetentionDays <= 3650;
		}
		if (currentStep === 'compliance') {
			return requiredConsentsSatisfied && retentionAcknowledged;
		}
		return true;
	});

	const stepMeta = $derived.by(() => {
		switch (currentStep) {
			case 'name':
				return {
					title: 'Before we get started, what should I call you?',
					description: 'This helps personalize your workspace.'
				};
			case 'topics':
				return {
					title: `What are you into, ${preferredName || 'there'}? Pick three topics to explore.`,
					description: 'Choose the areas you want Jatayu AI to lean into.'
				};
			case 'usage':
				return {
					title: 'How are you planning to use Jatayu AI?',
					description: 'You can change this later in settings.'
				};
			case 'profile':
				return {
					title: 'A few details to tune your assistant',
					description: 'All fields are optional — skip anything that does not apply.'
				};
			case 'team':
				return {
					title: "Let's set up your team",
					description: 'Pick an existing organization or create a new one.'
				};
			case 'orgCompliance':
				return {
					title: 'Organization compliance defaults',
					description: 'Set initial retention and audit policies — you can adjust these later.'
				};
			case 'invite':
				return {
					title: 'Invite teammates',
					description: 'Optional — you can invite people later from settings.'
				};
			case 'compliance':
				return {
					title: 'Privacy & compliance',
					description: 'Review how we handle your data. Required items are marked.'
				};
			case 'plan':
				return {
					title: 'Your plan',
					description: 'Here is what is active on your account right now.'
				};
			case 'review':
				return {
					title: 'Everything looks good?',
					description: 'Confirm your choices and jump into Jatayu AI.'
				};
		}
	});

	const selectedTopicLabels = $derived(
		topicOptions.filter((topic) => selectedTopics.includes(topic.id)).map((topic) => topic.label)
	);

	const unsubscribe = currentUser.subscribe((user) => {
		if (!user) return;
		currentUserId = user.id;
		enterpriseEnabled = user.enterprise_mode;
		if (!preferredName && user.name) {
			preferredName = user.name;
		}
	});

	onDestroy(() => unsubscribe());

	onMount(async () => {
		if (get(authToken) && !get(currentUser)) {
			try {
				await fetchCurrentUser();
			} catch {
				// Leave enterprise mode disabled and let the route render its fallback UI.
			}
		}

		const params = new URLSearchParams(window.location.search);
		if (
			params.get('flow') === 'enterprise' ||
			params.get('enterprise') === '1' ||
			window.location.pathname.includes('/onboarding/enterprise')
		) {
			usageMode = 'team';
			isEnterpriseEntry = true;
		}

		void loadExistingConsents();
		void loadCurrentSubscription();
	});

	async function loadExistingConsents(): Promise<void> {
		try {
			const status = await getUserConsent();
			for (const type of CONSENT_TYPES) {
				const entry = status[type.id];
				if (entry?.action) {
					consents[type.id] = entry.action === 'granted';
				}
			}
		} catch {
			// Keep defaults — user has not recorded consent yet.
		}
	}

	async function loadCurrentSubscription(): Promise<void> {
		subscriptionLoading = true;
		try {
			currentSubscription = await getUserSubscription({ skipErrorHandling: true });
		} catch {
			currentSubscription = null;
		} finally {
			subscriptionLoading = false;
		}
	}

	$effect(() => {
		if (!enterpriseEnabled || orgsLoaded) return;

		void (async () => {
			loadingOrganizations = true;
			try {
				existingOrganizations = await listOrganizations();
				if (existingOrganizations.length > 0) {
					organizationId = existingOrganizations[0].id;
					organizationName = existingOrganizations[0].name;
					usingExistingOrganization = true;
				}
				orgsLoaded = true;
			} catch {
				// keep defaults
			} finally {
				loadingOrganizations = false;
			}
		})();
	});

	$effect(() => {
		if (stepIndex > steps.length - 1) {
			stepIndex = steps.length - 1;
		}
	});

	function toggleTopic(topicId: string): void {
		if (selectedTopics.includes(topicId)) {
			selectedTopics = selectedTopics.filter((id) => id !== topicId);
			return;
		}

		if (selectedTopics.length >= 3) {
			toasts.info('Pick up to three topics.');
			return;
		}
		selectedTopics = [...selectedTopics, topicId];
	}

	function goBack(): void {
		if (!canGoBack) return;
		stepIndex -= 1;
	}

	function buildInstructions(): string {
		const lines: string[] = [];
		if (workStyle.trim()) lines.push(workStyle.trim());
		if (selectedTopicLabels.length > 0) {
			lines.push(`Primary interests: ${selectedTopicLabels.join(', ')}.`);
		}
		if (usageMode === 'team') {
			lines.push('Prefer collaboration-friendly output with clear ownership and execution steps.');
		}
		return lines.join('\n');
	}

	async function ensureOrganization(): Promise<boolean> {
		if (usageMode !== 'team' || !enterpriseEnabled) return true;
		if (usingExistingOrganization && organizationId) return true;
		if (!organizationName.trim()) return false;

		creatingOrganization = true;
		try {
			const org = await createOrganization({
				name: organizationName.trim()
			});
			organizationId = org.id;
			organizationName = org.name;
			toasts.success('Team created.');
			return true;
		} catch (error: unknown) {
			const err = error as { message?: string };
			toasts.error(err.message || 'Failed to create organization.');
			return false;
		} finally {
			creatingOrganization = false;
		}
	}

	async function handleAddInvite(): Promise<void> {
		if (!inviteEmail.trim()) return;

		const email = inviteEmail.trim().toLowerCase();
		const alreadyInvited = invitedMembers.some((member) => member.email.toLowerCase() === email);
		if (alreadyInvited) {
			toasts.info('This teammate is already in the list.');
			return;
		}

		if (!organizationId || !enterpriseEnabled) {
			invitedMembers = [...invitedMembers, { email, role: inviteRole }];
			inviteEmail = '';
			return;
		}

		sendingInvite = true;
		try {
			await createInvitation(organizationId, { email, role: inviteRole });
			invitedMembers = [...invitedMembers, { email, role: inviteRole }];
			inviteEmail = '';
			toasts.success('Invitation sent.');
		} catch (error: unknown) {
			const err = error as { message?: string };
			toasts.error(err.message || 'Failed to send invitation.');
		} finally {
			sendingInvite = false;
		}
	}

	async function handleNext(): Promise<void> {
		if (!canGoNext) return;

		if (currentStep === 'team') {
			const ok = await ensureOrganization();
			if (!ok) return;
		}

		if (currentStep === 'review') {
			await finishOnboarding();
			return;
		}

		stepIndex += 1;
	}

	function persistMfaChoice(): void {
		if (typeof localStorage === 'undefined') return;
		if (mfaInterest === 'now') {
			localStorage.setItem('midsphere-mfa-prompt-after', String(Date.now()));
			localStorage.removeItem('midsphere-mfa-dismissed');
		} else if (mfaInterest === 'later') {
			localStorage.setItem('midsphere-mfa-dismissed', '1');
			localStorage.removeItem('midsphere-mfa-prompt-after');
		}
	}

	async function persistConsents(): Promise<void> {
		for (const type of CONSENT_TYPES) {
			try {
				await updateUserConsent({
					consent_type: type.id,
					action: consents[type.id] ? 'granted' : 'revoked',
					version: type.version
				});
			} catch {
				// Individual consent failures should not block finishing onboarding.
			}
		}
	}

	async function finishOnboarding(): Promise<void> {
		if (finishing) return;
		finishing = true;
		try {
			if (currentUserId && preferredName.trim()) {
				await updateUser(
					currentUserId,
					{ user_name: preferredName.trim() },
					{ skipErrorHandling: true }
				);
			}

			await persistConsents();
			persistMfaChoice();

			await saveSettingsImmediately({
				nickname: preferredName.trim(),
				occupation: roleTitle.trim(),
				about_you: focusArea.trim(),
				custom_instructions: buildInstructions(),
				onboarding_completed: true
			});

			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto('/');
		} catch {
			toasts.error('Failed to finish onboarding. Please try again.');
			finishing = false;
		}
	}

	function onInviteInputKeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter') {
			event.preventDefault();
			handleAddInvite();
		}
	}

	function onNameKeydown(event: KeyboardEvent): void {
		if (event.key === 'Enter') {
			event.preventDefault();
			handleNext();
		}
	}
</script>

<svelte:head>
	<title>Welcome — Jatayu AI</title>
</svelte:head>

<main class="min-h-[100dvh] bg-background text-foreground">
	<div class="mx-auto flex min-h-[100dvh] w-full max-w-2xl flex-col px-5 py-8 sm:px-8">
		<header class="flex items-center justify-between">
			<a href="/" class="flex items-center" aria-label="Jatayu AI">
				<img
					src="/logos/logo-black.png"
					alt="Jatayu AI"
					class="logo-light h-7 w-auto"
					style="filter: drop-shadow(0 0 0.8px rgba(0,0,0,0.8))"
				/>
				<img
					src="/logos/logo-white.png"
					alt="Jatayu AI"
					class="logo-dark h-7 w-auto"
					style="filter: drop-shadow(0 0 0.8px rgba(255,255,255,0.8))"
				/>
			</a>
			<div class="flex items-center gap-1.5" aria-label="Onboarding progress">
				{#each steps as _, i (i)}
					<span
						class="h-1.5 rounded-full transition-all duration-200 {i === stepIndex
							? 'bg-foreground w-6'
							: i < stepIndex
								? 'bg-foreground/60 w-1.5'
								: 'bg-border-strong w-1.5'}"
						aria-hidden="true"
					></span>
				{/each}
				<span class="sr-only">Step {stepIndex + 1} of {steps.length}</span>
			</div>
		</header>

		<section class="mt-12 flex flex-1 flex-col sm:mt-16" aria-live="polite">
			<div class="mb-8 text-center">
				<h1 class="font-display text-3xl leading-tight sm:text-4xl">
					{stepMeta.title}
				</h1>
				{#if stepMeta.description}
					<p class="text-muted mt-3 text-sm">{stepMeta.description}</p>
				{/if}
			</div>

			<div class="flex-1">
				{#if currentStep === 'name'}
					<div class="mx-auto flex w-full max-w-md items-start gap-2">
						<div class="flex-1">
							<Input
								bind:value={preferredName}
								placeholder="Enter your name"
								autocomplete="name"
								onkeydown={onNameKeydown}
							/>
						</div>
						<button
							type="button"
							class="bg-foreground text-background flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-xl text-lg transition-opacity duration-200 hover:opacity-80 disabled:pointer-events-none disabled:opacity-40"
							onclick={handleNext}
							disabled={!canGoNext}
						>
							↗
						</button>
					</div>
				{/if}

				{#if currentStep === 'topics'}
					<div class="flex flex-wrap justify-center gap-2.5">
						{#each topicOptions as topic (topic.id)}
							{@const active = selectedTopics.includes(topic.id)}
							<button
								type="button"
								class="inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-sm transition-all duration-150 {active
									? 'border-accent bg-accent/10 text-foreground'
									: 'border-border-subtle bg-surface-2 text-foreground hover:border-border-strong'}"
								onclick={() => toggleTopic(topic.id)}
								aria-pressed={active}
							>
								<span class="text-muted font-mono text-xs">{topic.icon}</span>
								<span>{topic.label}</span>
							</button>
						{/each}
					</div>
					<p class="text-muted mt-5 text-center text-xs">{selectedTopics.length}/3 selected</p>
				{/if}

				{#if currentStep === 'usage'}
					<div class="grid gap-3 sm:grid-cols-2">
						<button
							type="button"
							class="rounded-xl border p-5 text-left transition-all duration-150 {usageMode ===
							'personal'
								? 'border-accent bg-accent/10'
								: 'border-border-subtle bg-surface-2 hover:border-border-strong'}"
							onclick={() => (usageMode = 'personal')}
						>
							<div class="font-display text-xl leading-tight">For personal use</div>
							<p class="text-muted mt-2 text-sm leading-snug">
								For individuals building and experimenting with their own projects.
							</p>
						</button>
						<button
							type="button"
							class="rounded-xl border p-5 text-left transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-50 {usageMode ===
							'team'
								? 'border-accent bg-accent/10'
								: 'border-border-subtle bg-surface-2 hover:border-border-strong'}"
							onclick={() => (usageMode = 'team')}
							disabled={!enterpriseEnabled}
						>
							<div class="font-display text-xl leading-tight">With my team</div>
							<p class="text-muted mt-2 text-sm leading-snug">
								For organizations collaborating across shared workspaces.
							</p>
						</button>
					</div>
					{#if !enterpriseEnabled}
						<p class="text-muted mt-4 text-center text-xs">
							Team mode becomes available after enabling enterprise mode.
						</p>
					{/if}
				{/if}

				{#if currentStep === 'profile'}
					<div class="mx-auto flex w-full max-w-lg flex-col gap-4">
						<Input
							label="What do you do?"
							bind:value={roleTitle}
							placeholder="Engineer, founder, student..."
						/>
						<Textarea
							label="What are you working on?"
							bind:value={focusArea}
							rows={3}
							placeholder="Current project or goal"
						/>
						<Textarea
							label="How should the assistant respond?"
							bind:value={workStyle}
							rows={3}
							placeholder="Be concise, include tradeoffs, prioritize code-first answers..."
						/>
					</div>
				{/if}

				{#if currentStep === 'team'}
					<div class="mx-auto w-full max-w-lg">
						{#if loadingOrganizations}
							<p class="text-muted text-center text-sm">Loading your organizations…</p>
						{:else if !enterpriseEnabled}
							<p class="text-muted text-center text-sm">
								Enterprise mode is off. Continue and enable it later.
							</p>
						{:else if existingOrganizations.length > 0}
							<Select
								label="Choose organization"
								value={organizationId ?? ''}
								onchange={(e) => {
									const id = (e.target as HTMLSelectElement).value;
									organizationId = id;
									const selected = existingOrganizations.find((org) => org.id === id);
									if (selected) {
										organizationName = selected.name;
										usingExistingOrganization = true;
									}
								}}
							>
								{#each existingOrganizations as org (org.id)}
									<option value={org.id}>{org.name}</option>
								{/each}
							</Select>
						{:else}
							<Input label="Team name" bind:value={organizationName} placeholder="Jatayu AI" />
						{/if}
					</div>
				{/if}

				{#if currentStep === 'orgCompliance'}
					<div class="mx-auto flex w-full max-w-lg flex-col gap-4">
						<div class="border-border-subtle bg-surface-2 rounded-xl border p-5">
							<label for="retention-days" class="text-foreground block text-sm font-medium">
								Default data retention
							</label>
							<p class="text-muted mt-1 text-xs">
								How long audit logs and conversation archives are kept before cleanup (30–3650
								days).
							</p>
							<div class="mt-3 flex items-center gap-3">
								<input
									id="retention-days"
									type="number"
									min="30"
									max="3650"
									bind:value={orgRetentionDays}
									class="border-border-subtle bg-background text-foreground focus:border-border-strong w-32 rounded-xl border px-4 py-2.5 text-sm outline-none"
								/>
								<span class="text-muted text-xs">days</span>
							</div>
						</div>
						<div class="border-border-subtle bg-surface-2 rounded-xl border p-5">
							<Checkbox
								bind:checked={enableAuditExport}
								label="Enable scheduled audit log exports"
							/>
							<p class="text-muted mt-2 ml-7 text-xs">
								Audit logs are streamed to your configured destination on a schedule. You can
								configure destinations under Settings → Compliance after setup.
							</p>
						</div>
					</div>
				{/if}

				{#if currentStep === 'invite'}
					<div class="mx-auto w-full max-w-lg">
						<div class="grid gap-2 sm:grid-cols-[minmax(0,1fr)_140px_auto]">
							<Input
								type="email"
								bind:value={inviteEmail}
								placeholder="teammate@company.com"
								onkeydown={onInviteInputKeydown}
							/>
							<Select bind:value={inviteRole}>
								{#each roleOptions as role (role.value)}
									<option value={role.value}>{role.label}</option>
								{/each}
							</Select>
							<Button
								variant="primary"
								onclick={handleAddInvite}
								disabled={sendingInvite || !inviteEmail.trim()}
							>
								{sendingInvite ? 'Adding…' : 'Add'}
							</Button>
						</div>
						{#if invitedMembers.length > 0}
							<ul class="mt-4 flex flex-col gap-2">
								{#each invitedMembers as member, idx (`${member.email}-${idx}`)}
									<li
										class="border-border-subtle bg-surface-2 flex items-center justify-between rounded-xl border px-4 py-2.5 text-sm"
									>
										<span class="text-foreground">{member.email}</span>
										<span class="text-muted text-xs capitalize">{member.role}</span>
									</li>
								{/each}
							</ul>
						{/if}
					</div>
				{/if}

				{#if currentStep === 'compliance'}
					<div class="mx-auto flex w-full max-w-lg flex-col gap-3">
						{#each CONSENT_TYPES as type (type.id)}
							<label
								class="border-border-subtle bg-surface-2 hover:border-border-strong flex cursor-pointer gap-4 rounded-xl border p-4 transition-colors"
							>
								<input
									type="checkbox"
									bind:checked={consents[type.id]}
									disabled={type.required}
									class="border-border-strong bg-surface-2 checked:border-accent checked:bg-accent mt-0.5 h-[18px] w-[18px] shrink-0 cursor-pointer appearance-none rounded-md disabled:cursor-not-allowed disabled:opacity-60"
								/>
								<div class="flex-1">
									<div class="flex items-center gap-2">
										<span class="text-foreground text-sm font-medium">{type.label}</span>
										{#if type.required}
											<span
												class="text-muted border-border-subtle rounded-full border px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
											>
												Required
											</span>
										{/if}
									</div>
									<p class="text-muted mt-1 text-xs leading-snug">{type.description}</p>
								</div>
							</label>
						{/each}

						<label
							class="border-border-subtle bg-surface-2 flex cursor-pointer gap-4 rounded-xl border p-4"
						>
							<input
								type="checkbox"
								bind:checked={retentionAcknowledged}
								class="border-border-strong bg-surface-2 checked:border-accent checked:bg-accent mt-0.5 h-[18px] w-[18px] shrink-0 cursor-pointer appearance-none rounded-md"
							/>
							<div class="flex-1">
								<span class="text-foreground text-sm font-medium">
									I acknowledge the data retention policy
								</span>
								<p class="text-muted mt-1 text-xs leading-snug">
									Conversation archives and audit logs are retained for the configured period, then
									deleted. Full details live in Settings → Compliance.
								</p>
							</div>
						</label>

						<div class="border-border-subtle bg-surface mt-2 rounded-xl border p-4">
							<div class="flex items-start gap-3">
								<span class="text-accent mt-0.5 text-lg leading-none">🛡</span>
								<div class="flex-1">
									<p class="text-foreground text-sm font-medium">Protect your account with MFA</p>
									<p class="text-muted mt-1 text-xs leading-snug">
										Two-factor authentication is strongly recommended. You can enable it now or
										later from Settings → Security.
									</p>
									<div class="mt-3 flex gap-2">
										<button
											type="button"
											class="rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors {mfaInterest ===
											'now'
												? 'border-accent bg-accent/10 text-foreground'
												: 'border-border-subtle text-muted hover:border-border-strong hover:text-foreground'}"
											onclick={() => (mfaInterest = 'now')}
										>
											Remind me after setup
										</button>
										<button
											type="button"
											class="rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors {mfaInterest ===
											'later'
												? 'border-accent bg-accent/10 text-foreground'
												: 'border-border-subtle text-muted hover:border-border-strong hover:text-foreground'}"
											onclick={() => (mfaInterest = 'later')}
										>
											I'll set it up later
										</button>
									</div>
								</div>
							</div>
						</div>
					</div>
				{/if}

				{#if currentStep === 'plan'}
					<div class="mx-auto flex w-full max-w-lg flex-col gap-4">
						<div class="border-border-subtle bg-surface-2 rounded-xl border p-5">
							{#if subscriptionLoading}
								<p class="text-muted text-sm">Loading plan details…</p>
							{:else if currentSubscription?.plan}
								<div class="flex items-start justify-between gap-4">
									<div>
										<p class="text-muted text-xs uppercase tracking-wide">Current plan</p>
										<p class="font-display mt-1 text-2xl leading-tight">
											{currentSubscription.plan.name}
										</p>
										<p class="text-muted mt-1 text-xs capitalize">
											{currentSubscription.status}
											{#if currentSubscription.plan.monthly_credits > 0}
												· {currentSubscription.plan.monthly_credits.toLocaleString()} credits / month
											{/if}
										</p>
									</div>
									{#if currentSubscription.plan.price > 0}
										<div class="text-right">
											<p class="font-display text-xl">${currentSubscription.plan.price}</p>
											<p class="text-muted text-xs">per month</p>
										</div>
									{/if}
								</div>
							{:else}
								<div>
									<p class="text-muted text-xs uppercase tracking-wide">Current plan</p>
									<p class="font-display mt-1 text-2xl leading-tight">Free</p>
									<p class="text-muted mt-1 text-xs">
										Enough to get started. Upgrade anytime for more credits and enterprise features.
									</p>
								</div>
							{/if}
						</div>
						<a
							href="/billing/plans"
							target="_blank"
							rel="noopener"
							class="border-border-subtle bg-surface-2 hover:border-border-strong flex items-center justify-between rounded-xl border p-4 text-sm transition-colors"
						>
							<div>
								<p class="text-foreground font-medium">View all plans</p>
								<p class="text-muted mt-0.5 text-xs">
									Compare tiers, features, and monthly credits (opens in a new tab).
								</p>
							</div>
							<span class="text-muted text-lg">↗</span>
						</a>
						{#if isEnterpriseEntry}
							<p class="text-muted text-center text-xs">
								Enterprise mode requires a paid plan to remain active.
							</p>
						{/if}
					</div>
				{/if}

				{#if currentStep === 'review'}
					<dl
						class="border-border-subtle bg-surface-2 mx-auto grid w-full max-w-lg gap-3 rounded-xl border p-5 text-sm"
					>
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Name</dt>
							<dd class="text-foreground text-right">{preferredName}</dd>
						</div>
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Topics</dt>
							<dd class="text-foreground text-right">{selectedTopicLabels.join(', ')}</dd>
						</div>
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Usage</dt>
							<dd class="text-foreground text-right">
								{usageMode === 'team' ? 'Team' : 'Personal'}
							</dd>
						</div>
						{#if roleTitle}
							<div class="flex justify-between gap-4">
								<dt class="text-muted">Role</dt>
								<dd class="text-foreground text-right">{roleTitle}</dd>
							</div>
						{/if}
						{#if focusArea}
							<div class="flex justify-between gap-4">
								<dt class="text-muted">Focus</dt>
								<dd class="text-foreground text-right">{focusArea}</dd>
							</div>
						{/if}
						{#if usageMode === 'team' && organizationName}
							<div class="flex justify-between gap-4">
								<dt class="text-muted">Team</dt>
								<dd class="text-foreground text-right">{organizationName}</dd>
							</div>
							<div class="flex justify-between gap-4">
								<dt class="text-muted">Retention</dt>
								<dd class="text-foreground text-right">{orgRetentionDays} days</dd>
							</div>
							{#if invitedMembers.length > 0}
								<div class="flex justify-between gap-4">
									<dt class="text-muted">Invites</dt>
									<dd class="text-foreground text-right">{invitedMembers.length} pending</dd>
								</div>
							{/if}
						{/if}
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Consents</dt>
							<dd class="text-foreground text-right">
								{CONSENT_TYPES.filter((t) => consents[t.id])
									.map((t) => t.label)
									.join(', ') || 'None'}
							</dd>
						</div>
						<div class="flex justify-between gap-4">
							<dt class="text-muted">Plan</dt>
							<dd class="text-foreground text-right">
								{currentSubscription?.plan?.name ?? 'Free'}
							</dd>
						</div>
					</dl>
				{/if}
			</div>

			{#if currentStep !== 'name'}
				<div class="mt-10 flex items-center justify-center gap-3">
					<Button variant="bordered" onclick={goBack} disabled={!canGoBack || finishing}>
						Back
					</Button>
					<Button variant="primary" onclick={handleNext} disabled={!canGoNext}>
						{#if currentStep === 'review'}
							{finishing ? 'Finishing…' : 'Continue'}
						{:else}
							Continue
						{/if}
					</Button>
				</div>
			{/if}
		</section>
	</div>
</main>
