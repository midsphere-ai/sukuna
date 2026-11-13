<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { settingsOpen, closeSettings, loadSettings, settingsLoading } from '$stores/settings';
	import GeneralSection from './GeneralSection.svelte';
	import CustomiseSection from './CustomiseSection.svelte';
	import AdvancedSection from './AdvancedSection.svelte';
	import AccountSection from './AccountSection.svelte';
	import NotificationsSection from './NotificationsSection.svelte';
	import DataControlsSection from './DataControlsSection.svelte';
	import DeveloperSection from './DeveloperSection.svelte';
	import ModelsSection from './ModelsSection.svelte';
	import EnterpriseSection from './EnterpriseSection.svelte';
	import MFASection from './MFASection.svelte';
	import InfoButton from '$components/ui/InfoButton.svelte';
	import { tooltip } from '$lib/actions/tooltip';

	type SettingsSection =
		| 'general'
		| 'customise'
		| 'account'
		| 'security'
		| 'notifications'
		| 'data'
		| 'developer'
		| 'models'
		| 'enterprise'
		| 'advanced';

	let activeSection: SettingsSection = $state('general');
	let mobileActiveSection: SettingsSection | null = $state(null);
	let dialogEl: HTMLDialogElement | undefined = $state();
	let closing = $state(false);

	const allSections: { id: SettingsSection; label: string; icon: string; description: string }[] = [
		{ id: 'general', label: 'General', icon: 'palette', description: 'Theme, appearance' },
		{
			id: 'customise',
			label: 'Customise',
			icon: 'sliders',
			description: 'Instructions, tools, persona'
		},
		{ id: 'account', label: 'Account', icon: 'user', description: 'Profile, password, security' },
		{
			id: 'security',
			label: 'Security',
			icon: 'shield',
			description: 'Two-factor authentication'
		},
		{
			id: 'notifications',
			label: 'Notifications',
			icon: 'bell',
			description: 'Alerts, sounds, badges'
		},
		{ id: 'data', label: 'Data Controls', icon: 'shield', description: 'Privacy, data export' },
		{ id: 'developer', label: 'API Keys', icon: 'key', description: 'Developer access tokens' },
		{ id: 'models', label: 'Models', icon: 'cpu', description: 'Custom LLM providers' },
		{
			id: 'enterprise',
			label: 'Enterprise',
			icon: 'building',
			description: 'Teams, orgs, SSO, SCIM'
		},
		{ id: 'advanced', label: 'Advanced', icon: 'code', description: 'Debug, experimental' }
	];

	const sections = allSections;

	function openMobileSection(id: SettingsSection): void {
		activeSection = id;
		mobileActiveSection = id;
	}

	function mobileBack(): void {
		mobileActiveSection = null;
		activeSection = 'general';
	}

	const mobileActiveSectionLabel = $derived(
		sections.find((s) => s.id === mobileActiveSection)?.label ?? ''
	);

	function close(): void {
		closing = true;
		setTimeout(() => {
			closing = false;
			closeSettings();
		}, 150);
	}

	function handleBackdropClick(e: MouseEvent): void {
		if (e.target === dialogEl) {
			close();
		}
	}

	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	$effect(() => {
		if (!dialogEl) return;
		if ($settingsOpen && !dialogEl.open) {
			dialogEl.showModal();
			loadSettings();
		} else if (!$settingsOpen && dialogEl.open) {
			dialogEl.close();
			activeSection = 'general';
			mobileActiveSection = null;
		}
	});

	function getSectionIcon(icon: string): string {
		switch (icon) {
			case 'palette':
				return 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1.01-.23-.26-.38-.61-.38-1 0-.83.67-1.5 1.5-1.5H16c3.31 0 6-2.69 6-6 0-4.96-4.49-9-10-9z';
			case 'sliders':
				return 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6';
			case 'user':
				return 'M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 3a4 4 0 100 8 4 4 0 000-8z';
			case 'bell':
				return 'M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0';
			case 'shield':
				return 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z';
			case 'clock':
				return 'M12 2a10 10 0 100 20 10 10 0 000-20zM12 6v6l4 2';
			case 'key':
				return 'M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4';
			case 'cpu':
				return 'M9 3v2m6-2v2M9 19v2m6-2v2M3 9h2m-2 6h2m14-6h2m-2 6h2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z';
			case 'building':
				return 'M6 22V4a2 2 0 012-2h8a2 2 0 012 2v18M2 22h20M10 7h.01M14 7h.01M10 11h.01M14 11h.01M10 15h.01M14 15h.01';
			case 'code':
				return 'M16 18l6-6-6-6M8 6l-6 6 6 6';
			default:
				return '';
		}
	}

	onMount(() => {
		// On mount, if open was already true (e.g., from store), show the dialog
		if ($settingsOpen && dialogEl && !dialogEl.open) {
			dialogEl.showModal();
			loadSettings();
		}
	});
</script>

<!-- Desktop: modal dialog; Mobile: full-screen overlay -->
<dialog
	bind:this={dialogEl}
	class="animate-dialog fixed inset-0 m-auto h-[62vh] w-full max-w-3xl rounded-2xl border border-border-subtle bg-surface-2 p-0 shadow-xl backdrop:bg-foreground/40 open:flex open:flex-col max-lg:h-full max-lg:max-h-full max-lg:max-w-full max-lg:rounded-none max-lg:border-0"
	class:closing
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
>
	{#if $settingsOpen}
		<div class="flex h-full min-h-0 flex-col overflow-hidden lg:flex-row">
			<!-- Sidebar / Header navigation -->
			<!-- Desktop: left sidebar -->
			<nav class="hidden w-56 shrink-0 flex-col border-r border-border-subtle bg-surface lg:flex">
				<div class="flex h-14 items-center gap-2 px-5">
					<h2 class="text-base font-medium text-foreground">Settings</h2>
					<InfoButton context="settings" />
				</div>
				<div class="flex flex-col gap-0.5 px-3 py-1">
					{#each sections as section (section.id)}
						<button
							onclick={() => (activeSection = section.id)}
							class="flex items-center gap-3 rounded-xl px-3 py-1.5 text-[14px] leading-[1.2] transition-all duration-200 {activeSection ===
							section.id
								? 'bg-surface-2 font-medium text-foreground'
								: 'text-foreground hover:bg-surface-2'}"
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
								class="shrink-0"
							>
								<path d={getSectionIcon(section.icon)} />
							</svg>
							{section.label}
						</button>
					{/each}
				</div>
			</nav>

			<!-- Mobile: multi-page navigation -->
			<div class="mobile-settings-container relative flex-1 overflow-hidden lg:hidden">
				<!-- Main list page -->
				<div
					class="mobile-page absolute inset-0 flex flex-col bg-background"
					class:mobile-page-active={mobileActiveSection === null}
					class:mobile-page-left={mobileActiveSection !== null}
				>
					<!-- Header -->
					<div class="flex h-14 shrink-0 items-center gap-3 border-b border-border-subtle px-4">
						<button
							onclick={close}
							class="flex h-8 w-8 items-center justify-center rounded-xl text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
							aria-label="Close settings"
							use:tooltip={{ text: 'Close', shortcut: 'Esc' }}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="20"
								height="20"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M15 18l-6-6 6-6" />
							</svg>
						</button>
						<h2 class="text-base font-medium text-foreground">Settings</h2>
						<InfoButton context="settings" />
					</div>
					<!-- Category list -->
					<div class="flex-1 overflow-y-auto">
						{#each sections as section (section.id)}
							<button
								onclick={() => openMobileSection(section.id)}
								class="flex w-full items-center gap-3.5 px-5 py-3.5 text-left transition-colors duration-150 active:bg-surface"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="20"
									height="20"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.75"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="shrink-0 text-muted"
								>
									<path d={getSectionIcon(section.icon)} />
								</svg>
								<div class="min-w-0 flex-1">
									<div class="text-[15px] font-medium text-foreground">{section.label}</div>
									<div class="mt-0.5 text-xs text-muted">{section.description}</div>
								</div>
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
									class="shrink-0 text-muted"
								>
									<path d="M9 18l6-6-6-6" />
								</svg>
							</button>
						{/each}
					</div>
				</div>

				<!-- Sub-page -->
				<div
					class="mobile-page absolute inset-0 flex flex-col bg-background"
					class:mobile-page-active={mobileActiveSection !== null}
					class:mobile-page-right={mobileActiveSection === null}
				>
					<!-- Header -->
					<div class="flex h-14 shrink-0 items-center gap-3 border-b border-border-subtle px-5">
						<button
							onclick={mobileBack}
							class="flex h-8 w-8 items-center justify-center rounded-xl text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
							aria-label="Back to settings"
							use:tooltip={'Back'}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="20"
								height="20"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M15 18l-6-6 6-6" />
							</svg>
						</button>
						<h2 class="text-base font-medium text-foreground">{mobileActiveSectionLabel}</h2>
					</div>
					<!-- Section content -->
					<div class="flex-1 overflow-y-auto px-8 pb-8 pt-2">
						{#if $settingsLoading}
							<div class="flex items-center justify-center py-16">
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
						{:else if activeSection === 'general'}
							<GeneralSection />
						{:else if activeSection === 'customise'}
							<CustomiseSection />
						{:else if activeSection === 'account'}
							<AccountSection />
						{:else if activeSection === 'security'}
							<MFASection />
						{:else if activeSection === 'notifications'}
							<NotificationsSection />
						{:else if activeSection === 'data'}
							<DataControlsSection />
						{:else if activeSection === 'developer'}
							<DeveloperSection />
						{:else if activeSection === 'models'}
							<ModelsSection />
						{:else if activeSection === 'enterprise'}
							<EnterpriseSection />
						{:else if activeSection === 'advanced'}
							<AdvancedSection />
						{/if}
					</div>
				</div>
			</div>

			<!-- Desktop: content area -->
			<div class="hidden min-h-0 flex-1 flex-col lg:flex">
				<!-- Desktop close button -->
				<div class="flex h-14 shrink-0 items-center justify-end px-5">
					<button
						onclick={close}
						class="flex h-8 w-8 items-center justify-center rounded-xl text-muted transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
						aria-label="Close settings"
						use:tooltip={{ text: 'Close', shortcut: 'Esc' }}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="18"
							height="18"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M18 6L6 18" />
							<path d="M6 6l12 12" />
						</svg>
					</button>
				</div>

				<!-- Section content -->
				<div class="flex-1 overflow-y-auto px-8 pb-6">
					{#if $settingsLoading}
						<div class="flex items-center justify-center py-16">
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
						{#key activeSection}
							<div in:fade={{ duration: 100, delay: 30 }} out:fade={{ duration: 60 }}>
								{#if activeSection === 'general'}
									<GeneralSection />
								{:else if activeSection === 'customise'}
									<CustomiseSection />
								{:else if activeSection === 'account'}
									<AccountSection />
								{:else if activeSection === 'security'}
									<MFASection />
								{:else if activeSection === 'notifications'}
									<NotificationsSection />
								{:else if activeSection === 'data'}
									<DataControlsSection />
								{:else if activeSection === 'developer'}
									<DeveloperSection />
								{:else if activeSection === 'models'}
									<ModelsSection />
								{:else if activeSection === 'enterprise'}
									<EnterpriseSection />
								{:else if activeSection === 'advanced'}
									<AdvancedSection />
								{/if}
							</div>
						{/key}
					{/if}
				</div>
			</div>
		</div>
	{/if}
</dialog>

<style>
	.animate-dialog[open] {
		animation: dialog-in 150ms ease-out;
	}
	.animate-dialog[open]::backdrop {
		animation: backdrop-in 150ms ease-out;
	}
	.animate-dialog.closing {
		animation: dialog-out 150ms ease-in forwards;
	}
	.animate-dialog.closing::backdrop {
		animation: backdrop-out 150ms ease-in forwards;
	}
	@keyframes dialog-in {
		from {
			opacity: 0;
			transform: scale(0.95) translateY(-8px);
		}
		to {
			opacity: 1;
			transform: scale(1) translateY(0);
		}
	}
	@keyframes dialog-out {
		from {
			opacity: 1;
			transform: scale(1) translateY(0);
		}
		to {
			opacity: 0;
			transform: scale(0.95) translateY(-8px);
		}
	}
	@keyframes backdrop-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}
	@keyframes backdrop-out {
		from {
			opacity: 1;
		}
		to {
			opacity: 0;
		}
	}

	/* Mobile multi-page slide transitions */
	.mobile-page {
		transition: transform 200ms ease;
	}
	.mobile-page-active {
		transform: translateX(0);
	}
	.mobile-page-left {
		transform: translateX(-30%);
		pointer-events: none;
	}
	.mobile-page-right {
		transform: translateX(100%);
		pointer-events: none;
	}
</style>
