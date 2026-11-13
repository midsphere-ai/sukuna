<script lang="ts">
	import { usageLimitModal, type LimitType } from '$stores/usageLimit';

	const limitInfo: Record<LimitType, { title: string; description: string; icon: string }> = {
		credits: {
			title: 'Credits exhausted',
			description:
				"You've used all your available credits. Purchase an add-on pack or upgrade your plan to continue.",
			icon: 'coins'
		},
		concurrent_tasks: {
			title: 'Concurrent task limit reached',
			description:
				"You've reached the maximum number of tasks running at once. Wait for a task to finish or upgrade.",
			icon: 'layers'
		},
		custom_llm: {
			title: 'Custom LLM not available',
			description:
				'Your current plan does not support custom LLM models. Upgrade to use your own models.',
			icon: 'lock'
		},
		custom_mcp: {
			title: 'Custom MCP not available',
			description:
				'Your current plan does not support custom MCP servers. Upgrade to connect your own servers.',
			icon: 'lock'
		},
		enterprise_mode: {
			title: 'Enterprise mode requires an upgrade',
			description:
				'Enterprise mode is available on paid plans. Upgrade to unlock organizations, SSO, and SCIM.',
			icon: 'lock'
		},
		unknown: {
			title: 'Usage limit reached',
			description: "You've reached a limit on your current plan. Upgrade for higher limits.",
			icon: 'alert'
		}
	};

	let info = $derived($usageLimitModal);
	let display = $derived(info ? limitInfo[info.limitType] : null);
</script>

{#if info && display}
	<!-- svelte-ignore a11y_interactive_supports_focus -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
		role="dialog"
		aria-modal="true"
		aria-label="Usage limit reached"
		onkeydown={(e) => {
			if (e.key === 'Escape') usageLimitModal.dismiss();
		}}
	>
		<div
			class="mx-4 w-full max-w-md rounded-xl border border-border-subtle bg-surface-2 p-6 shadow-xl"
		>
			<!-- Icon -->
			<div
				class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent/10"
			>
				{#if display.icon === 'layers'}
					<svg
						class="h-6 w-6 text-accent"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
					</svg>
				{:else if display.icon === 'lock'}
					<svg
						class="h-6 w-6 text-accent"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" />
					</svg>
				{:else if display.icon === 'coins'}
					<svg
						class="h-6 w-6 text-accent"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<circle cx="8" cy="8" r="6" /><path d="M18.09 10.37A6 6 0 1112 20.09" /><path
							d="M7 6h2m-1-1v2"
						/>
					</svg>
				{:else}
					<svg
						class="h-6 w-6 text-accent"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<circle cx="12" cy="12" r="10" /><path d="M12 8v4m0 4h.01" />
					</svg>
				{/if}
			</div>

			<!-- Content -->
			<h3 class="font-junicode text-center text-lg text-foreground">{display.title}</h3>
			<p class="mt-2 text-center text-sm text-subtle">{display.description}</p>

			{#if info.message}
				<div class="mt-3 rounded-lg bg-accent/5 px-3 py-2">
					<p class="text-xs text-accent/80">{info.message}</p>
				</div>
			{/if}

			<!-- Actions -->
			<div class="mt-5 flex flex-col gap-2">
				<!-- eslint-disable svelte/no-navigation-without-resolve -->
				<a
					href="/billing/plans"
					onclick={() => usageLimitModal.dismiss()}
					class="flex w-full items-center justify-center rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent/90"
				>
					Upgrade plan
				</a>
				<!-- eslint-enable svelte/no-navigation-without-resolve -->
				<button
					onclick={() => usageLimitModal.dismiss()}
					class="w-full rounded-lg px-4 py-2 text-xs font-medium text-subtle transition-colors hover:bg-surface-2"
				>
					Dismiss
				</button>
			</div>
		</div>
	</div>
{/if}
