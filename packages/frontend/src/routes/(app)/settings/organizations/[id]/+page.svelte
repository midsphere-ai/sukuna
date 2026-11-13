<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { goto } from '$app/navigation';
	import { toasts } from '$stores/toast';
	import { enterpriseMode } from '$stores/enterprise';
	import {
		getOrganization,
		listMembers,
		changeMemberRole,
		removeMember,
		leaveOrganization,
		listInvitations,
		createInvitation,
		createLinkInvitation,
		revokeInvitation,
		getSSOConfig,
		createSSOConfig,
		updateSSOConfig,
		deleteSSOConfig,
		getSPMetadata,
		getSlackIntegration,
		upsertSlackIntegration,
		deleteSlackIntegration,
		testSlackIntegration,
		getDiscordIntegration,
		upsertDiscordIntegration,
		deleteDiscordIntegration,
		testDiscordIntegration,
		listTemplates,
		createTemplate,
		updateTemplate,
		deleteTemplate,
		type Organization,
		type OrgMember,
		type Invitation,
		type SSOConfig,
		type SPMetadata,
		type WebhookIntegration,
		getIPAllowlist,
		addIPAllowlistEntry,
		removeIPAllowlistEntry,
		getAccessPolicies,
		createAccessPolicy,
		updateAccessPolicy,
		deleteAccessPolicy,
		type AccessPolicy,
		type AccessPolicyCondition,
		getModelPolicy,
		updateModelPolicy,
		type ModelPolicy,
		getAgentPolicy,
		updateAgentPolicy,
		type AgentPolicy,
		getAnalyticsSummary,
		getAnalyticsMembers,
		getAnalyticsProjects,
		exportAnalyticsMembersUrl,
		exportAnalyticsProjectsUrl,
		type ProjectTemplate,
		type TemplateFile,
		type IPAllowlistEntry,
		type IPAllowlistList,
		type AnalyticsSummary,
		type MemberAnalyticsEntry,
		type MemberAnalyticsPage,
		type ProjectAnalyticsEntry,
		type ProjectAnalyticsPage
	} from '$api/organizations';
	import { get } from 'svelte/store';
	import { authToken, currentUser } from '$stores/auth';
	import ScimTokensSection from '$lib/components/settings/org/ScimTokensSection.svelte';
	import DlpPolicySection from '$lib/components/settings/org/DlpPolicySection.svelte';
	import WebhooksTab from '$lib/components/settings/org/WebhooksTab.svelte';
	import ApiKeysTab from '$lib/components/settings/org/ApiKeysTab.svelte';
	import CostPolicySection from '$lib/components/settings/org/CostPolicySection.svelte';
	import SecurityPolicySection from '$lib/components/settings/org/SecurityPolicySection.svelte';
	import ForceLogoutSection from '$lib/components/settings/org/ForceLogoutSection.svelte';
	import OrgLifecycleSection from '$lib/components/settings/org/OrgLifecycleSection.svelte';
	import IPAllowlistSection from '$lib/components/settings/org/IPAllowlistSection.svelte';
	import AccessPoliciesSection from '$lib/components/settings/org/AccessPoliciesSection.svelte';
	import SideNav from '$lib/components/ui/SideNav.svelte';

	type Tab =
		| 'members'
		| 'invitations'
		| 'sso'
		| 'security'
		| 'ip-allowlist'
		| 'access-policies'
		| 'integrations'
		| 'templates'
		| 'analytics'
		| 'webhooks'
		| 'api-keys'
		| 'billing'
		| 'general';
	let activeTab: Tab = $state('sso');

	const baseNavItems: { id: Tab; label: string }[] = [
		{ id: 'members', label: 'Members' },
		{ id: 'invitations', label: 'Invitations' },
		{ id: 'sso', label: 'SSO' },
		{ id: 'security', label: 'Security' },
		{ id: 'ip-allowlist', label: 'IP Allowlist' },
		{ id: 'access-policies', label: 'Access Policies' },
		{ id: 'integrations', label: 'Integrations' },
		{ id: 'templates', label: 'Templates' }
	];
	const adminNavItems: { id: Tab; label: string }[] = [
		{ id: 'analytics', label: 'Analytics' },
		{ id: 'webhooks', label: 'Webhooks' },
		{ id: 'api-keys', label: 'API Keys' },
		{ id: 'billing', label: 'Billing' },
		{ id: 'general', label: 'General' }
	];

	// Org state
	let org = $state<Organization | null>(null);
	let navItems = $derived(
		org?.your_role === 'admin' || org?.your_role === 'owner'
			? [...baseNavItems, ...adminNavItems]
			: baseNavItems
	);
	let members: OrgMember[] = $state([]);
	let loading = $state(true);

	// Member management state
	let confirmingRemoveId: string | null = $state(null);
	let removingMemberId: string | null = $state(null);
	let changingRoleId: string | null = $state(null);
	let leavingOrg = $state(false);
	let showLeaveConfirm = $state(false);

	// Current user info for self-action prevention
	const currentUserId = $derived($currentUser?.id ?? null);
	const myRole = $derived.by(() => {
		const o = org;
		return o ? o.your_role : null;
	});
	const canManageMembers = $derived(myRole === 'owner' || myRole === 'admin');

	// Invitation state
	let invitations: Invitation[] = $state([]);
	let invLoading = $state(true);
	let inviteEmail = $state('');
	let inviteRole = $state('member');
	let inviting = $state(false);
	let revokingId: string | null = $state(null);

	// Link invitation popover state
	let showLinkPopover = $state(false);
	let linkRole = $state('member');
	let linkExpiry = $state('7d');
	let linkMaxUses: string = $state('');
	let creatingLink = $state(false);
	let generatedLink: string | null = $state(null);
	let copiedLink = $state(false);

	// SSO state
	let ssoConfig: SSOConfig | null = $state(null);
	let spMetadata: SPMetadata | null = $state(null);
	let ssoLoading = $state(true);
	let ssoSaving = $state(false);

	// SSO form fields
	let providerType = $state('saml');
	let metadataUrl = $state('');
	let entityId = $state('');
	let certificate = $state('');
	let isActive = $state(false);
	let enforceSso = $state(false);
	let emergencyBypass = $state(false);

	// Test connection
	let testingConnection = $state(false);
	let testResult: { ok: boolean; message: string } | null = $state(null);

	// Confirm dialogs
	let showEnforceConfirm = $state(false);
	let showDeleteConfirm = $state(false);
	let deleting = $state(false);

	// Integration state
	let slackWebhookUrl = $state('');
	let slackChannelName = $state('');
	let slackActive = $state(true);
	let slackLoading = $state(true);
	let slackSaving = $state(false);
	let slackExists = $state(false);
	let slackTestResult: { ok: boolean; message: string } | null = $state(null);
	let slackTesting = $state(false);

	let discordWebhookUrl = $state('');
	let discordChannelName = $state('');
	let discordActive = $state(true);
	let discordLoading = $state(true);
	let discordSaving = $state(false);
	let discordExists = $state(false);
	let discordTestResult: { ok: boolean; message: string } | null = $state(null);
	let discordTesting = $state(false);

	// Template state
	let tmplList: ProjectTemplate[] = $state([]);
	let tmplLoading = $state(true);
	let tmplEditing: ProjectTemplate | null = $state(null);
	let tmplShowForm = $state(false);
	let tmplSaving = $state(false);
	let tmplDeletingId: string | null = $state(null);

	// Template form fields
	let tmplName = $state('');
	let tmplDescription = $state('');
	let tmplInstructions = $state('');
	let tmplIcon = $state('');
	let tmplFiles: TemplateFile[] = $state([]);

	// IP Allowlist state
	let ipEntries: IPAllowlistEntry[] = $state([]);
	let ipYourIp: string | null = $state(null);
	let ipLoading = $state(true);
	let ipAdding = $state(false);
	let ipRemovingId: string | null = $state(null);
	let ipCidr = $state('');
	let ipDescription = $state('');
	let ipShowLockoutWarning = $state(false);

	// Model Policy state
	let mpAllowedModels: string[] = $state([]);
	let mpAllowedProviders: string[] = $state([]);
	let mpBlockByom = $state(false);
	let mpLoading = $state(true);
	let mpSaving = $state(false);
	let mpNewModel = $state('');
	let mpNewProvider = $state('');

	// Agent Policy state
	let apBlockedTools: string[] = $state([]);
	let apBlockedToolGroups: string[] = $state([]);
	let apRequireHitlFor: string[] = $state([]);
	let apLoading = $state(true);
	let apSaving = $state(false);
	let apNewBlockedTool = $state('');
	let apNewHitlTool = $state('');

	const TOOL_GROUPS = ['file', 'shell', 'browse', 'search', 'media_gen', 'git_ops', 'perception'];

	// Access Policy state
	let capPolicies: AccessPolicy[] = $state([]);
	let capYourIp: string | null = $state(null);
	let capLoading = $state(true);
	let capSaving = $state(false);
	let capDeletingId: string | null = $state(null);
	let capShowForm = $state(false);
	let capEditingId: string | null = $state(null);
	// Form fields
	let capName = $state('');
	let capAction = $state('block');
	let capPriority = $state(0);
	let capIsActive = $state(true);
	let capConditions: AccessPolicyCondition[] = $state([]);
	// New condition form
	let capCondType = $state('ip_range');
	let capCondCidr = $state('');
	let capCondStartHour = $state(9);
	let capCondEndHour = $state(17);
	let capCondTimezone = $state('UTC');
	let capCondDays: number[] = $state([]);
	let capCondPattern = $state('');

	const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

	// Analytics state
	let analyticsSummary: AnalyticsSummary | null = $state(null);
	let analyticsMembers: MemberAnalyticsPage | null = $state(null);
	let analyticsProjects: ProjectAnalyticsPage | null = $state(null);
	let analyticsLoading = $state(true);
	let analyticsPeriod = $state('30d');
	let analyticsCustomStart = $state('');
	let analyticsCustomEnd = $state('');
	let memberPage = $state(1);
	let memberSortBy = $state('agent_runs_count');
	let memberSortOrder = $state('desc');
	let projectPage = $state(1);
	let projectSortBy = $state('agent_runs');
	let projectSortOrder = $state('desc');

	const orgId = $derived(page.params.id ?? '');

	function populateForm(config: SSOConfig): void {
		providerType = config.provider_type;
		metadataUrl = config.metadata_url;
		entityId = config.entity_id;
		certificate = config.certificate;
		isActive = config.is_active;
		enforceSso = config.enforce_sso;
		emergencyBypass = config.emergency_bypass_enabled ?? false;
	}

	function resetForm(): void {
		providerType = 'saml';
		metadataUrl = '';
		entityId = '';
		certificate = '';
		isActive = false;
		enforceSso = false;
		emergencyBypass = false;
	}

	async function loadOrg(): Promise<void> {
		try {
			org = await getOrganization(orgId);
		} catch {
			toasts.error('Failed to load organization.');
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto('/');
		}
	}

	async function loadMembers(): Promise<void> {
		try {
			members = await listMembers(orgId);
		} catch {
			// Non-critical — may not have permission
		}
	}

	function isCurrentUser(member: OrgMember): boolean {
		if (!currentUserId) return false;
		return String(member.user_id) === String(currentUserId);
	}

	function assignableRoles(): string[] {
		if (myRole === 'owner') return ['viewer', 'member', 'admin', 'owner'];
		if (myRole === 'admin') return ['viewer', 'member', 'admin'];
		return [];
	}

	async function handleChangeRole(member: OrgMember, newRole: string): Promise<void> {
		changingRoleId = member.id;
		try {
			const updated = await changeMemberRole(orgId, member.id, { role: newRole });
			// Update the member in the local array
			members = members.map((m) => (m.id === member.id ? { ...m, role: updated.role } : m));
			toasts.success(`Changed ${member.name || member.email}'s role to ${newRole}.`);
			// If we changed someone to owner, reload org to refresh our own role info
			if (newRole === 'owner') {
				await loadOrg();
			}
		} catch {
			// Error handled by API client
		} finally {
			changingRoleId = null;
		}
	}

	async function handleRemoveMember(member: OrgMember): Promise<void> {
		removingMemberId = member.id;
		try {
			await removeMember(orgId, member.id);
			members = members.filter((m) => m.id !== member.id);
			toasts.success(`Removed ${member.name || member.email} from the organization.`);
			confirmingRemoveId = null;
		} catch {
			// Error handled by API client
		} finally {
			removingMemberId = null;
		}
	}

	async function handleLeaveOrg(): Promise<void> {
		leavingOrg = true;
		try {
			await leaveOrganization(orgId);
			toasts.success(`You have left ${org?.name ?? 'the organization'}.`);
			showLeaveConfirm = false;
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			goto('/');
		} catch (err: unknown) {
			// The backend returns an error if the user is the last owner
			if (err && typeof err === 'object' && 'message' in err) {
				toasts.error(String((err as { message: string }).message));
			}
		} finally {
			leavingOrg = false;
		}
	}

	async function loadSSO(): Promise<void> {
		ssoLoading = true;
		try {
			ssoConfig = await getSSOConfig(orgId);
			populateForm(ssoConfig);
			// Load SP metadata if config exists
			try {
				spMetadata = await getSPMetadata(orgId);
			} catch {
				spMetadata = null;
			}
		} catch {
			// 404 = no SSO config yet — that's fine
			ssoConfig = null;
			spMetadata = null;
			resetForm();
		} finally {
			ssoLoading = false;
		}
	}

	async function loadInvitations(): Promise<void> {
		invLoading = true;
		try {
			invitations = await listInvitations(orgId);
		} catch {
			// Non-critical
		} finally {
			invLoading = false;
		}
	}

	async function handleSendInvite(): Promise<void> {
		if (!inviteEmail.trim()) return;
		inviting = true;
		try {
			await createInvitation(orgId, { email: inviteEmail.trim(), role: inviteRole });
			toasts.success(`Invitation sent to ${inviteEmail.trim()}.`);
			inviteEmail = '';
			inviteRole = 'member';
			await loadInvitations();
		} catch {
			// Error handled by API client
		} finally {
			inviting = false;
		}
	}

	async function handleRevokeInvitation(invId: string): Promise<void> {
		revokingId = invId;
		try {
			await revokeInvitation(invId);
			toasts.success('Invitation revoked.');
			invitations = invitations.filter((inv) => inv.id !== invId);
		} catch {
			// Error handled by API client
		} finally {
			revokingId = null;
		}
	}

	async function handleCreateLink(): Promise<void> {
		creatingLink = true;
		generatedLink = null;
		copiedLink = false;
		try {
			const maxUses = linkMaxUses.trim() ? parseInt(linkMaxUses, 10) : null;
			if (maxUses !== null && (isNaN(maxUses) || maxUses < 1)) {
				toasts.error('Max uses must be a positive number.');
				creatingLink = false;
				return;
			}
			const inv = await createLinkInvitation(orgId, {
				role: linkRole,
				expiry: linkExpiry,
				max_uses: maxUses
			});
			generatedLink = `${window.location.origin}/invite/${inv.token}`;
			await loadInvitations();
		} catch {
			// Error handled by API client
		} finally {
			creatingLink = false;
		}
	}

	function copyLink(): void {
		if (generatedLink) {
			navigator.clipboard.writeText(generatedLink);
			copiedLink = true;
			toasts.success('Link copied to clipboard.');
			setTimeout(() => (copiedLink = false), 2000);
		}
	}

	async function handleSaveSSO(): Promise<void> {
		ssoSaving = true;
		try {
			const data = {
				provider_type: providerType,
				metadata_url: metadataUrl,
				entity_id: entityId,
				certificate,
				is_active: isActive,
				enforce_sso: enforceSso,
				emergency_bypass_enabled: emergencyBypass
			};

			if (ssoConfig) {
				ssoConfig = await updateSSOConfig(orgId, data);
			} else {
				ssoConfig = await createSSOConfig(orgId, data);
			}
			populateForm(ssoConfig);
			// Reload SP metadata
			try {
				spMetadata = await getSPMetadata(orgId);
			} catch {
				spMetadata = null;
			}
			toasts.success('SSO configuration saved.');
		} catch {
			// Error handled by API client
		} finally {
			ssoSaving = false;
		}
	}

	async function handleDeleteSSO(): Promise<void> {
		deleting = true;
		try {
			await deleteSSOConfig(orgId);
			ssoConfig = null;
			spMetadata = null;
			resetForm();
			showDeleteConfirm = false;
			toasts.success('SSO configuration deleted.');
		} catch {
			// Error handled by API client
		} finally {
			deleting = false;
		}
	}

	async function handleTestConnection(): Promise<void> {
		if (!metadataUrl.trim()) {
			testResult = { ok: false, message: 'Metadata URL is required.' };
			return;
		}
		testingConnection = true;
		testResult = null;
		try {
			const response = await fetch(metadataUrl, {
				method: 'GET',
				mode: 'no-cors',
				signal: AbortSignal.timeout(10000)
			});
			// no-cors always returns opaque response; if we get here the server responded
			testResult = { ok: true, message: 'Metadata URL is reachable.' };
		} catch {
			testResult = {
				ok: false,
				message: 'Could not reach metadata URL. Check the URL and try again.'
			};
		} finally {
			testingConnection = false;
		}
	}

	function handleEnforceToggle(): void {
		if (!enforceSso) {
			// Turning ON — show confirmation
			showEnforceConfirm = true;
		} else {
			// Turning OFF — no confirmation needed
			enforceSso = false;
		}
	}

	function confirmEnforce(): void {
		enforceSso = true;
		showEnforceConfirm = false;
	}

	function copyToClipboard(text: string): void {
		navigator.clipboard.writeText(text);
		toasts.success('Copied to clipboard.');
	}

	// ── Integration functions ──────────────────────────────────────────────

	async function loadSlack(): Promise<void> {
		slackLoading = true;
		try {
			const data = await getSlackIntegration(orgId);
			slackWebhookUrl = data.webhook_url;
			slackChannelName = data.channel_name;
			slackActive = data.is_active;
			slackExists = true;
		} catch {
			slackExists = false;
		} finally {
			slackLoading = false;
		}
	}

	async function loadDiscord(): Promise<void> {
		discordLoading = true;
		try {
			const data = await getDiscordIntegration(orgId);
			discordWebhookUrl = data.webhook_url;
			discordChannelName = data.channel_name;
			discordActive = data.is_active;
			discordExists = true;
		} catch {
			discordExists = false;
		} finally {
			discordLoading = false;
		}
	}

	async function handleSaveSlack(): Promise<void> {
		if (!slackWebhookUrl.trim()) {
			toasts.error('Webhook URL is required.');
			return;
		}
		slackSaving = true;
		slackTestResult = null;
		try {
			await upsertSlackIntegration(orgId, {
				webhook_url: slackWebhookUrl.trim(),
				channel_name: slackChannelName.trim(),
				is_active: slackActive
			});
			slackExists = true;
			toasts.success('Slack integration saved.');
		} catch {
			// Error handled by API client
		} finally {
			slackSaving = false;
		}
	}

	async function handleDeleteSlack(): Promise<void> {
		try {
			await deleteSlackIntegration(orgId);
			slackWebhookUrl = '';
			slackChannelName = '';
			slackActive = true;
			slackExists = false;
			slackTestResult = null;
			toasts.success('Slack integration removed.');
		} catch {
			// Error handled by API client
		}
	}

	async function handleTestSlack(): Promise<void> {
		slackTesting = true;
		slackTestResult = null;
		try {
			slackTestResult = await testSlackIntegration(orgId);
		} catch {
			slackTestResult = { ok: false, message: 'Request failed.' };
		} finally {
			slackTesting = false;
		}
	}

	async function handleSaveDiscord(): Promise<void> {
		if (!discordWebhookUrl.trim()) {
			toasts.error('Webhook URL is required.');
			return;
		}
		discordSaving = true;
		discordTestResult = null;
		try {
			await upsertDiscordIntegration(orgId, {
				webhook_url: discordWebhookUrl.trim(),
				channel_name: discordChannelName.trim(),
				is_active: discordActive
			});
			discordExists = true;
			toasts.success('Discord integration saved.');
		} catch {
			// Error handled by API client
		} finally {
			discordSaving = false;
		}
	}

	async function handleDeleteDiscord(): Promise<void> {
		try {
			await deleteDiscordIntegration(orgId);
			discordWebhookUrl = '';
			discordChannelName = '';
			discordActive = true;
			discordExists = false;
			discordTestResult = null;
			toasts.success('Discord integration removed.');
		} catch {
			// Error handled by API client
		}
	}

	async function handleTestDiscord(): Promise<void> {
		discordTesting = true;
		discordTestResult = null;
		try {
			discordTestResult = await testDiscordIntegration(orgId);
		} catch {
			discordTestResult = { ok: false, message: 'Request failed.' };
		} finally {
			discordTesting = false;
		}
	}

	// ── Template helpers ───────────────────────────────────────────────

	async function loadTemplates(): Promise<void> {
		tmplLoading = true;
		try {
			tmplList = await listTemplates(orgId);
		} catch {
			tmplList = [];
		} finally {
			tmplLoading = false;
		}
	}

	function openTemplateForm(tmpl: ProjectTemplate | null = null): void {
		tmplEditing = tmpl;
		tmplName = tmpl?.name ?? '';
		tmplDescription = tmpl?.description ?? '';
		tmplInstructions = tmpl?.custom_instructions ?? '';
		tmplIcon = tmpl?.icon ?? '';
		tmplFiles = tmpl?.files?.map((f) => ({ ...f })) ?? [];
		tmplShowForm = true;
	}

	function closeTemplateForm(): void {
		tmplShowForm = false;
		tmplEditing = null;
	}

	function addTemplateFile(): void {
		tmplFiles = [...tmplFiles, { file_name: '', file_content: '', sort_order: tmplFiles.length }];
	}

	function removeTemplateFile(index: number): void {
		tmplFiles = tmplFiles.filter((_, i) => i !== index);
	}

	async function handleSaveTemplate(): Promise<void> {
		if (!tmplName.trim()) return;
		tmplSaving = true;
		try {
			const data = {
				name: tmplName.trim(),
				description: tmplDescription.trim(),
				custom_instructions: tmplInstructions,
				icon: tmplIcon.trim(),
				files: tmplFiles.filter((f) => f.file_name.trim())
			};
			if (tmplEditing) {
				await updateTemplate(orgId, tmplEditing.id, data);
				toasts.success('Template updated');
			} else {
				await createTemplate(orgId, data);
				toasts.success('Template created');
			}
			closeTemplateForm();
			await loadTemplates();
		} catch {
			toasts.error('Failed to save template');
		} finally {
			tmplSaving = false;
		}
	}

	async function handleDeleteTemplate(id: string): Promise<void> {
		tmplDeletingId = id;
		try {
			await deleteTemplate(orgId, id);
			toasts.success('Template deleted');
			await loadTemplates();
		} catch {
			toasts.error('Failed to delete template');
		} finally {
			tmplDeletingId = null;
		}
	}

	// ── IP Allowlist helpers ────────────────────────────────────────────

	async function loadIPAllowlist(): Promise<void> {
		ipLoading = true;
		try {
			const data = await getIPAllowlist(orgId);
			ipEntries = data.entries;
			ipYourIp = data.your_ip;
		} catch {
			ipEntries = [];
		} finally {
			ipLoading = false;
		}
	}

	function checkLockoutRisk(): boolean {
		if (!ipYourIp) return false;
		// If adding a new entry and there's nothing matching our IP yet, warn
		const activeCidrs = ipEntries.filter((e) => e.is_active).map((e) => e.cidr_range);
		// Will have entries after adding this one — check if our IP would be included
		// Simple heuristic: if there are active entries and the new entry is not a loopback
		if (activeCidrs.length === 0) return false; // first entry — always warn
		return true; // Show warning on first add; after that list already has entries
	}

	async function handleAddIPEntry(): Promise<void> {
		if (!ipCidr.trim()) return;
		ipAdding = true;
		try {
			await addIPAllowlistEntry(orgId, {
				cidr_range: ipCidr.trim(),
				description: ipDescription.trim()
			});
			toasts.success(`Added ${ipCidr.trim()} to allowlist.`);
			ipCidr = '';
			ipDescription = '';
			ipShowLockoutWarning = false;
			await loadIPAllowlist();
		} catch {
			// Error handled by API client
		} finally {
			ipAdding = false;
		}
	}

	async function handleRemoveIPEntry(entryId: string): Promise<void> {
		ipRemovingId = entryId;
		try {
			await removeIPAllowlistEntry(orgId, entryId);
			toasts.success('IP allowlist entry removed.');
			await loadIPAllowlist();
		} catch {
			// Error handled by API client
		} finally {
			ipRemovingId = null;
		}
	}

	// ── Model Policy helpers ──────────────────────────────────────────

	async function loadModelPolicy(): Promise<void> {
		mpLoading = true;
		try {
			const data = await getModelPolicy(orgId);
			mpAllowedModels = data.allowed_models || [];
			mpAllowedProviders = data.allowed_providers || [];
			mpBlockByom = data.block_byom;
		} catch {
			mpAllowedModels = [];
			mpAllowedProviders = [];
			mpBlockByom = false;
		} finally {
			mpLoading = false;
		}
	}

	async function handleSaveModelPolicy(): Promise<void> {
		mpSaving = true;
		try {
			const data = await updateModelPolicy(orgId, {
				allowed_models: mpAllowedModels,
				allowed_providers: mpAllowedProviders,
				block_byom: mpBlockByom
			});
			mpAllowedModels = data.allowed_models || [];
			mpAllowedProviders = data.allowed_providers || [];
			mpBlockByom = data.block_byom;
			toasts.success('Model policy updated.');
		} catch {
			// Error handled by API client
		} finally {
			mpSaving = false;
		}
	}

	function handleAddModel(): void {
		const model = mpNewModel.trim();
		if (model && !mpAllowedModels.includes(model)) {
			mpAllowedModels = [...mpAllowedModels, model];
			mpNewModel = '';
		}
	}

	function handleRemoveModel(model: string): void {
		mpAllowedModels = mpAllowedModels.filter((m) => m !== model);
	}

	function handleAddProvider(): void {
		const provider = mpNewProvider.trim();
		if (provider && !mpAllowedProviders.includes(provider)) {
			mpAllowedProviders = [...mpAllowedProviders, provider];
			mpNewProvider = '';
		}
	}

	function handleRemoveProvider(provider: string): void {
		mpAllowedProviders = mpAllowedProviders.filter((p) => p !== provider);
	}

	// ── Agent Policy helpers ──────────────────────────────────────────────

	async function loadAgentPolicy(): Promise<void> {
		apLoading = true;
		try {
			const data = await getAgentPolicy(orgId);
			apBlockedTools = data.blocked_tools || [];
			apBlockedToolGroups = data.blocked_tool_groups || [];
			apRequireHitlFor = data.require_hitl_for || [];
		} catch {
			apBlockedTools = [];
			apBlockedToolGroups = [];
			apRequireHitlFor = [];
		} finally {
			apLoading = false;
		}
	}

	async function handleSaveAgentPolicy(): Promise<void> {
		apSaving = true;
		try {
			const data = await updateAgentPolicy(orgId, {
				blocked_tools: apBlockedTools,
				blocked_tool_groups: apBlockedToolGroups,
				require_hitl_for: apRequireHitlFor
			});
			apBlockedTools = data.blocked_tools || [];
			apBlockedToolGroups = data.blocked_tool_groups || [];
			apRequireHitlFor = data.require_hitl_for || [];
			toasts.success('Agent policy updated.');
		} catch {
			// Error handled by API client
		} finally {
			apSaving = false;
		}
	}

	function handleAddBlockedTool(): void {
		const tool = apNewBlockedTool.trim();
		if (tool && !apBlockedTools.includes(tool)) {
			apBlockedTools = [...apBlockedTools, tool];
			apNewBlockedTool = '';
		}
	}

	function handleRemoveBlockedTool(tool: string): void {
		apBlockedTools = apBlockedTools.filter((t) => t !== tool);
	}

	function handleToggleToolGroup(group: string): void {
		if (apBlockedToolGroups.includes(group)) {
			apBlockedToolGroups = apBlockedToolGroups.filter((g) => g !== group);
		} else {
			apBlockedToolGroups = [...apBlockedToolGroups, group];
		}
	}

	function handleAddHitlTool(): void {
		const tool = apNewHitlTool.trim();
		if (tool && !apRequireHitlFor.includes(tool)) {
			apRequireHitlFor = [...apRequireHitlFor, tool];
			apNewHitlTool = '';
		}
	}

	function handleRemoveHitlTool(tool: string): void {
		apRequireHitlFor = apRequireHitlFor.filter((t) => t !== tool);
	}

	// ── Access Policy helpers ──────────────────────────────────────────

	function resetCapForm(): void {
		capName = '';
		capAction = 'block';
		capPriority = 0;
		capIsActive = true;
		capConditions = [];
		capEditingId = null;
		capCondType = 'ip_range';
		capCondCidr = '';
		capCondStartHour = 9;
		capCondEndHour = 17;
		capCondTimezone = 'UTC';
		capCondDays = [];
		capCondPattern = '';
	}

	async function loadAccessPolicies(): Promise<void> {
		capLoading = true;
		try {
			const data = await getAccessPolicies(orgId);
			capPolicies = data.policies;
			capYourIp = data.your_ip;
		} catch {
			capPolicies = [];
		} finally {
			capLoading = false;
		}
	}

	function handleAddCondition(): void {
		let cond: AccessPolicyCondition = { type: capCondType };
		if (capCondType === 'ip_range') {
			if (!capCondCidr.trim()) return;
			cond.cidr = capCondCidr.trim();
		} else if (capCondType === 'time_of_day') {
			cond.start_hour = capCondStartHour;
			cond.end_hour = capCondEndHour;
			cond.timezone = capCondTimezone || 'UTC';
		} else if (capCondType === 'day_of_week') {
			if (capCondDays.length === 0) return;
			cond.days = [...capCondDays];
			cond.timezone = capCondTimezone || 'UTC';
		} else if (capCondType === 'user_agent_pattern') {
			if (!capCondPattern.trim()) return;
			cond.pattern = capCondPattern.trim();
		}
		capConditions = [...capConditions, cond];
		capCondCidr = '';
		capCondPattern = '';
		capCondDays = [];
	}

	function handleRemoveCondition(idx: number): void {
		capConditions = capConditions.filter((_, i) => i !== idx);
	}

	function handleToggleDay(day: number): void {
		if (capCondDays.includes(day)) {
			capCondDays = capCondDays.filter((d) => d !== day);
		} else {
			capCondDays = [...capCondDays, day];
		}
	}

	function handleEditPolicy(policy: AccessPolicy): void {
		capEditingId = policy.id;
		capName = policy.name;
		capAction = policy.action;
		capPriority = policy.priority;
		capIsActive = policy.is_active;
		capConditions = [...policy.conditions];
		capShowForm = true;
	}

	async function handleSavePolicy(): Promise<void> {
		if (!capName.trim()) return;
		capSaving = true;
		try {
			if (capEditingId) {
				await updateAccessPolicy(orgId, capEditingId, {
					name: capName.trim(),
					action: capAction,
					priority: capPriority,
					is_active: capIsActive,
					conditions: capConditions
				});
				toasts.success('Access policy updated.');
			} else {
				await createAccessPolicy(orgId, {
					name: capName.trim(),
					action: capAction,
					priority: capPriority,
					is_active: capIsActive,
					conditions: capConditions
				});
				toasts.success('Access policy created.');
			}
			resetCapForm();
			capShowForm = false;
			await loadAccessPolicies();
		} catch {
			// Error handled by API client
		} finally {
			capSaving = false;
		}
	}

	async function handleDeletePolicy(policyId: string): Promise<void> {
		capDeletingId = policyId;
		try {
			await deleteAccessPolicy(orgId, policyId);
			toasts.success('Access policy deleted.');
			await loadAccessPolicies();
		} catch {
			// Error handled by API client
		} finally {
			capDeletingId = null;
		}
	}

	function conditionLabel(cond: AccessPolicyCondition): string {
		if (cond.type === 'ip_range') return `IP: ${cond.cidr}`;
		if (cond.type === 'time_of_day')
			return `Time: ${cond.start_hour}:00-${cond.end_hour}:00 ${cond.timezone ?? 'UTC'}`;
		if (cond.type === 'day_of_week')
			return `Days: ${(cond.days ?? []).map((d) => DAY_NAMES[d]).join(', ')}`;
		if (cond.type === 'user_agent_pattern') return `UA: ${cond.pattern}`;
		return cond.type;
	}

	// ── Analytics helpers ──────────────────────────────────────────────

	function _analyticsParams() {
		const params: Record<string, string> = {};
		if (analyticsCustomStart && analyticsCustomEnd) {
			params.start_date = analyticsCustomStart;
			params.end_date = analyticsCustomEnd;
		} else {
			params.period = analyticsPeriod;
		}
		return params;
	}

	async function loadAnalytics(): Promise<void> {
		analyticsLoading = true;
		const params = _analyticsParams();
		try {
			const [summary, membersData, projectsData] = await Promise.all([
				getAnalyticsSummary(orgId, params),
				getAnalyticsMembers(orgId, {
					...params,
					page: memberPage,
					page_size: 20,
					sort_by: memberSortBy,
					sort_order: memberSortOrder
				}),
				getAnalyticsProjects(orgId, {
					...params,
					page: projectPage,
					page_size: 20,
					sort_by: projectSortBy,
					sort_order: projectSortOrder
				})
			]);
			analyticsSummary = summary;
			analyticsMembers = membersData;
			analyticsProjects = projectsData;
		} catch {
			// Permission denied or error — hide analytics silently
		} finally {
			analyticsLoading = false;
		}
	}

	async function handleAnalyticsPeriodChange(): Promise<void> {
		analyticsCustomStart = '';
		analyticsCustomEnd = '';
		memberPage = 1;
		projectPage = 1;
		await loadAnalytics();
	}

	async function handleAnalyticsCustomRange(): Promise<void> {
		if (!analyticsCustomStart || !analyticsCustomEnd) return;
		memberPage = 1;
		projectPage = 1;
		await loadAnalytics();
	}

	async function handleMemberSort(field: string): Promise<void> {
		if (memberSortBy === field) {
			memberSortOrder = memberSortOrder === 'desc' ? 'asc' : 'desc';
		} else {
			memberSortBy = field;
			memberSortOrder = 'desc';
		}
		memberPage = 1;
		await loadAnalytics();
	}

	async function handleProjectSort(field: string): Promise<void> {
		if (projectSortBy === field) {
			projectSortOrder = projectSortOrder === 'desc' ? 'asc' : 'desc';
		} else {
			projectSortBy = field;
			projectSortOrder = 'desc';
		}
		projectPage = 1;
		await loadAnalytics();
	}

	async function handleMemberPage(p: number): Promise<void> {
		memberPage = p;
		await loadAnalytics();
	}

	async function handleProjectPage(p: number): Promise<void> {
		projectPage = p;
		await loadAnalytics();
	}

	function handleExportMembersCsv(): void {
		const params = _analyticsParams();
		const url = exportAnalyticsMembersUrl(orgId, params);
		const token = get(authToken);
		fetch(url, {
			headers: token ? { Authorization: `Bearer ${token}` } : {}
		})
			.then((res) => {
				if (!res.ok) throw new Error('Export failed');
				return res.blob();
			})
			.then((blob) => {
				const a = document.createElement('a');
				a.href = URL.createObjectURL(blob);
				a.download = 'member_analytics.csv';
				a.click();
				URL.revokeObjectURL(a.href);
				toasts.success('Member analytics exported.');
			})
			.catch(() => {
				toasts.error('Failed to export member analytics.');
			});
	}

	function handleExportProjectsCsv(): void {
		const params = _analyticsParams();
		const url = exportAnalyticsProjectsUrl(orgId, params);
		const token = get(authToken);
		fetch(url, {
			headers: token ? { Authorization: `Bearer ${token}` } : {}
		})
			.then((res) => {
				if (!res.ok) throw new Error('Export failed');
				return res.blob();
			})
			.then((blob) => {
				const a = document.createElement('a');
				a.href = URL.createObjectURL(blob);
				a.download = 'project_analytics.csv';
				a.click();
				URL.revokeObjectURL(a.href);
				toasts.success('Project analytics exported.');
			})
			.catch(() => {
				toasts.error('Failed to export project analytics.');
			});
	}

	function formatDate(iso: string): string {
		try {
			const d = new Date(iso);
			return d.toLocaleString(undefined, {
				year: 'numeric',
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}

	function sortIndicator(field: string, currentSort: string, currentOrder: string): string {
		if (field !== currentSort) return '';
		return currentOrder === 'desc' ? ' \u2193' : ' \u2191';
	}

	onMount(async () => {
		if (!$enterpriseMode) {
			goto('/');
			return;
		}
		await loadOrg();
		loading = false;
		loadMembers();
		loadInvitations();
		loadSSO();
		loadSlack();
		loadDiscord();
		loadTemplates();
		loadIPAllowlist();
		loadAccessPolicies();
		loadModelPolicy();
		loadAgentPolicy();
		loadAnalytics();
	});
</script>

{#if loading}
	<div class="flex h-full items-center justify-center py-16">
		<svg
			class="h-6 w-6 animate-spin text-muted"
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
{:else if org}
	<div class="flex w-full">
		<SideNav
			bind:value={activeTab}
			items={navItems}
			title={org.name}
			searchParamKey="section"
			class="px-4 py-8"
		/>

		<div class="min-w-0 flex-1 px-6 py-8">
			<!-- Tab content -->
			{#key activeTab}
				<div in:fade={{ duration: 100, delay: 30 }} out:fade={{ duration: 60 }}>
					{#if activeTab === 'members'}
						<!-- Members Tab -->
						<div class="space-y-4">
							<div class="flex items-center justify-between">
								<div>
									<h3 class="text-sm font-medium text-foreground">Members</h3>
									<p class="text-xs text-muted">
										{members.length} member{members.length !== 1 ? 's' : ''} in this organization.
									</p>
								</div>
								<!-- Leave Organization button (not for owners) -->
								{#if myRole && myRole !== 'owner'}
									{#if showLeaveConfirm}
										<div class="flex items-center gap-2">
											<span class="text-xs text-muted"
												>Leave {org?.name ?? 'this org'}? You'll lose access to all shared projects
												and conversations.</span
											>
											<button
												onclick={handleLeaveOrg}
												disabled={leavingOrg}
												class="rounded px-2 py-1 text-xs font-medium text-red-600 hover:text-red-700"
											>
												{leavingOrg ? 'Leaving...' : 'Yes'}
											</button>
											<button
												onclick={() => (showLeaveConfirm = false)}
												class="rounded px-2 py-1 text-xs font-medium text-muted hover:text-foreground"
											>
												Cancel
											</button>
										</div>
									{:else}
										<button
											onclick={() => (showLeaveConfirm = true)}
											class="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 hover:text-red-700 dark:border-red-500/20 dark:hover:bg-red-500/5"
										>
											Leave Organization
										</button>
									{/if}
								{/if}
							</div>

							{#if members.length > 0}
								<div class="rounded-xl border border-border">
									{#each members as member, i (member.id)}
										<div
											class="flex items-center justify-between gap-3 px-4 py-3 {i <
											members.length - 1
												? 'border-b border-border-subtle'
												: ''}"
										>
											<div class="min-w-0 flex-1">
												<div class="flex items-center gap-2">
													<p class="truncate text-sm font-medium text-foreground">
														{member.name || member.email}
													</p>
													{#if isCurrentUser(member)}
														<span
															class="rounded px-1.5 py-0.5 text-[10px] font-medium bg-surface text-muted"
															>you</span
														>
													{/if}
												</div>
												<p class="truncate text-xs text-muted">{member.email}</p>
											</div>

											<!-- Role badge or role dropdown -->
											{#if canManageMembers && !isCurrentUser(member)}
												<select
													value={member.role}
													disabled={changingRoleId === member.id}
													onchange={(e) =>
														handleChangeRole(member, (e.target as HTMLSelectElement).value)}
													class="rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground"
												>
													{#each assignableRoles() as role}
														<option value={role}>{role}</option>
													{/each}
												</select>
											{:else}
												<span
													class="ml-3 shrink-0 rounded-lg px-2.5 py-1 text-xs font-medium capitalize
													{member.role === 'owner'
														? 'bg-amber-100 text-amber-800'
														: member.role === 'admin'
															? 'bg-blue-100 text-blue-800'
															: member.role === 'member'
																? 'bg-gray-100 text-gray-600'
																: 'bg-gray-100 text-gray-500'}"
												>
													{member.role}
												</span>
											{/if}

											<!-- Remove button (only for admins/owners, not for self) -->
											{#if canManageMembers && !isCurrentUser(member)}
												{#if confirmingRemoveId === member.id}
													<span class="flex items-center gap-1 text-xs shrink-0">
														<span class="text-muted">Remove {member.name || member.email}?</span>
														<button
															onclick={() => handleRemoveMember(member)}
															disabled={removingMemberId === member.id}
															class="rounded px-2 py-1 text-xs font-medium text-red-600 hover:text-red-700"
														>
															{removingMemberId === member.id ? '...' : 'Yes'}
														</button>
														<button
															onclick={() => (confirmingRemoveId = null)}
															class="rounded px-2 py-1 text-xs font-medium text-muted hover:text-foreground"
														>
															Cancel
														</button>
													</span>
												{:else}
													<button
														onclick={() => (confirmingRemoveId = member.id)}
														class="shrink-0 rounded px-2 py-1 text-xs font-medium text-red-600 hover:text-red-700"
														aria-label="Remove {member.name || member.email}"
													>
														Remove
													</button>
												{/if}
											{/if}
										</div>
									{/each}
								</div>
							{:else}
								<p class="text-sm text-muted">No members found.</p>
							{/if}
						</div>
					{:else if activeTab === 'invitations'}
						<!-- Invitations Tab -->
						<div class="space-y-6">
							<!-- Send Email Invite -->
							<section>
								<h3 class="text-sm font-medium text-foreground">Invite by Email</h3>
								<p class="text-xs text-muted">
									Send an email invitation to join this organization.
								</p>
								<div class="mt-3 flex gap-2">
									<input
										type="email"
										bind:value={inviteEmail}
										placeholder="email@example.com"
										class="flex-1 rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
									<select
										bind:value={inviteRole}
										class="rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none"
									>
										<option value="viewer">Viewer</option>
										<option value="member">Member</option>
										<option value="admin">Admin</option>
									</select>
									<button
										onclick={handleSendInvite}
										disabled={inviting || !inviteEmail.trim()}
										class="shrink-0 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
									>
										{inviting ? 'Sending...' : 'Send Invite'}
									</button>
								</div>
							</section>

							<!-- Create Shareable Link -->
							<section class="border-t border-border-subtle pt-5">
								<div class="flex items-center justify-between">
									<div>
										<h3 class="text-sm font-medium text-foreground">Shareable Invite Link</h3>
										<p class="text-xs text-muted">Generate a link that anyone can use to join.</p>
									</div>
									<button
										onclick={() => {
											showLinkPopover = !showLinkPopover;
											generatedLink = null;
											copiedLink = false;
										}}
										class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
									>
										{showLinkPopover ? 'Cancel' : 'Create Link'}
									</button>
								</div>

								{#if showLinkPopover}
									<div
										class="mt-3 rounded-xl border border-border-subtle bg-surface p-4"
										in:fade={{ duration: 100 }}
									>
										<div class="grid grid-cols-3 gap-3">
											<div class="flex flex-col gap-1.5">
												<label for="link-role" class="text-xs font-medium text-muted">Role</label>
												<select
													id="link-role"
													bind:value={linkRole}
													class="rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none"
												>
													<option value="viewer">Viewer</option>
													<option value="member">Member</option>
													<option value="admin">Admin</option>
												</select>
											</div>
											<div class="flex flex-col gap-1.5">
												<label for="link-expiry" class="text-xs font-medium text-muted"
													>Expires</label
												>
												<select
													id="link-expiry"
													bind:value={linkExpiry}
													class="rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none"
												>
													<option value="1d">1 day</option>
													<option value="7d">7 days</option>
													<option value="30d">30 days</option>
													<option value="never">Never</option>
												</select>
											</div>
											<div class="flex flex-col gap-1.5">
												<label for="link-max-uses" class="text-xs font-medium text-muted"
													>Max uses</label
												>
												<input
													id="link-max-uses"
													type="number"
													min="1"
													bind:value={linkMaxUses}
													placeholder="Unlimited"
													class="rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted"
												/>
											</div>
										</div>

										<div class="mt-3 flex items-center gap-2">
											<button
												onclick={handleCreateLink}
												disabled={creatingLink}
												class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
											>
												{creatingLink ? 'Generating...' : 'Generate Link'}
											</button>
										</div>

										{#if generatedLink}
											<div class="mt-3 flex items-center gap-2">
												<code
													class="flex-1 truncate rounded-lg bg-surface-2 px-3 py-2 font-mono text-xs text-foreground"
												>
													{generatedLink}
												</code>
												<button
													onclick={copyLink}
													class="shrink-0 rounded-lg border border-border px-3 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
												>
													{copiedLink ? 'Copied!' : 'Copy Link'}
												</button>
											</div>
										{/if}
									</div>
								{/if}
							</section>

							<!-- Pending Invitations List -->
							<section class="border-t border-border-subtle pt-5">
								<h3 class="text-sm font-medium text-foreground">Pending Invitations</h3>
								<p class="mb-3 text-xs text-muted">
									Active invitations that haven't been fully used.
								</p>

								{#if invLoading}
									<div class="flex items-center justify-center py-8">
										<svg
											class="h-5 w-5 animate-spin text-muted"
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
										>
											<circle
												class="opacity-25"
												cx="12"
												cy="12"
												r="10"
												stroke="currentColor"
												stroke-width="4"
											></circle>
											<path
												class="opacity-75"
												fill="currentColor"
												d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
											></path>
										</svg>
									</div>
								{:else if invitations.length === 0}
									<p class="py-4 text-center text-sm text-muted">No pending invitations.</p>
								{:else}
									<div class="rounded-xl border border-border">
										{#each invitations as inv, i (inv.id)}
											<div
												class="flex items-center justify-between px-4 py-3 {i <
												invitations.length - 1
													? 'border-b border-border-subtle'
													: ''}"
											>
												<div class="min-w-0 flex-1">
													<p class="truncate text-sm font-medium text-foreground">
														{inv.email || 'Link invitation'}
													</p>
													<div class="flex items-center gap-2 text-xs text-muted">
														<span class="capitalize">{inv.role}</span>
														{#if inv.max_uses !== null}
															<span>· {inv.use_count}/{inv.max_uses} uses</span>
														{:else}
															<span>· {inv.use_count} uses</span>
														{/if}
														{#if inv.expires_at}
															<span>· Expires {new Date(inv.expires_at).toLocaleDateString()}</span>
														{/if}
													</div>
												</div>
												<div class="ml-3 flex items-center gap-2">
													{#if !inv.email}
														<button
															onclick={() => {
																navigator.clipboard.writeText(
																	`${window.location.origin}/invite/${inv.token}`
																);
																toasts.success('Link copied.');
															}}
															class="rounded-lg p-2 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
															aria-label="Copy invite link"
														>
															<svg
																xmlns="http://www.w3.org/2000/svg"
																width="14"
																height="14"
																viewBox="0 0 24 24"
																fill="none"
																stroke="currentColor"
																stroke-width="2"
																stroke-linecap="round"
																stroke-linejoin="round"
															>
																<rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
																<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
															</svg>
														</button>
													{/if}
													<button
														onclick={() => handleRevokeInvitation(inv.id)}
														disabled={revokingId === inv.id}
														class="rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 transition-all duration-200 hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-900/20"
													>
														{revokingId === inv.id ? 'Revoking...' : 'Revoke'}
													</button>
												</div>
											</div>
										{/each}
									</div>
								{/if}
							</section>
						</div>
					{:else if activeTab === 'sso'}
						<!-- SSO Tab -->
						{#if ssoLoading}
							<div class="flex items-center justify-center py-12">
								<svg
									class="h-6 w-6 animate-spin text-muted"
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
								>
									<circle
										class="opacity-25"
										cx="12"
										cy="12"
										r="10"
										stroke="currentColor"
										stroke-width="4"
									></circle>
									<path
										class="opacity-75"
										fill="currentColor"
										d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
									></path>
								</svg>
							</div>
						{:else}
							<div class="space-y-6">
								<!-- Status indicator -->
								{#if ssoConfig}
									<div class="flex items-center gap-3">
										<div
											class="h-2.5 w-2.5 rounded-full {ssoConfig.is_active
												? 'bg-green-500'
												: 'bg-gray-300 dark:bg-gray-600'}"
										></div>
										<span class="text-sm font-medium text-foreground">
											{ssoConfig.is_active ? 'Active' : 'Inactive'}
										</span>
										{#if ssoConfig.enforce_sso}
											<span
												class="rounded-lg bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
											>
												Enforced
											</span>
										{/if}
									</div>
								{/if}

								<!-- SSO Configuration Form -->
								<section>
									<div>
										<h3 class="text-sm font-medium text-foreground">
											{ssoConfig ? 'SSO Configuration' : 'Set Up SSO'}
										</h3>
										<p class="text-xs text-muted">
											Configure SAML or OIDC single sign-on for your organization.
										</p>
									</div>

									<div class="mt-4 space-y-4">
										<!-- Provider Type -->
										<div class="flex flex-col gap-1.5">
											<label for="sso-provider-type" class="text-sm font-medium text-foreground"
												>Provider Type</label
											>
											<select
												id="sso-provider-type"
												bind:value={providerType}
												class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
											>
												<option value="saml">SAML</option>
												<option value="oidc">OIDC</option>
											</select>
										</div>

										<!-- Metadata URL -->
										<div class="flex flex-col gap-1.5">
											<label for="sso-metadata-url" class="text-sm font-medium text-foreground"
												>Metadata URL</label
											>
											<div class="flex gap-2">
												<input
													id="sso-metadata-url"
													type="url"
													bind:value={metadataUrl}
													placeholder="https://idp.example.com/metadata.xml"
													class="flex-1 rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
												/>
												<button
													onclick={handleTestConnection}
													disabled={testingConnection || !metadataUrl.trim()}
													class="shrink-0 rounded-lg border border-border px-3 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:border-border-strong hover:bg-surface-2 disabled:opacity-50"
												>
													{testingConnection ? 'Testing...' : 'Test Connection'}
												</button>
											</div>
											{#if testResult}
												<p
													class="text-xs {testResult.ok
														? 'text-green-600 dark:text-green-400'
														: 'text-red-600 dark:text-red-400'}"
												>
													{testResult.message}
												</p>
											{/if}
										</div>

										<!-- Entity ID -->
										<div class="flex flex-col gap-1.5">
											<label for="sso-entity-id" class="text-sm font-medium text-foreground"
												>Entity ID</label
											>
											<input
												id="sso-entity-id"
												type="text"
												bind:value={entityId}
												placeholder="https://idp.example.com/entity"
												class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
											/>
										</div>

										<!-- Certificate -->
										<div class="flex flex-col gap-1.5">
											<label for="sso-certificate" class="text-sm font-medium text-foreground"
												>Certificate</label
											>
											<textarea
												id="sso-certificate"
												bind:value={certificate}
												placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
												rows="5"
												class="w-full resize-y rounded-xl border border-border bg-surface-2 px-4 py-2 font-mono text-xs text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
											></textarea>
										</div>

										<!-- Active toggle -->
										<div class="flex items-center justify-between">
											<div>
												<p class="text-sm font-medium text-foreground">Active</p>
												<p class="text-xs text-muted">
													Enable SSO authentication for this organization.
												</p>
											</div>
											<label class="inline-flex cursor-pointer items-center">
												<input type="checkbox" bind:checked={isActive} class="peer sr-only" />
												<div
													class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
												></div>
												<div
													class="absolute h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
													style="margin-left: 2px;"
												></div>
											</label>
										</div>

										<!-- Enforce SSO toggle -->
										<div class="flex items-center justify-between">
											<div>
												<p class="text-sm font-medium text-foreground">Enforce SSO</p>
												<p class="text-xs text-muted">
													Block password and OAuth login for organization members.
												</p>
											</div>
											<button
												onclick={handleEnforceToggle}
												class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 {enforceSso
													? 'bg-accent'
													: 'bg-border-strong'}"
												role="switch"
												aria-checked={enforceSso}
											>
												<span
													class="inline-block h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 {enforceSso
														? 'translate-x-5'
														: 'translate-x-0.5'}"
												></span>
											</button>
										</div>

										<!-- Emergency bypass toggle -->
										<div class="flex items-center justify-between">
											<div>
												<p class="text-sm font-medium text-foreground">Emergency bypass</p>
												<p class="text-xs text-muted">
													Allow owners to log in with password if the IdP is unreachable. Each
													bypass attempt is audit-logged.
												</p>
											</div>
											<button
												type="button"
												onclick={() => (emergencyBypass = !emergencyBypass)}
												class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-200 {emergencyBypass
													? 'bg-amber-500'
													: 'bg-border-strong'}"
												role="switch"
												aria-checked={emergencyBypass}
											>
												<span
													class="inline-block h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 {emergencyBypass
														? 'translate-x-5'
														: 'translate-x-0.5'}"
												></span>
											</button>
										</div>

										<!-- Save button -->
										<div class="flex items-center gap-3 pt-2">
											<button
												onclick={handleSaveSSO}
												disabled={ssoSaving}
												class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
											>
												{ssoSaving
													? 'Saving...'
													: ssoConfig
														? 'Save Changes'
														: 'Create SSO Configuration'}
											</button>
										</div>
									</div>
								</section>

								<!-- SP Metadata Display -->
								{#if ssoConfig && spMetadata}
									<section class="border-t border-border-subtle pt-5">
										<div>
											<h3 class="text-sm font-medium text-foreground">Service Provider Metadata</h3>
											<p class="text-xs text-muted">
												Provide these values to your Identity Provider (IdP) to complete SSO setup.
											</p>
										</div>

										<div class="mt-4 space-y-3">
											{#each [{ label: 'SP Entity ID', value: spMetadata.entity_id }, { label: 'ACS URL', value: spMetadata.acs_url }, { label: 'SLO URL', value: spMetadata.slo_url }, { label: 'NameID Format', value: spMetadata.name_id_format }] as field (field.label)}
												<div class="flex flex-col gap-1">
													<span class="text-xs font-medium text-muted">{field.label}</span>
													<div class="flex items-center gap-2">
														<code
															class="flex-1 truncate rounded-lg bg-surface px-3 py-2 font-mono text-xs text-foreground"
														>
															{field.value}
														</code>
														<button
															onclick={() => copyToClipboard(field.value)}
															class="shrink-0 rounded-lg p-2 text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
															aria-label="Copy {field.label}"
														>
															<svg
																xmlns="http://www.w3.org/2000/svg"
																width="14"
																height="14"
																viewBox="0 0 24 24"
																fill="none"
																stroke="currentColor"
																stroke-width="2"
																stroke-linecap="round"
																stroke-linejoin="round"
															>
																<rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
																<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
															</svg>
														</button>
													</div>
												</div>
											{/each}
										</div>
									</section>
								{/if}

								<!-- Delete SSO Config -->
								{#if ssoConfig}
									<section class="border-t border-border-subtle pt-5">
										<div>
											<h3 class="text-sm font-medium text-red-600 dark:text-red-400">
												Danger Zone
											</h3>
											<p class="text-xs text-muted">
												Deleting SSO configuration will allow all members to use password/OAuth
												login again.
											</p>
										</div>

										<div class="mt-3">
											{#if !showDeleteConfirm}
												<button
													onclick={() => (showDeleteConfirm = true)}
													class="rounded-lg border border-red-200 px-4 py-2 text-xs font-medium text-red-600 transition-all duration-200 hover:border-red-300 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:border-red-700 dark:hover:bg-red-900/20"
												>
													Delete SSO Configuration
												</button>
											{:else}
												<div
													class="rounded-xl border border-red-200 bg-red-50/50 p-4 dark:border-red-800/50 dark:bg-red-900/10"
												>
													<p class="text-sm font-medium text-red-700 dark:text-red-400">
														Are you sure you want to delete the SSO configuration?
													</p>
													<p class="mt-1 text-xs text-red-600/70 dark:text-red-400/70">
														Members will need to use password or OAuth login after this.
													</p>
													<div class="mt-3 flex gap-2">
														<button
															onclick={handleDeleteSSO}
															disabled={deleting}
															class="rounded-lg bg-red-600 px-4 py-2 text-xs font-medium text-white transition-all duration-200 hover:bg-red-700 disabled:opacity-50"
														>
															{deleting ? 'Deleting...' : 'Yes, Delete'}
														</button>
														<button
															onclick={() => (showDeleteConfirm = false)}
															class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
														>
															Cancel
														</button>
													</div>
												</div>
											{/if}
										</div>
									</section>
								{/if}
							</div>

							<!-- SCIM Tokens sub-section -->
							{#if org}
								<div class="mt-8 border-t border-border-subtle pt-6">
									<ScimTokensSection {orgId} {org} />
								</div>
							{/if}
						{/if}
					{:else if activeTab === 'security'}
						<!-- Security Tab — IP Allowlist -->
						<div class="space-y-6">
							<div>
								<h3 class="text-sm font-medium text-foreground">IP Allowlist</h3>
								<p class="text-xs text-muted">
									Restrict access to this organization to specific IP addresses or ranges. When
									enabled, only requests from allowed IPs can access org resources.
								</p>
								{#if ipYourIp}
									<p class="mt-1 text-xs text-muted">
										Your current IP: <span class="font-mono text-foreground">{ipYourIp}</span>
									</p>
								{/if}
							</div>

							<!-- Add entry form (admin/owner only) -->
							{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
								<div class="rounded-xl border border-border-subtle bg-surface p-4">
									<h4 class="mb-3 text-xs font-medium text-foreground">Add IP Range</h4>
									<div class="flex flex-col gap-3 sm:flex-row sm:items-end">
										<div class="flex-1">
											<label for="ip-cidr" class="mb-1 block text-xs font-medium text-muted"
												>CIDR Range</label
											>
											<input
												id="ip-cidr"
												type="text"
												bind:value={ipCidr}
												placeholder="e.g. 10.0.0.0/24 or 2001:db8::/32"
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div class="flex-1">
											<label for="ip-desc" class="mb-1 block text-xs font-medium text-muted"
												>Description</label
											>
											<input
												id="ip-desc"
												type="text"
												bind:value={ipDescription}
												placeholder="e.g. Office VPN"
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<button
											onclick={handleAddIPEntry}
											disabled={ipAdding || !ipCidr.trim()}
											class="shrink-0 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
										>
											{ipAdding ? 'Adding...' : 'Add Range'}
										</button>
									</div>
									{#if ipYourIp && ipEntries.filter((e) => e.is_active).length === 0 && ipCidr.trim()}
										<p class="mt-2 text-xs text-amber-600 dark:text-amber-400">
											Warning: Adding an allowlist entry that doesn't include your IP ({ipYourIp})
											will lock you out of this organization's settings.
										</p>
									{/if}
								</div>
							{/if}

							<!-- Entry list -->
							{#if ipLoading}
								<div class="flex justify-center py-8">
									<svg
										class="h-5 w-5 animate-spin text-muted"
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
									>
										<circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
										></circle>
										<path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path>
									</svg>
								</div>
							{:else if ipEntries.length === 0}
								<div class="py-8 text-center">
									<p class="text-sm text-muted">No IP restrictions configured.</p>
									<p class="mt-1 text-xs text-subtle">All IP addresses are currently allowed.</p>
								</div>
							{:else}
								<div class="rounded-xl border border-border">
									{#each ipEntries as entry, i (entry.id)}
										<div
											class="flex items-center justify-between px-4 py-3 {i < ipEntries.length - 1
												? 'border-b border-border-subtle'
												: ''}"
										>
											<div class="min-w-0 flex-1">
												<div class="flex items-center gap-2">
													<p class="font-mono text-sm font-medium text-foreground">
														{entry.cidr_range}
													</p>
													<span
														class="rounded-lg px-2 py-0.5 text-xs font-medium {entry.is_active
															? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
															: 'bg-surface text-muted'}"
													>
														{entry.is_active ? 'Active' : 'Inactive'}
													</span>
												</div>
												{#if entry.description}
													<p class="mt-0.5 text-xs text-muted">{entry.description}</p>
												{/if}
												<p class="mt-0.5 text-xs text-subtle">
													Added {new Date(entry.created_at).toLocaleDateString()}
												</p>
											</div>
											{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
												<button
													onclick={() => handleRemoveIPEntry(entry.id)}
													disabled={ipRemovingId === entry.id}
													class="ml-3 shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-900/20"
												>
													{ipRemovingId === entry.id ? 'Removing...' : 'Remove'}
												</button>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</div>

						<!-- Model Policy -->
						<div class="mt-8 space-y-6">
							<div>
								<h3 class="text-sm font-medium text-foreground">Model Restrictions</h3>
								<p class="text-xs text-muted">
									Control which LLM models and providers members can use in org projects. Empty
									lists mean all models/providers are allowed.
								</p>
							</div>

							{#if mpLoading}
								<div class="flex justify-center py-8">
									<svg
										class="h-5 w-5 animate-spin text-muted"
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
									>
										<circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
										></circle>
										<path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path>
									</svg>
								</div>
							{:else}
								<!-- Allowed Models -->
								<div class="rounded-xl border border-border-subtle bg-surface p-4">
									<h4 class="mb-1 text-xs font-medium text-foreground">Allowed Models</h4>
									<p class="mb-3 text-xs text-muted">
										Restrict which models members can select. Leave empty to allow all models.
									</p>

									{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
										<div class="mb-3 flex gap-2">
											<input
												type="text"
												bind:value={mpNewModel}
												placeholder="e.g. claude-sonnet-4, gpt-4o"
												onkeydown={(e) => e.key === 'Enter' && handleAddModel()}
												class="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
											<button
												onclick={handleAddModel}
												disabled={!mpNewModel.trim()}
												class="shrink-0 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
											>
												Add
											</button>
										</div>
									{/if}

									{#if mpAllowedModels.length === 0}
										<p class="text-xs text-subtle">No restrictions — all models are allowed.</p>
									{:else}
										<div class="flex flex-wrap gap-2">
											{#each mpAllowedModels as model (model)}
												<span
													class="inline-flex items-center gap-1 rounded-lg bg-background px-2.5 py-1 text-xs font-medium text-foreground border border-border"
												>
													{model}
													{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
														<button
															onclick={() => handleRemoveModel(model)}
															class="ml-0.5 text-muted hover:text-red-500 transition-colors"
															aria-label="Remove {model}"
														>
															&times;
														</button>
													{/if}
												</span>
											{/each}
										</div>
									{/if}
								</div>

								<!-- Allowed Providers -->
								<div class="rounded-xl border border-border-subtle bg-surface p-4">
									<h4 class="mb-1 text-xs font-medium text-foreground">Allowed Providers</h4>
									<p class="mb-3 text-xs text-muted">
										Restrict which LLM providers members can use. Leave empty to allow all
										providers.
									</p>

									{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
										<div class="mb-3 flex gap-2">
											<input
												type="text"
												bind:value={mpNewProvider}
												placeholder="e.g. anthropic, openai, google"
												onkeydown={(e) => e.key === 'Enter' && handleAddProvider()}
												class="flex-1 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
											<button
												onclick={handleAddProvider}
												disabled={!mpNewProvider.trim()}
												class="shrink-0 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
											>
												Add
											</button>
										</div>
									{/if}

									{#if mpAllowedProviders.length === 0}
										<p class="text-xs text-subtle">No restrictions — all providers are allowed.</p>
									{:else}
										<div class="flex flex-wrap gap-2">
											{#each mpAllowedProviders as provider (provider)}
												<span
													class="inline-flex items-center gap-1 rounded-lg bg-background px-2.5 py-1 text-xs font-medium text-foreground border border-border"
												>
													{provider}
													{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
														<button
															onclick={() => handleRemoveProvider(provider)}
															class="ml-0.5 text-muted hover:text-red-500 transition-colors"
															aria-label="Remove {provider}"
														>
															&times;
														</button>
													{/if}
												</span>
											{/each}
										</div>
									{/if}
								</div>

								<!-- Block BYOM toggle -->
								<div class="rounded-xl border border-border-subtle bg-surface p-4">
									<div class="flex items-center justify-between">
										<div>
											<h4 class="text-xs font-medium text-foreground">
												Block Bring-Your-Own-Model (BYOM)
											</h4>
											<p class="mt-0.5 text-xs text-muted">
												When enabled, members cannot use personal API keys in org projects — only
												platform-provided models are allowed.
											</p>
										</div>
										{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
											<button
												onclick={() => (mpBlockByom = !mpBlockByom)}
												class="relative ml-4 h-6 w-11 shrink-0 rounded-full transition-colors duration-200 {mpBlockByom
													? 'bg-accent'
													: 'bg-border'}"
												role="switch"
												aria-checked={mpBlockByom}
											>
												<span
													class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow transition-transform duration-200 {mpBlockByom
														? 'translate-x-5'
														: ''}"
												></span>
											</button>
										{:else}
											<span class="text-xs font-medium {mpBlockByom ? 'text-accent' : 'text-muted'}"
												>{mpBlockByom ? 'Blocked' : 'Allowed'}</span
											>
										{/if}
									</div>
								</div>

								<!-- Save button -->
								{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
									<div class="flex justify-end">
										<button
											onclick={handleSaveModelPolicy}
											disabled={mpSaving}
											class="rounded-lg bg-foreground px-5 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
										>
											{mpSaving ? 'Saving...' : 'Save Model Policy'}
										</button>
									</div>
								{/if}
							{/if}
						</div>

						<!-- Agent Guardrails -->
						<div class="rounded-xl border border-border bg-background p-6">
							<h3 class="text-sm font-medium text-foreground">Agent Guardrails</h3>
							<p class="mt-1 text-xs text-muted">
								Control which tools agents can use and which require human approval in org projects.
							</p>

							{#if apLoading}
								<div class="flex items-center justify-center py-6">
									<svg
										class="h-5 w-5 animate-spin text-muted"
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										><circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
										></circle><path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path></svg
									>
								</div>
							{:else}
								<div class="mt-4 space-y-5">
									<!-- Blocked Tool Groups -->
									<div>
										<label class="mb-2 block text-xs font-medium text-foreground"
											>Blocked Tool Groups</label
										>
										<p class="mb-2 text-xs text-muted">
											Entire groups of tools to disable for all org projects.
										</p>
										<div class="flex flex-wrap gap-2">
											{#each TOOL_GROUPS as group}
												{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
													<button
														onclick={() => handleToggleToolGroup(group)}
														class="rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors {apBlockedToolGroups.includes(
															group
														)
															? 'border-accent bg-accent/10 text-accent'
															: 'border-border bg-background text-muted hover:border-foreground hover:text-foreground'}"
													>
														{group}
													</button>
												{:else}
													<span
														class="rounded-lg border px-3 py-1.5 text-xs font-medium {apBlockedToolGroups.includes(
															group
														)
															? 'border-accent bg-accent/10 text-accent'
															: 'border-border text-muted'}"
													>
														{group}
													</span>
												{/if}
											{/each}
										</div>
									</div>

									<!-- Blocked Individual Tools -->
									<div>
										<label class="mb-2 block text-xs font-medium text-foreground"
											>Blocked Individual Tools</label
										>
										<p class="mb-2 text-xs text-muted">
											Specific tool names to block (e.g. "shell", "browse").
										</p>
										{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
											<div class="flex gap-2">
												<input
													type="text"
													bind:value={apNewBlockedTool}
													placeholder="Tool name"
													onkeydown={(e: KeyboardEvent) =>
														e.key === 'Enter' && handleAddBlockedTool()}
													class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
												/>
												<button
													onclick={handleAddBlockedTool}
													class="shrink-0 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:bg-foreground/90"
												>
													Add
												</button>
											</div>
										{/if}
										{#if apBlockedTools.length > 0}
											<div class="mt-2 flex flex-wrap gap-1.5">
												{#each apBlockedTools as tool}
													<span
														class="inline-flex items-center gap-1 rounded-md bg-accent/10 px-2 py-1 text-xs font-medium text-accent"
													>
														{tool}
														{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
															<button
																onclick={() => handleRemoveBlockedTool(tool)}
																class="ml-0.5 hover:text-accent/70">&times;</button
															>
														{/if}
													</span>
												{/each}
											</div>
										{:else}
											<p class="mt-2 text-xs text-muted">No individual tools blocked.</p>
										{/if}
									</div>

									<!-- HITL Tools -->
									<div>
										<label class="mb-2 block text-xs font-medium text-foreground"
											>Require Human Approval</label
										>
										<p class="mb-2 text-xs text-muted">
											Tools that require human approval before execution.
										</p>
										{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
											<div class="flex gap-2">
												<input
													type="text"
													bind:value={apNewHitlTool}
													placeholder="Tool name"
													onkeydown={(e: KeyboardEvent) => e.key === 'Enter' && handleAddHitlTool()}
													class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
												/>
												<button
													onclick={handleAddHitlTool}
													class="shrink-0 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:bg-foreground/90"
												>
													Add
												</button>
											</div>
										{/if}
										{#if apRequireHitlFor.length > 0}
											<div class="mt-2 flex flex-wrap gap-1.5">
												{#each apRequireHitlFor as tool}
													<span
														class="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-2 py-1 text-xs font-medium text-amber-600"
													>
														{tool}
														{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
															<button
																onclick={() => handleRemoveHitlTool(tool)}
																class="ml-0.5 hover:text-amber-400">&times;</button
															>
														{/if}
													</span>
												{/each}
											</div>
										{:else}
											<p class="mt-2 text-xs text-muted">No tools require human approval.</p>
										{/if}
									</div>

									<!-- Save button -->
									{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
										<div class="flex justify-end">
											<button
												onclick={handleSaveAgentPolicy}
												disabled={apSaving}
												class="rounded-lg bg-foreground px-5 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
											>
												{apSaving ? 'Saving...' : 'Save Agent Policy'}
											</button>
										</div>
									{/if}
								</div>
							{/if}
						</div>

						<!-- Conditional Access Policies -->
						<div class="mt-8 space-y-6">
							<div class="flex items-start justify-between">
								<div>
									<h3 class="text-sm font-medium text-foreground">Conditional Access Policies</h3>
									<p class="text-xs text-muted">
										Restrict organization access based on IP range, time of day, day of week, or
										user agent. Policies are evaluated in priority order — first match wins.
									</p>
									{#if capYourIp}
										<p class="mt-1 text-xs text-muted">
											Your current IP: <span class="font-mono text-foreground">{capYourIp}</span>
										</p>
									{/if}
								</div>
								{#if (org?.your_role === 'admin' || org?.your_role === 'owner') && !capShowForm}
									<button
										onclick={() => {
											resetCapForm();
											capShowForm = true;
										}}
										class="shrink-0 rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90"
									>
										Add Policy
									</button>
								{/if}
							</div>

							<!-- Policy form -->
							{#if capShowForm && (org?.your_role === 'admin' || org?.your_role === 'owner')}
								<div class="rounded-xl border border-border-subtle bg-surface p-4 space-y-4">
									<h4 class="text-xs font-medium text-foreground">
										{capEditingId ? 'Edit Policy' : 'New Policy'}
									</h4>

									<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
										<div>
											<label for="cap-name" class="mb-1 block text-xs font-medium text-muted"
												>Name</label
											>
											<input
												id="cap-name"
												type="text"
												bind:value={capName}
												placeholder="e.g. Block outside office hours"
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div>
											<label for="cap-action" class="mb-1 block text-xs font-medium text-muted"
												>Action</label
											>
											<select
												id="cap-action"
												bind:value={capAction}
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-accent"
											>
												<option value="block">Block</option>
												<option value="allow">Allow</option>
												<option value="require_mfa">Require MFA</option>
											</select>
										</div>
										<div>
											<label for="cap-priority" class="mb-1 block text-xs font-medium text-muted"
												>Priority (lower = higher)</label
											>
											<input
												id="cap-priority"
												type="number"
												bind:value={capPriority}
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div class="flex items-end gap-2">
											<label class="flex items-center gap-2 text-xs font-medium text-muted">
												<input
													type="checkbox"
													bind:checked={capIsActive}
													class="rounded border-border"
												/>
												Active
											</label>
										</div>
									</div>

									<!-- Conditions -->
									<div>
										<h5 class="mb-2 text-xs font-medium text-foreground">
											Conditions (all must match)
										</h5>
										{#if capConditions.length > 0}
											<div class="mb-3 flex flex-wrap gap-1.5">
												{#each capConditions as cond, i}
													<span
														class="inline-flex items-center gap-1 rounded-md bg-foreground/5 px-2 py-1 text-xs font-medium text-foreground dark:bg-white/10"
													>
														{conditionLabel(cond)}
														<button
															onclick={() => handleRemoveCondition(i)}
															class="ml-0.5 hover:text-red-500">&times;</button
														>
													</span>
												{/each}
											</div>
										{:else}
											<p class="mb-3 text-xs text-muted">
												No conditions — policy will match all requests.
											</p>
										{/if}

										<!-- Add condition -->
										<div class="rounded-lg border border-border-subtle bg-background p-3 space-y-2">
											<div class="flex gap-2 items-end">
												<div>
													<label
														for="cap-cond-type"
														class="mb-1 block text-xs font-medium text-muted">Type</label
													>
													<select
														id="cap-cond-type"
														bind:value={capCondType}
														class="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
													>
														<option value="ip_range">IP Range</option>
														<option value="time_of_day">Time of Day</option>
														<option value="day_of_week">Day of Week</option>
														<option value="user_agent_pattern">User Agent</option>
													</select>
												</div>
												{#if capCondType === 'ip_range'}
													<div class="flex-1">
														<label for="cap-cidr" class="mb-1 block text-xs font-medium text-muted"
															>CIDR</label
														>
														<input
															id="cap-cidr"
															type="text"
															bind:value={capCondCidr}
															placeholder="e.g. 10.0.0.0/24"
															class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none focus:border-accent"
														/>
													</div>
												{:else if capCondType === 'time_of_day'}
													<div>
														<label for="cap-start" class="mb-1 block text-xs font-medium text-muted"
															>Start Hour</label
														>
														<input
															id="cap-start"
															type="number"
															min="0"
															max="23"
															bind:value={capCondStartHour}
															class="w-20 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
														/>
													</div>
													<div>
														<label for="cap-end" class="mb-1 block text-xs font-medium text-muted"
															>End Hour</label
														>
														<input
															id="cap-end"
															type="number"
															min="0"
															max="23"
															bind:value={capCondEndHour}
															class="w-20 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-accent"
														/>
													</div>
													<div>
														<label for="cap-tz" class="mb-1 block text-xs font-medium text-muted"
															>Timezone</label
														>
														<input
															id="cap-tz"
															type="text"
															bind:value={capCondTimezone}
															placeholder="UTC"
															class="w-32 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none focus:border-accent"
														/>
													</div>
												{:else if capCondType === 'day_of_week'}
													<div class="flex-1">
														<label class="mb-1 block text-xs font-medium text-muted">Days</label>
														<div class="flex gap-1">
															{#each DAY_NAMES as day, i}
																<button
																	type="button"
																	onclick={() => handleToggleDay(i)}
																	class="rounded-md px-2 py-1 text-xs font-medium transition-colors {capCondDays.includes(
																		i
																	)
																		? 'bg-foreground text-background'
																		: 'bg-surface text-muted hover:bg-foreground/10'}"
																>
																	{day}
																</button>
															{/each}
														</div>
													</div>
												{:else if capCondType === 'user_agent_pattern'}
													<div class="flex-1">
														<label for="cap-ua" class="mb-1 block text-xs font-medium text-muted"
															>Regex Pattern</label
														>
														<input
															id="cap-ua"
															type="text"
															bind:value={capCondPattern}
															placeholder="e.g. .*Mobile.*"
															class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none focus:border-accent"
														/>
													</div>
												{/if}
												<button
													type="button"
													onclick={handleAddCondition}
													class="shrink-0 rounded-lg bg-surface px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-foreground/10"
												>
													Add
												</button>
											</div>
										</div>
									</div>

									<!-- Self-lockout warning -->
									{#if capAction === 'block' && capConditions.length === 0}
										<p class="text-xs text-amber-600 dark:text-amber-400">
											Warning: A block policy with no conditions will block ALL access to this
											organization, including your own.
										</p>
									{/if}
									{#if capAction === 'block' && capConditions.some((c) => c.type === 'ip_range') && capYourIp}
										<p class="text-xs text-amber-600 dark:text-amber-400">
											Your IP ({capYourIp}) — make sure it won't be blocked by this policy.
										</p>
									{/if}

									<!-- Form actions -->
									<div class="flex gap-2 justify-end">
										<button
											onclick={() => {
												capShowForm = false;
												resetCapForm();
											}}
											class="rounded-lg px-4 py-2 text-xs font-medium text-muted transition-colors hover:bg-surface"
										>
											Cancel
										</button>
										<button
											onclick={handleSavePolicy}
											disabled={capSaving || !capName.trim()}
											class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
										>
											{capSaving ? 'Saving...' : capEditingId ? 'Update Policy' : 'Create Policy'}
										</button>
									</div>
								</div>
							{/if}

							<!-- Policy list -->
							{#if capLoading}
								<div class="flex justify-center py-8">
									<svg
										class="h-5 w-5 animate-spin text-muted"
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
									>
										<circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
										></circle>
										<path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path>
									</svg>
								</div>
							{:else if capPolicies.length === 0}
								<div class="py-8 text-center">
									<p class="text-sm text-muted">No conditional access policies configured.</p>
									<p class="mt-1 text-xs text-subtle">All access conditions are unrestricted.</p>
								</div>
							{:else}
								<div class="rounded-xl border border-border">
									{#each capPolicies as policy, i (policy.id)}
										<div
											class="flex items-center justify-between px-4 py-3 {i < capPolicies.length - 1
												? 'border-b border-border-subtle'
												: ''}"
										>
											<div class="min-w-0 flex-1">
												<div class="flex items-center gap-2">
													<p class="text-sm font-medium text-foreground">{policy.name}</p>
													<span
														class="rounded-lg px-2 py-0.5 text-xs font-medium {policy.action ===
														'block'
															? 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
															: policy.action === 'allow'
																? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
																: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400'}"
													>
														{policy.action === 'require_mfa' ? 'MFA' : policy.action}
													</span>
													<span
														class="rounded-lg px-2 py-0.5 text-xs font-medium {policy.is_active
															? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
															: 'bg-surface text-muted'}"
													>
														{policy.is_active ? 'Active' : 'Inactive'}
													</span>
													<span class="text-xs text-subtle">Priority: {policy.priority}</span>
												</div>
												{#if policy.conditions.length > 0}
													<div class="mt-1 flex flex-wrap gap-1">
														{#each policy.conditions as cond}
															<span class="rounded bg-surface px-1.5 py-0.5 text-xs text-muted"
																>{conditionLabel(cond)}</span
															>
														{/each}
													</div>
												{:else}
													<p class="mt-0.5 text-xs text-muted">
														No conditions (matches all requests)
													</p>
												{/if}
											</div>
											{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
												<div class="ml-3 flex shrink-0 gap-1">
													<button
														onclick={() => handleEditPolicy(policy)}
														class="rounded-lg px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-surface"
													>
														Edit
													</button>
													<button
														onclick={() => handleDeletePolicy(policy.id)}
														disabled={capDeletingId === policy.id}
														class="rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-900/20"
													>
														{capDeletingId === policy.id ? 'Deleting...' : 'Delete'}
													</button>
												</div>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</div>

						<!-- Security Policy sub-section -->
						{#if org}
							<div class="mt-8 border-t border-border-subtle pt-6">
								<SecurityPolicySection {orgId} {org} />
							</div>
						{/if}

						<!-- DLP Policy sub-section -->
						{#if org}
							<div class="mt-8 border-t border-border-subtle pt-6">
								<DlpPolicySection {orgId} {org} />
							</div>
						{/if}

						<!-- Force Logout sub-section -->
						{#if org}
							<div class="mt-8 border-t border-border-subtle pt-6">
								<ForceLogoutSection {orgId} {org} />
							</div>
						{/if}
					{:else if activeTab === 'ip-allowlist'}
						<IPAllowlistSection {orgId} />
					{:else if activeTab === 'access-policies'}
						<AccessPoliciesSection {orgId} />
					{:else if activeTab === 'integrations'}
						<!-- Integrations Tab -->
						<div class="space-y-8">
							<!-- Slack Integration -->
							<section>
								<div class="mb-4">
									<h3 class="text-sm font-medium text-foreground">Slack</h3>
									<p class="text-xs text-muted">
										Forward notifications to a Slack channel via incoming webhook.
									</p>
								</div>

								{#if slackLoading}
									<div class="flex items-center justify-center py-6">
										<svg
											class="h-5 w-5 animate-spin text-muted"
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											><circle
												class="opacity-25"
												cx="12"
												cy="12"
												r="10"
												stroke="currentColor"
												stroke-width="4"
											></circle><path
												class="opacity-75"
												fill="currentColor"
												d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
											></path></svg
										>
									</div>
								{:else}
									<div class="space-y-3">
										<div>
											<label
												for="slack-webhook-url"
												class="mb-1 block text-xs font-medium text-foreground">Webhook URL</label
											>
											<input
												id="slack-webhook-url"
												type="url"
												bind:value={slackWebhookUrl}
												placeholder="https://hooks.slack.com/services/..."
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div>
											<label
												for="slack-channel"
												class="mb-1 block text-xs font-medium text-foreground"
												>Channel name (optional)</label
											>
											<input
												id="slack-channel"
												type="text"
												bind:value={slackChannelName}
												placeholder="#general"
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<label for="slack-active" class="flex cursor-pointer items-center gap-2">
											<div class="relative shrink-0">
												<input
													id="slack-active"
													type="checkbox"
													role="switch"
													bind:checked={slackActive}
													class="peer sr-only"
												/>
												<div
													class="h-5 w-9 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
												></div>
												<div
													class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-4"
												></div>
											</div>
											<span class="text-xs text-subtle">Active</span>
										</label>
										<div class="flex items-center gap-2 pt-1">
											<button
												onclick={handleSaveSlack}
												disabled={slackSaving}
												class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
												>{slackSaving ? 'Saving...' : slackExists ? 'Update' : 'Save'}</button
											>
											{#if slackExists}
												<button
													onclick={handleTestSlack}
													disabled={slackTesting}
													class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-50"
													>{slackTesting ? 'Sending...' : 'Test'}</button
												>
												<button
													onclick={handleDeleteSlack}
													class="rounded-lg border border-red-200 px-4 py-2 text-xs font-medium text-red-600 transition-all duration-200 hover:bg-red-50 dark:border-red-900/30 dark:text-red-400 dark:hover:bg-red-900/20"
													>Remove</button
												>
											{/if}
										</div>
										{#if slackTestResult}
											<p
												class="text-xs {slackTestResult.ok
													? 'text-success'
													: 'text-red-600 dark:text-red-400'}"
											>
												{slackTestResult.message}
											</p>
										{/if}
									</div>
								{/if}
							</section>

							<!-- Discord Integration -->
							<section class="border-t border-border-subtle pt-6">
								<div class="mb-4">
									<h3 class="text-sm font-medium text-foreground">Discord</h3>
									<p class="text-xs text-muted">
										Forward notifications to a Discord channel via webhook.
									</p>
								</div>

								{#if discordLoading}
									<div class="flex items-center justify-center py-6">
										<svg
											class="h-5 w-5 animate-spin text-muted"
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											><circle
												class="opacity-25"
												cx="12"
												cy="12"
												r="10"
												stroke="currentColor"
												stroke-width="4"
											></circle><path
												class="opacity-75"
												fill="currentColor"
												d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
											></path></svg
										>
									</div>
								{:else}
									<div class="space-y-3">
										<div>
											<label
												for="discord-webhook-url"
												class="mb-1 block text-xs font-medium text-foreground">Webhook URL</label
											>
											<input
												id="discord-webhook-url"
												type="url"
												bind:value={discordWebhookUrl}
												placeholder="https://discord.com/api/webhooks/..."
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div>
											<label
												for="discord-channel"
												class="mb-1 block text-xs font-medium text-foreground"
												>Channel name (optional)</label
											>
											<input
												id="discord-channel"
												type="text"
												bind:value={discordChannelName}
												placeholder="#general"
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<label for="discord-active" class="flex cursor-pointer items-center gap-2">
											<div class="relative shrink-0">
												<input
													id="discord-active"
													type="checkbox"
													role="switch"
													bind:checked={discordActive}
													class="peer sr-only"
												/>
												<div
													class="h-5 w-9 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
												></div>
												<div
													class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-4"
												></div>
											</div>
											<span class="text-xs text-subtle">Active</span>
										</label>
										<div class="flex items-center gap-2 pt-1">
											<button
												onclick={handleSaveDiscord}
												disabled={discordSaving}
												class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
												>{discordSaving ? 'Saving...' : discordExists ? 'Update' : 'Save'}</button
											>
											{#if discordExists}
												<button
													onclick={handleTestDiscord}
													disabled={discordTesting}
													class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-50"
													>{discordTesting ? 'Sending...' : 'Test'}</button
												>
												<button
													onclick={handleDeleteDiscord}
													class="rounded-lg border border-red-200 px-4 py-2 text-xs font-medium text-red-600 transition-all duration-200 hover:bg-red-50 dark:border-red-900/30 dark:text-red-400 dark:hover:bg-red-900/20"
													>Remove</button
												>
											{/if}
										</div>
										{#if discordTestResult}
											<p
												class="text-xs {discordTestResult.ok
													? 'text-success'
													: 'text-red-600 dark:text-red-400'}"
											>
												{discordTestResult.message}
											</p>
										{/if}
									</div>
								{/if}
							</section>
						</div>
					{:else if activeTab === 'templates'}
						<!-- Templates Tab -->
						<div class="space-y-4">
							<div class="flex items-center justify-between">
								<div>
									<h3 class="text-sm font-medium text-foreground">Project Templates</h3>
									<p class="text-xs text-muted">Create reusable templates for new projects.</p>
								</div>
								{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
									<button
										onclick={() => openTemplateForm()}
										class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90"
									>
										New Template
									</button>
								{/if}
							</div>

							{#if tmplLoading}
								<div class="flex justify-center py-8">
									<svg
										class="h-5 w-5 animate-spin text-muted"
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
									>
										<circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
										></circle>
										<path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path>
									</svg>
								</div>
							{:else if tmplList.length === 0}
								<p class="py-8 text-center text-sm text-muted">
									No templates yet. Create one to get started.
								</p>
							{:else}
								<div class="rounded-xl border border-border">
									{#each tmplList as tmpl, i (tmpl.id)}
										<div
											class="flex items-center justify-between px-4 py-3 {i < tmplList.length - 1
												? 'border-b border-border-subtle'
												: ''}"
										>
											<div class="min-w-0 flex-1">
												<p class="text-sm font-medium text-foreground">
													{tmpl.icon ? `${tmpl.icon} ` : ''}{tmpl.name}
												</p>
												{#if tmpl.description}
													<p class="mt-0.5 truncate text-xs text-muted">{tmpl.description}</p>
												{/if}
												<p class="mt-0.5 text-xs text-subtle">
													{tmpl.files.length} file{tmpl.files.length !== 1 ? 's' : ''}
												</p>
											</div>
											{#if org?.your_role === 'admin' || org?.your_role === 'owner'}
												<div class="ml-3 flex shrink-0 gap-1">
													<button
														onclick={() => openTemplateForm(tmpl)}
														class="rounded-lg px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
													>
														Edit
													</button>
													<button
														onclick={() => handleDeleteTemplate(tmpl.id)}
														disabled={tmplDeletingId === tmpl.id}
														class="rounded-lg px-3 py-1.5 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-900/20"
													>
														{tmplDeletingId === tmpl.id ? 'Deleting...' : 'Delete'}
													</button>
												</div>
											{/if}
										</div>
									{/each}
								</div>
							{/if}

							<!-- Template Create/Edit Form (inline) -->
							{#if tmplShowForm}
								<div
									class="rounded-xl border border-border-subtle bg-surface p-4"
									in:fade={{ duration: 100 }}
								>
									<h4 class="mb-3 text-sm font-medium text-foreground">
										{tmplEditing ? 'Edit Template' : 'New Template'}
									</h4>
									<div class="space-y-3">
										<div class="flex flex-col gap-1.5">
											<label for="tmpl-name" class="text-xs font-medium text-muted">Name</label>
											<input
												id="tmpl-name"
												type="text"
												bind:value={tmplName}
												placeholder="Template name"
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div class="flex flex-col gap-1.5">
											<label for="tmpl-desc" class="text-xs font-medium text-muted"
												>Description</label
											>
											<input
												id="tmpl-desc"
												type="text"
												bind:value={tmplDescription}
												placeholder="Brief description"
												class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div class="flex flex-col gap-1.5">
											<label for="tmpl-icon" class="text-xs font-medium text-muted">Icon</label>
											<input
												id="tmpl-icon"
												type="text"
												bind:value={tmplIcon}
												placeholder="e.g. 🚀"
												maxlength="4"
												class="w-20 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											/>
										</div>
										<div class="flex flex-col gap-1.5">
											<label for="tmpl-instructions" class="text-xs font-medium text-muted"
												>Custom Instructions</label
											>
											<textarea
												id="tmpl-instructions"
												bind:value={tmplInstructions}
												rows="3"
												placeholder="Instructions applied to projects created from this template"
												class="w-full resize-y rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder-muted outline-none transition-colors focus:border-accent"
											></textarea>
										</div>

										<!-- Template Files -->
										<div class="flex flex-col gap-1.5">
											<div class="flex items-center justify-between">
												<label class="text-xs font-medium text-muted">Files</label>
												<button
													type="button"
													onclick={addTemplateFile}
													class="text-xs font-medium text-accent hover:underline">+ Add file</button
												>
											</div>
											{#each tmplFiles as file, idx (idx)}
												<div class="flex gap-2">
													<input
														type="text"
														bind:value={file.file_name}
														placeholder="filename.txt"
														class="w-1/3 rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder-muted outline-none focus:border-accent"
													/>
													<textarea
														bind:value={file.file_content}
														placeholder="File content"
														rows="2"
														class="flex-1 resize-y rounded-lg border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder-muted outline-none focus:border-accent"
													></textarea>
													<button
														type="button"
														onclick={() => removeTemplateFile(idx)}
														class="shrink-0 text-xs text-red-500 hover:text-red-700">&times;</button
													>
												</div>
											{/each}
										</div>

										<div class="flex items-center gap-2 pt-1">
											<button
												onclick={handleSaveTemplate}
												disabled={tmplSaving || !tmplName.trim()}
												class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
												>{tmplSaving ? 'Saving...' : tmplEditing ? 'Update' : 'Create'}</button
											>
											<button
												onclick={closeTemplateForm}
												class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
												>Cancel</button
											>
										</div>
									</div>
								</div>
							{/if}
						</div>
					{:else if activeTab === 'analytics'}
						<!-- Analytics Tab -->
						<div class="space-y-6">
							<!-- Period selector -->
							<div class="flex flex-wrap items-end gap-3">
								<div>
									<label for="analytics-period" class="mb-1 block text-xs font-medium text-muted"
										>Period</label
									>
									<select
										id="analytics-period"
										bind:value={analyticsPeriod}
										onchange={handleAnalyticsPeriodChange}
										class="rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none"
									>
										<option value="7d">Last 7 days</option>
										<option value="30d">Last 30 days</option>
										<option value="90d">Last 90 days</option>
									</select>
								</div>
								<div>
									<label for="analytics-from" class="mb-1 block text-xs font-medium text-muted"
										>From</label
									>
									<input
										id="analytics-from"
										type="date"
										bind:value={analyticsCustomStart}
										class="rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								</div>
								<div>
									<label for="analytics-to" class="mb-1 block text-xs font-medium text-muted"
										>To</label
									>
									<input
										id="analytics-to"
										type="date"
										bind:value={analyticsCustomEnd}
										class="rounded-xl border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								</div>
								<button
									onclick={handleAnalyticsCustomRange}
									disabled={!analyticsCustomStart || !analyticsCustomEnd}
									class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90 disabled:opacity-50"
								>
									Apply
								</button>
							</div>

							{#if analyticsLoading}
								<div class="flex justify-center py-8">
									<svg
										class="h-5 w-5 animate-spin text-muted"
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
									>
										<circle
											class="opacity-25"
											cx="12"
											cy="12"
											r="10"
											stroke="currentColor"
											stroke-width="4"
										></circle>
										<path
											class="opacity-75"
											fill="currentColor"
											d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
										></path>
									</svg>
								</div>
							{:else if analyticsSummary}
								<!-- Summary cards -->
								<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
									<div class="rounded-xl border border-border p-4">
										<p class="text-xs font-medium text-muted">Agent Runs</p>
										<p class="mt-1 text-2xl font-medium text-foreground">
											{analyticsSummary.total_agent_runs.toLocaleString()}
										</p>
									</div>
									<div class="rounded-xl border border-border p-4">
										<p class="text-xs font-medium text-muted">Credits Consumed</p>
										<p class="mt-1 text-2xl font-medium text-foreground">
											{analyticsSummary.total_credits_consumed.toLocaleString()}
										</p>
									</div>
									<div class="rounded-xl border border-border p-4">
										<p class="text-xs font-medium text-muted">Active Members</p>
										<p class="mt-1 text-2xl font-medium text-foreground">
											{analyticsSummary.active_members.toLocaleString()}
										</p>
									</div>
									<div class="rounded-xl border border-border p-4">
										<p class="text-xs font-medium text-muted">Conversations</p>
										<p class="mt-1 text-2xl font-medium text-foreground">
											{analyticsSummary.total_conversations.toLocaleString()}
										</p>
									</div>
								</div>

								<!-- Member analytics table -->
								<div>
									<div class="mb-3 flex items-center justify-between">
										<h3 class="text-sm font-medium text-foreground">Member Usage</h3>
										<button
											onclick={handleExportMembersCsv}
											class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
										>
											Export CSV
										</button>
									</div>
									{#if analyticsMembers && analyticsMembers.results.length > 0}
										<div class="overflow-x-auto rounded-xl border border-border">
											<table class="w-full text-left text-sm">
												<thead>
													<tr class="border-b border-border-subtle bg-surface">
														<th class="px-4 py-2.5 text-xs font-medium text-muted">Member</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleMemberSort('agent_runs_count')}
														>
															Runs{sortIndicator('agent_runs_count', memberSortBy, memberSortOrder)}
														</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleMemberSort('credits_consumed')}
														>
															Credits{sortIndicator(
																'credits_consumed',
																memberSortBy,
																memberSortOrder
															)}
														</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleMemberSort('conversations_count')}
														>
															Conversations{sortIndicator(
																'conversations_count',
																memberSortBy,
																memberSortOrder
															)}
														</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleMemberSort('last_active')}
														>
															Last Active{sortIndicator(
																'last_active',
																memberSortBy,
																memberSortOrder
															)}
														</th>
													</tr>
												</thead>
												<tbody>
													{#each analyticsMembers.results as entry (entry.email)}
														<tr class="border-b border-border-subtle last:border-0">
															<td class="px-4 py-2.5">
																<p class="text-xs font-medium text-foreground">
																	{entry.name || entry.email}
																</p>
																<p class="text-xs text-muted">{entry.email}</p>
															</td>
															<td class="px-4 py-2.5 text-xs text-foreground"
																>{entry.agent_runs_count.toLocaleString()}</td
															>
															<td class="px-4 py-2.5 text-xs text-foreground"
																>{entry.credits_consumed.toLocaleString()}</td
															>
															<td class="px-4 py-2.5 text-xs text-foreground"
																>{entry.conversations_count.toLocaleString()}</td
															>
															<td class="px-4 py-2.5 text-xs text-muted"
																>{entry.last_active ? formatDate(entry.last_active) : '—'}</td
															>
														</tr>
													{/each}
												</tbody>
											</table>
										</div>
										{#if analyticsMembers.total_pages > 1}
											<div class="mt-3 flex items-center justify-between">
												<p class="text-xs text-muted">
													Page {analyticsMembers.page} of {analyticsMembers.total_pages} ({analyticsMembers.total}
													total)
												</p>
												<div class="flex gap-2">
													<button
														onclick={() => handleMemberPage(analyticsMembers!.page - 1)}
														disabled={analyticsMembers.page <= 1}
														class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-50"
														>Previous</button
													>
													<button
														onclick={() => handleMemberPage(analyticsMembers!.page + 1)}
														disabled={analyticsMembers.page >= analyticsMembers.total_pages}
														class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-50"
														>Next</button
													>
												</div>
											</div>
										{/if}
									{:else}
										<p class="py-4 text-center text-sm text-muted">
											No member activity in this period.
										</p>
									{/if}
								</div>

								<!-- Project analytics table -->
								<div>
									<div class="mb-3 flex items-center justify-between">
										<h3 class="text-sm font-medium text-foreground">Project Usage</h3>
										<button
											onclick={handleExportProjectsCsv}
											class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
										>
											Export CSV
										</button>
									</div>
									{#if analyticsProjects && analyticsProjects.results.length > 0}
										<div class="overflow-x-auto rounded-xl border border-border">
											<table class="w-full text-left text-sm">
												<thead>
													<tr class="border-b border-border-subtle bg-surface">
														<th class="px-4 py-2.5 text-xs font-medium text-muted">Project</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleProjectSort('agent_runs')}
														>
															Runs{sortIndicator('agent_runs', projectSortBy, projectSortOrder)}
														</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleProjectSort('credits_consumed')}
														>
															Credits{sortIndicator(
																'credits_consumed',
																projectSortBy,
																projectSortOrder
															)}
														</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleProjectSort('unique_users')}
														>
															Users{sortIndicator('unique_users', projectSortBy, projectSortOrder)}
														</th>
														<th
															class="cursor-pointer px-4 py-2.5 text-xs font-medium text-muted"
															onclick={() => handleProjectSort('last_activity')}
														>
															Last Activity{sortIndicator(
																'last_activity',
																projectSortBy,
																projectSortOrder
															)}
														</th>
													</tr>
												</thead>
												<tbody>
													{#each analyticsProjects.results as entry (entry.project_id)}
														<tr class="border-b border-border-subtle last:border-0">
															<td class="px-4 py-2.5">
																<p class="text-xs font-medium text-foreground">
																	{entry.title}{entry.note ? ` ${entry.note}` : ''}
																</p>
															</td>
															<td class="px-4 py-2.5 text-xs text-foreground"
																>{entry.agent_runs.toLocaleString()}</td
															>
															<td class="px-4 py-2.5 text-xs text-foreground"
																>{entry.credits_consumed.toLocaleString()}</td
															>
															<td class="px-4 py-2.5 text-xs text-foreground"
																>{entry.unique_users.toLocaleString()}</td
															>
															<td class="px-4 py-2.5 text-xs text-muted"
																>{entry.last_activity ? formatDate(entry.last_activity) : '—'}</td
															>
														</tr>
													{/each}
												</tbody>
											</table>
										</div>
										{#if analyticsProjects.total_pages > 1}
											<div class="mt-3 flex items-center justify-between">
												<p class="text-xs text-muted">
													Page {analyticsProjects.page} of {analyticsProjects.total_pages} ({analyticsProjects.total}
													total)
												</p>
												<div class="flex gap-2">
													<button
														onclick={() => handleProjectPage(analyticsProjects!.page - 1)}
														disabled={analyticsProjects.page <= 1}
														class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-50"
														>Previous</button
													>
													<button
														onclick={() => handleProjectPage(analyticsProjects!.page + 1)}
														disabled={analyticsProjects.page >= analyticsProjects.total_pages}
														class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2 disabled:opacity-50"
														>Next</button
													>
												</div>
											</div>
										{/if}
									{:else}
										<p class="py-4 text-center text-sm text-muted">
											No project activity in this period.
										</p>
									{/if}
								</div>
							{:else}
								<p class="py-8 text-center text-sm text-muted">
									Analytics data unavailable. You may not have permission to view this data.
								</p>
							{/if}
						</div>
					{:else if activeTab === 'webhooks'}
						{#if org}
							<WebhooksTab {orgId} {org} />
						{/if}
					{:else if activeTab === 'api-keys'}
						{#if org}
							<ApiKeysTab {orgId} {org} />
						{/if}
					{:else if activeTab === 'billing'}
						{#if org}
							<CostPolicySection {orgId} {org} />
						{/if}
					{:else if activeTab === 'general'}
						{#if org}
							<OrgLifecycleSection {orgId} {org} />
						{/if}
					{/if}
				</div>
			{/key}
		</div>
	</div>

	<!-- Enforce SSO Confirmation Dialog -->
	{#if showEnforceConfirm}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40"
			onclick={(e) => {
				if (e.target === e.currentTarget) showEnforceConfirm = false;
			}}
			onkeydown={(e) => {
				if (e.key === 'Escape') showEnforceConfirm = false;
			}}
		>
			<div
				class="mx-4 w-full max-w-md rounded-2xl border border-border bg-background p-6 shadow-xl"
				in:fade={{ duration: 100 }}
			>
				<h3 class="text-base font-medium text-foreground">Enforce SSO?</h3>
				<p class="mt-2 text-sm text-muted">
					Enabling SSO enforcement will <strong>block password and OAuth login</strong> for all members
					of this organization. Only users who authenticate via SSO will be able to access their accounts.
				</p>
				<p class="mt-2 text-sm text-muted">
					Make sure your IdP is properly configured before enabling this.
				</p>
				<div class="mt-4 flex justify-end gap-2">
					<button
						onclick={() => (showEnforceConfirm = false)}
						class="rounded-lg border border-border px-4 py-2 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
					>
						Cancel
					</button>
					<button
						onclick={confirmEnforce}
						class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all duration-200 hover:bg-foreground/90"
					>
						Enable Enforcement
					</button>
				</div>
			</div>
		</div>
	{/if}
{/if}
