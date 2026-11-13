<script lang="ts">
	import { userSettings, saveSettings } from '$stores/settings';

	let customInstructions = $state('');
	let nickname = $state('');
	let occupation = $state('');
	let aboutYou = $state('');
	let webSearch = $state(true);
	let browserEnabled = $state(true);
	let shellCommands = $state(true);
	let complexReasoning = $state(true);
	let computerUse = $state(true);
	userSettings.subscribe((s) => {
		customInstructions = s.custom_instructions;
		nickname = s.nickname;
		occupation = s.occupation;
		aboutYou = s.about_you;
		webSearch = s.web_search;
		browserEnabled = s.browser;
		shellCommands = s.shell_commands;
		complexReasoning = s.complex_reasoning;
		computerUse = s.computer_use;
	});

	function saveField(field: string, value: string | boolean): void {
		saveSettings({ [field]: value });
	}

	const toggles: { field: string; label: string; description: string; icon: string }[] = [
		{
			field: 'web_search',
			label: 'Web Search',
			description: 'Allow the agent to search the web for information',
			icon: 'M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z'
		},
		{
			field: 'browser',
			label: 'Browser',
			description: 'Allow the agent to navigate and interact with web pages',
			icon: 'M12 2a10 10 0 100 20 10 10 0 000-20zM2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z'
		},
		{
			field: 'shell_commands',
			label: 'Shell Commands',
			description: 'Allow the agent to execute shell commands',
			icon: 'M4 17l6-6-6-6M12 19h8'
		},
		{
			field: 'complex_reasoning',
			label: 'Complex Reasoning',
			description: 'Enable extended thinking for complex tasks',
			icon: 'M12 2a2 2 0 012 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 017 7h1a1 1 0 011 1v3a1 1 0 01-1 1h-1v1a2 2 0 01-2 2H5a2 2 0 01-2-2v-1H2a1 1 0 01-1-1v-3a1 1 0 011-1h1a7 7 0 017-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 012-2'
		},
		{
			field: 'computer_use',
			label: 'Computer Use',
			description: 'Allow the agent to control the desktop environment',
			icon: 'M2 3h20v14H2V3zM8 21h8M12 17v4'
		}
	];

	function getToggleValue(field: string): boolean {
		switch (field) {
			case 'web_search':
				return webSearch;
			case 'browser':
				return browserEnabled;
			case 'shell_commands':
				return shellCommands;
			case 'complex_reasoning':
				return complexReasoning;
			case 'computer_use':
				return computerUse;
			default:
				return false;
		}
	}

	function handleToggle(field: string, checked: boolean): void {
		switch (field) {
			case 'web_search':
				webSearch = checked;
				break;
			case 'browser':
				browserEnabled = checked;
				break;
			case 'shell_commands':
				shellCommands = checked;
				break;
			case 'complex_reasoning':
				complexReasoning = checked;
				break;
			case 'computer_use':
				computerUse = checked;
				break;
		}
		saveField(field, checked);
	}
</script>

<div class="space-y-5">
	<!-- Personal Information -->
	<section>
		<div>
			<h3 class="text-sm font-medium text-foreground">Personal Information</h3>
			<p class="text-xs text-muted">Help the agent understand you better.</p>
		</div>

		<div class="mt-3 space-y-4">
			<div class="flex flex-col gap-1.5">
				<label for="settings-nickname" class="text-sm font-medium text-foreground">Nickname</label>
				<input
					id="settings-nickname"
					type="text"
					bind:value={nickname}
					onblur={() => saveField('nickname', nickname)}
					placeholder="What should the agent call you?"
					class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				/>
			</div>

			<div class="flex flex-col gap-1.5">
				<label for="settings-occupation" class="text-sm font-medium text-foreground"
					>Occupation</label
				>
				<input
					id="settings-occupation"
					type="text"
					bind:value={occupation}
					onblur={() => saveField('occupation', occupation)}
					placeholder="e.g. Software Engineer, Designer, Student"
					class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				/>
			</div>

			<div class="flex flex-col gap-1.5">
				<label for="settings-about" class="text-sm font-medium text-foreground"
					>More About You</label
				>
				<textarea
					id="settings-about"
					bind:value={aboutYou}
					onblur={() => saveField('about_you', aboutYou)}
					placeholder="Anything else the agent should know about you, your preferences, or how you work"
					rows={3}
					class="w-full resize-y rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				></textarea>
			</div>
		</div>
	</section>

	<!-- Custom Instructions -->
	<section class="border-t border-border-subtle pt-4">
		<div>
			<h3 class="text-sm font-medium text-foreground">Custom Instructions</h3>
			<p class="text-xs text-muted">
				Tell the agent how to behave. These instructions are included in every conversation.
			</p>
		</div>

		<div class="mt-3">
			<textarea
				id="settings-custom-instructions"
				bind:value={customInstructions}
				onblur={() => saveField('custom_instructions', customInstructions)}
				placeholder="e.g. Always respond in British English. Prefer concise answers. When writing code, use TypeScript."
				rows={5}
				class="w-full resize-y rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
			></textarea>
		</div>
	</section>

	<!-- Agent Capabilities -->
	<section class="border-t border-border-subtle pt-4">
		<div>
			<h3 class="text-sm font-medium text-foreground">Agent Capabilities</h3>
			<p class="text-xs text-muted">Control what tools the agent can use by default.</p>
		</div>

		<div class="mt-3 space-y-1">
			{#each toggles as toggle (toggle.field)}
				<label
					for="settings-toggle-{toggle.field}"
					class="flex cursor-pointer items-center justify-between rounded-xl px-3 py-2 transition-all duration-200 hover:bg-surface-2"
				>
					<div class="mr-4 flex items-center gap-3">
						<div
							class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted"
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
								<path d={toggle.icon} />
							</svg>
						</div>
						<div>
							<span class="text-sm font-medium text-foreground">{toggle.label}</span>
							<p class="mt-0.5 text-xs text-muted">{toggle.description}</p>
						</div>
					</div>
					<div class="relative shrink-0">
						<input
							id="settings-toggle-{toggle.field}"
							type="checkbox"
							role="switch"
							checked={getToggleValue(toggle.field)}
							onchange={(e: Event) =>
								handleToggle(toggle.field, (e.target as HTMLInputElement).checked)}
							aria-checked={getToggleValue(toggle.field)}
							class="peer sr-only"
						/>
						<div
							class="h-6 w-11 rounded-full bg-border-strong transition-colors duration-200 peer-checked:bg-accent"
						></div>
						<div
							class="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-background shadow-sm transition-transform duration-200 peer-checked:translate-x-5"
						></div>
					</div>
				</label>
			{/each}
		</div>
	</section>
</div>
