<script lang="ts">
	import { userSettings, saveSettings } from '$stores/settings';

	let theme = $state('system');
	userSettings.subscribe((s) => {
		theme = s.theme;
	});

	const themeOptions: { value: string; label: string; description: string }[] = [
		{ value: 'light', label: 'Light', description: 'Classic warm paper theme' },
		{ value: 'dark', label: 'Dark', description: 'Easy on the eyes at night' },
		{ value: 'system', label: 'System', description: 'Follows your device setting' }
	];

	function selectTheme(value: string): void {
		theme = value;
		saveSettings({ theme: value });
	}
</script>

<div class="space-y-5">
	<!-- Theme -->
	<section>
		<div>
			<h3 class="text-sm font-medium text-foreground">Appearance</h3>
			<p class="text-xs text-muted">Choose how Jatayu AI looks to you.</p>
		</div>

		<div class="mt-3 grid gap-3 sm:grid-cols-3">
			{#each themeOptions as option (option.value)}
				<button
					onclick={() => selectTheme(option.value)}
					class="group relative flex flex-col items-center gap-2 rounded-2xl border-2 px-4 py-3 transition-all duration-200 {theme ===
					option.value
						? 'border-accent bg-accent/[0.04]'
						: 'border-border hover:border-border-strong hover:bg-surface-2'}"
				>
					<!-- Theme preview -->
					<div class="relative h-12 w-16 overflow-hidden rounded-xl border border-border">
						{#if option.value === 'light'}
							<div class="h-full w-full bg-[#f0f2f5]">
								<div class="ml-1 mt-1.5 h-1.5 w-6 rounded-full bg-[#1c2333]/20"></div>
								<div class="ml-1 mt-1 h-1 w-8 rounded-full bg-[#1c2333]/10"></div>
								<div class="ml-1 mt-1 h-1 w-5 rounded-full bg-[#1c2333]/10"></div>
							</div>
						{:else if option.value === 'dark'}
							<div class="h-full w-full bg-[#0e1525]">
								<div class="ml-1 mt-1.5 h-1.5 w-6 rounded-full bg-[#f5f9fc]/20"></div>
								<div class="ml-1 mt-1 h-1 w-8 rounded-full bg-[#f5f9fc]/10"></div>
								<div class="ml-1 mt-1 h-1 w-5 rounded-full bg-[#f5f9fc]/10"></div>
							</div>
						{:else}
							<div class="flex h-full w-full">
								<div class="h-full w-1/2 bg-[#f0f2f5]">
									<div class="ml-0.5 mt-1.5 h-1 w-4 rounded-full bg-[#1c2333]/20"></div>
									<div class="ml-0.5 mt-0.5 h-0.5 w-5 rounded-full bg-[#1c2333]/10"></div>
								</div>
								<div class="h-full w-1/2 bg-[#0e1525]">
									<div class="ml-0.5 mt-1.5 h-1 w-4 rounded-full bg-[#f5f9fc]/20"></div>
									<div class="ml-0.5 mt-0.5 h-0.5 w-5 rounded-full bg-[#f5f9fc]/10"></div>
								</div>
							</div>
						{/if}
					</div>

					<div class="text-center">
						<span
							class="text-sm font-medium {theme === option.value
								? 'text-accent'
								: 'text-foreground'}">{option.label}</span
						>
						<p class="mt-0.5 text-[11px] text-muted">{option.description}</p>
					</div>

					<!-- Check indicator -->
					{#if theme === option.value}
						<div
							class="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="12"
								height="12"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="3"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<polyline points="20 6 9 17 4 12" />
							</svg>
						</div>
					{/if}
				</button>
			{/each}
		</div>
	</section>

	<!-- Links -->
	<section class="border-t border-border-subtle pt-4">
		<h3 class="text-sm font-medium text-foreground">Legal</h3>
		<div class="mt-3 flex flex-col gap-1">
			<!-- eslint-disable svelte/no-navigation-without-resolve -->
			<a
				href="/terms"
				target="_blank"
				rel="noopener noreferrer"
				class="flex items-center justify-between rounded-xl px-3 py-2.5 text-sm text-foreground transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
			>
				Terms and Conditions
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
					class="text-muted"
				>
					<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
					<polyline points="15 3 21 3 21 9" />
					<line x1="10" y1="14" x2="21" y2="3" />
				</svg>
			</a>
			<a
				href="/privacy"
				target="_blank"
				rel="noopener noreferrer"
				class="flex items-center justify-between rounded-xl px-3 py-2.5 text-sm text-foreground transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
			>
				Privacy Policy
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
					class="text-muted"
				>
					<path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
					<polyline points="15 3 21 3 21 9" />
					<line x1="10" y1="14" x2="21" y2="3" />
				</svg>
			</a>
			<!-- eslint-enable svelte/no-navigation-without-resolve -->
		</div>
	</section>
</div>
