<script lang="ts">
	import { browser } from '$app/environment';
	import { get } from 'svelte/store';
	import {
		hasConsented,
		consentPreferences,
		acceptAll,
		rejectNonEssential,
		updateConsent
	} from '$stores/consent';
	import Button from './Button.svelte';
	import Dialog from './Dialog.svelte';
	import Toggle from './Toggle.svelte';

	let show = $state(false);
	let customizeOpen = $state(false);

	let analyticsEnabled = $state(false);
	let errorTrackingEnabled = $state(false);

	if (browser) {
		hasConsented.subscribe((consented) => {
			show = !consented;
		});
	}

	function handleAcceptAll(): void {
		acceptAll();
		show = false;
	}

	function handleRejectNonEssential(): void {
		rejectNonEssential();
		show = false;
	}

	function openCustomize(): void {
		const prefs = get(consentPreferences);
		analyticsEnabled = prefs.analytics;
		errorTrackingEnabled = prefs.errorTracking;
		customizeOpen = true;
	}

	function saveCustomPreferences(): void {
		updateConsent({
			analytics: analyticsEnabled,
			errorTracking: errorTrackingEnabled
		});
		customizeOpen = false;
		show = false;
	}
</script>

{#if show}
	<div
		class="fixed inset-x-0 bottom-0 z-50 p-3 sm:p-5 pointer-events-none animate-[slideUp_0.4s_ease-out]"
		role="region"
		aria-label="Cookie consent"
	>
		<div
			class="pointer-events-auto mx-auto max-w-lg rounded-lg border border-border-subtle bg-background shadow-sm p-4 sm:p-5"
		>
			<div class="flex gap-3.5 sm:gap-4">
				<!-- Cookie icon -->
				<div
					class="hidden sm:flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-warning/[0.08] text-accent-warning/60"
				>
					<svg
						width="20"
						height="20"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5" />
						<path d="M8.5 8.5v.01" />
						<path d="M16 15.5v.01" />
						<path d="M12 12v.01" />
						<path d="M11 17v.01" />
						<path d="M7 14v.01" />
					</svg>
				</div>

				<div class="min-w-0 flex-1">
					<p class="text-sm leading-relaxed text-subtle">
						We use cookies to improve your experience and track errors.
					</p>
					<div class="mt-3 flex flex-wrap items-center gap-2">
						<Button variant="primary" class="!py-2 !px-4 !text-xs" onclick={handleAcceptAll}
							>Accept All</Button
						>
						<Button
							variant="bordered"
							class="!py-2 !px-4 !text-xs"
							onclick={handleRejectNonEssential}>Reject</Button
						>
						<Button class="!py-1.5 !px-3 !text-xs" onclick={openCustomize}>Customize</Button>
					</div>
				</div>
			</div>
		</div>
	</div>
{/if}

<Dialog bind:open={customizeOpen}>
	<div class="p-5 sm:p-6">
		<div class="mb-5 flex items-center gap-3">
			<div
				class="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-warning/[0.08] text-accent-warning/60"
			>
				<svg
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5" />
					<path d="M8.5 8.5v.01" />
					<path d="M16 15.5v.01" />
					<path d="M12 12v.01" />
					<path d="M11 17v.01" />
					<path d="M7 14v.01" />
				</svg>
			</div>
			<div>
				<h2 class="text-lg font-normal text-foreground">Cookie settings</h2>
				<p class="text-sm text-subtle">Choose which cookies you'd like to allow.</p>
			</div>
		</div>

		<div class="space-y-2.5">
			<div
				class="flex items-center justify-between rounded-xl border border-border-subtle bg-surface px-4 py-3"
			>
				<div>
					<p class="text-sm font-medium text-foreground">Essential</p>
					<p class="text-xs text-muted">Required for the site to function</p>
				</div>
				<Toggle checked={true} disabled={true} />
			</div>

			<div
				class="flex items-center justify-between rounded-xl border border-border-subtle bg-surface px-4 py-3"
			>
				<div>
					<p class="text-sm font-medium text-foreground">Analytics</p>
					<p class="text-xs text-muted">Help us understand how you use the site</p>
				</div>
				<Toggle bind:checked={analyticsEnabled} />
			</div>

			<div
				class="flex items-center justify-between rounded-xl border border-border-subtle bg-surface px-4 py-3"
			>
				<div>
					<p class="text-sm font-medium text-foreground">Error Tracking</p>
					<p class="text-xs text-muted">Help us detect and fix issues faster</p>
				</div>
				<Toggle bind:checked={errorTrackingEnabled} />
			</div>
		</div>

		<div class="mt-6 flex justify-end gap-2">
			<Button onclick={() => (customizeOpen = false)}>Cancel</Button>
			<Button variant="primary" onclick={saveCustomPreferences}>Save preferences</Button>
		</div>
	</div>
</Dialog>

<style>
	@keyframes slideUp {
		from {
			opacity: 0;
			transform: translateY(1rem);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
