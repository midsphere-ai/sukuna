<script lang="ts">
	import { listBYOMProviders, upsertBYOMProvider, deleteBYOMProvider } from '$lib/api/byom';
	import type {
		BYOMProvider,
		BYOMToolSlot,
		BYOMProviderName,
		BYOMProviderInput
	} from '$lib/api/types';
	import { ConfirmationDialog } from '$components/ui';
	import { toasts } from '$stores/toast';
	import { subscription } from '$stores/subscription';
	import { tooltip } from '$lib/actions/tooltip';

	// ── Static data ──────────────────────────────────────────────

	const TOOL_SLOTS: { id: BYOMToolSlot; label: string; description: string; icon: string }[] = [
		{
			id: 'lead_agent',
			label: 'Main Agent',
			description: 'Primary AI model for reasoning and tasks',
			icon: 'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z'
		},
		{
			id: 'vision',
			label: 'Vision & Image',
			description: 'Image and video analysis',
			icon: 'M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z'
		},
		{
			id: 'browser',
			label: 'Web Browsing',
			description: 'Web search and page navigation',
			icon: 'M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9'
		},
		{
			id: 'audio',
			label: 'Audio',
			description: 'Audio transcription and processing',
			icon: 'M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z'
		}
	];

	const PROVIDERS: { id: BYOMProviderName; label: string }[] = [
		{ id: 'openai', label: 'OpenAI' },
		{ id: 'anthropic', label: 'Anthropic' },
		{ id: 'azure_openai', label: 'Azure OpenAI' },
		{ id: 'openrouter', label: 'OpenRouter' },
		{ id: 'ollama', label: 'Ollama' }
	];

	const PROVIDER_EXTRA_FIELDS: Record<
		BYOMProviderName,
		{ key: string; label: string; placeholder: string; textarea?: boolean }[]
	> = {
		openai: [],
		anthropic: [],
		azure_openai: [
			{
				key: 'azure_endpoint',
				label: 'Azure Endpoint',
				placeholder: 'https://your-resource.openai.azure.com'
			},
			{
				key: 'api_version',
				label: 'API Version',
				placeholder: '2024-12-01-preview'
			},
			{
				key: 'azure_deployment',
				label: 'Deployment Name',
				placeholder: 'my-gpt4o-deployment'
			}
		],
		openrouter: [],
		ollama: []
	};

	/** Providers where base_url is shown. Required for openrouter + ollama. */
	const BASE_URL_PROVIDERS: Record<string, { required: boolean; placeholder: string }> = {
		openai: { required: false, placeholder: 'https://api.openai.com/v1 (default)' },
		openrouter: { required: true, placeholder: 'https://openrouter.ai/api/v1' },
		ollama: { required: true, placeholder: 'http://localhost:11434/v1' },
		azure_openai: {
			required: true,
			placeholder: 'https://your-resource.openai.azure.com'
		}
	};

	// ── State ────────────────────────────────────────────────────

	let providers: BYOMProvider[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	// Billing gate
	let canUseCustomLLM = $derived(
		($subscription?.plan?.features?.use_custom_llm as boolean) === true
	);

	// Config form state
	let editingSlot: BYOMToolSlot | null = $state(null);
	let formProvider: BYOMProviderName = $state('openai');
	let formModelName = $state('');
	let formApiKey = $state('');
	let formBaseUrl = $state('');
	let formExtras: Record<string, string> = $state({});
	let formSubmitting = $state(false);

	// Delete state
	let deleteConfirmSlot: BYOMToolSlot | null = $state(null);
	let deleteLoading = $state(false);

	// Derived lookup
	let providerBySlot = $derived(new Map(providers.map((p) => [p.tool_slot, p])));

	let isEditing = $derived(editingSlot !== null && providerBySlot.has(editingSlot));

	let deleteSlotLabel = $derived(TOOL_SLOTS.find((s) => s.id === deleteConfirmSlot)?.label ?? '');

	// ── Data loading ─────────────────────────────────────────────

	async function loadProviders(): Promise<void> {
		loading = true;
		error = '';
		try {
			providers = await listBYOMProviders();
		} catch {
			error = 'Failed to load model configurations.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (canUseCustomLLM) {
			loadProviders();
		} else {
			loading = false;
		}
	});

	// ── Form helpers ─────────────────────────────────────────────

	function openConfigForm(slot: BYOMToolSlot): void {
		const existing = providerBySlot.get(slot);
		editingSlot = slot;
		if (existing) {
			formProvider = existing.provider_name;
			formModelName = existing.model_name;
			formApiKey = '';
			formBaseUrl = existing.base_url ?? '';
			formExtras = existing.extras ? { ...existing.extras } : {};
		} else {
			formProvider = 'openai';
			formModelName = '';
			formApiKey = '';
			formBaseUrl = '';
			formExtras = {};
		}
	}

	function closeConfigForm(): void {
		editingSlot = null;
		formProvider = 'openai';
		formModelName = '';
		formApiKey = '';
		formBaseUrl = '';
		formExtras = {};
	}

	function handleProviderChange(): void {
		formBaseUrl = '';
		formExtras = {};
	}

	// ── Submit ───────────────────────────────────────────────────

	async function handleSubmit(): Promise<void> {
		if (!editingSlot) return;

		if (!formModelName.trim()) {
			toasts.error('Model name is required.');
			return;
		}

		const isNew = !providerBySlot.has(editingSlot);
		if (isNew && !formApiKey.trim()) {
			toasts.error('API key is required.');
			return;
		}

		// Validate required extras
		const extraFields = PROVIDER_EXTRA_FIELDS[formProvider];
		for (const field of extraFields) {
			if (!formExtras[field.key]?.trim()) {
				toasts.error(`${field.label} is required.`);
				return;
			}
		}

		// Validate required base_url
		const baseUrlConfig = BASE_URL_PROVIDERS[formProvider];
		if (baseUrlConfig?.required && !formBaseUrl.trim()) {
			toasts.error('Base URL is required for this provider.');
			return;
		}

		formSubmitting = true;
		try {
			const payload: BYOMProviderInput = {
				tool_slot: editingSlot,
				provider_name: formProvider,
				model_name: formModelName.trim(),
				api_key: formApiKey
			};
			if (formBaseUrl.trim()) {
				payload.base_url = formBaseUrl.trim();
			}
			const extras = Object.fromEntries(Object.entries(formExtras).filter(([, v]) => v.trim()));
			if (Object.keys(extras).length > 0) {
				payload.extras = extras;
			}

			await upsertBYOMProvider(payload);
			toasts.success(isNew ? 'Model configured.' : 'Model updated.');
			closeConfigForm();
			await loadProviders();
		} catch {
			toasts.error('Failed to save model configuration.');
		} finally {
			formSubmitting = false;
		}
	}

	// ── Delete ───────────────────────────────────────────────────

	async function handleDelete(): Promise<void> {
		if (!deleteConfirmSlot) return;
		deleteLoading = true;
		try {
			await deleteBYOMProvider(deleteConfirmSlot);
			toasts.success('Model configuration removed.');
			deleteConfirmSlot = null;
			await loadProviders();
		} catch {
			toasts.error('Failed to remove model configuration.');
		} finally {
			deleteLoading = false;
		}
	}

	function getProviderLabel(name: BYOMProviderName): string {
		return PROVIDERS.find((p) => p.id === name)?.label ?? name;
	}
</script>

<div class="space-y-5">
	<!-- Header -->
	<section>
		<div>
			<h3 class="text-sm font-medium text-foreground">Custom Models</h3>
			<p class="text-xs text-muted">Configure your own LLM providers for each tool slot.</p>
		</div>
	</section>

	<!-- Upgrade CTA (billing gate) -->
	{#if !canUseCustomLLM}
		<section>
			<div class="rounded-xl border border-border bg-surface px-6 py-10 text-center">
				<div
					class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-2 text-muted"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="28"
						height="28"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
						<path d="M7 11V7a5 5 0 0110 0v4" />
					</svg>
				</div>
				<h4 class="text-base font-normal text-foreground">Custom Models</h4>
				<p class="mx-auto mt-2 max-w-xs text-sm text-subtle">
					Bring your own LLM providers to customise which models power each tool. Upgrade your plan
					to unlock this feature.
				</p>
				<a
					href="/billing/plans"
					class="mt-5 inline-flex items-center gap-2 rounded-xl bg-foreground px-5 py-2.5 text-sm font-medium text-background transition-all duration-200"
				>
					View Plans
				</a>
			</div>
		</section>

		<!-- Loading -->
	{:else if loading}
		<section class="grid gap-3 sm:grid-cols-2">
			{#each [0, 1, 2, 3] as i (i)}
				<div class="animate-pulse rounded-xl border border-border-subtle bg-surface p-4">
					<div class="flex items-center gap-3">
						<div class="h-9 w-9 rounded-lg bg-surface-2"></div>
						<div class="space-y-1.5">
							<div class="h-4 w-24 rounded bg-surface-2"></div>
							<div class="h-3 w-36 rounded bg-surface-2"></div>
						</div>
					</div>
				</div>
			{/each}
		</section>

		<!-- Error -->
	{:else if error}
		<section>
			<div
				class="rounded-xl border border-border-subtle bg-surface px-4 py-6 text-center text-sm text-muted"
			>
				{error}
				<button
					onclick={loadProviders}
					class="mt-2 block w-full text-xs font-medium text-accent hover:underline"
				>
					Try again
				</button>
			</div>
		</section>

		<!-- Slot cards -->
	{:else}
		<section class="grid gap-3 sm:grid-cols-2">
			{#each TOOL_SLOTS as slot (slot.id)}
				{@const config = providerBySlot.get(slot.id)}
				<div
					class="group rounded-xl border border-border bg-surface p-4 transition-colors hover:bg-surface-2"
				>
					<!-- Slot header -->
					<div class="flex items-start gap-3">
						<div
							class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg {config
								? 'bg-accent/10 text-accent'
								: 'bg-surface-2 text-muted'}"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								width="18"
								height="18"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.75"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d={slot.icon} />
							</svg>
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<p class="text-sm font-medium text-foreground">{slot.label}</p>
								{#if config?.is_active}
									<span class="h-1.5 w-1.5 rounded-full bg-green-500" use:tooltip={'Active'}></span>
								{/if}
							</div>

							{#if config}
								<!-- Configured state -->
								<div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
									<span
										class="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-subtle"
									>
										{getProviderLabel(config.provider_name)}
									</span>
									<span class="text-xs text-foreground">{config.model_name}</span>
								</div>
								<p class="mt-1 font-mono text-[11px] text-muted" use:tooltip={'Masked API key'}>
									{config.api_key_masked}
								</p>
							{:else}
								<!-- Unconfigured state -->
								<p class="mt-0.5 text-xs text-muted">{slot.description}</p>
								<p class="mt-1.5 text-[11px] text-muted">Not configured</p>
							{/if}
						</div>
					</div>

					<!-- Actions -->
					<div class="mt-3 flex items-center gap-2">
						{#if config}
							<button
								onclick={() => openConfigForm(slot.id)}
								class="rounded-lg px-2.5 py-1 text-xs font-medium text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
								use:tooltip={'Edit configuration'}
							>
								Edit
							</button>
							<button
								onclick={() => {
									deleteConfirmSlot = slot.id;
								}}
								class="rounded-lg px-2.5 py-1 text-xs text-muted opacity-0 transition-all duration-200 hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100"
								use:tooltip={'Remove configuration'}
							>
								Remove
							</button>
						{:else}
							<button
								onclick={() => openConfigForm(slot.id)}
								class="flex items-center gap-1.5 rounded-lg bg-surface-2 px-3 py-1.5 text-xs font-medium text-subtle transition-all duration-200 hover:bg-surface-2 hover:text-foreground"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									width="12"
									height="12"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
								>
									<line x1="12" y1="5" x2="12" y2="19" />
									<line x1="5" y1="12" x2="19" y2="12" />
								</svg>
								Configure
							</button>
						{/if}
					</div>
				</div>
			{/each}
		</section>

		<!-- Inline config form -->
		{#if editingSlot}
			{@const editingSlotLabel = TOOL_SLOTS.find((s) => s.id === editingSlot)?.label ?? ''}
			<section>
				<div class="rounded-xl border border-border bg-surface p-4">
					<h4 class="text-sm font-medium text-foreground">
						{isEditing ? 'Edit' : 'Configure'} — {editingSlotLabel}
					</h4>

					<div class="mt-3 space-y-4">
						<!-- Provider selector -->
						<div class="flex flex-col gap-1.5">
							<label for="byom-provider" class="text-xs font-medium text-foreground"
								>Provider <span class="text-accent">*</span></label
							>
							<select
								id="byom-provider"
								bind:value={formProvider}
								onchange={handleProviderChange}
								class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							>
								{#each PROVIDERS as provider (provider.id)}
									<option value={provider.id}>{provider.label}</option>
								{/each}
							</select>
						</div>

						<!-- Model name -->
						<div class="flex flex-col gap-1.5">
							<label for="byom-model" class="text-xs font-medium text-foreground"
								>Model Name <span class="text-accent">*</span></label
							>
							<input
								id="byom-model"
								type="text"
								bind:value={formModelName}
								placeholder={formProvider === 'openai'
									? 'gpt-4o'
									: formProvider === 'anthropic'
										? 'claude-sonnet-4-20250514'
										: formProvider === 'ollama'
											? 'llama3'
											: formProvider === 'openrouter'
												? 'openai/gpt-4o'
												: 'model-name'}
								class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							/>
						</div>

						<!-- API key -->
						<div class="flex flex-col gap-1.5">
							<label for="byom-apikey" class="text-xs font-medium text-foreground"
								>API Key {#if !isEditing}<span class="text-accent">*</span>{/if}</label
							>
							<input
								id="byom-apikey"
								type="password"
								bind:value={formApiKey}
								placeholder={isEditing ? 'Leave blank to keep existing key' : 'sk-...'}
								class="w-full rounded-xl border border-border bg-background px-4 py-2 font-mono text-sm text-foreground outline-none transition-all duration-200 placeholder:font-sans placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							/>
							{#if isEditing}
								<p class="text-[11px] text-muted">Leave blank to keep the existing key.</p>
							{/if}
						</div>

						<!-- Base URL (conditional) -->
						{#if BASE_URL_PROVIDERS[formProvider]}
							{@const urlConfig = BASE_URL_PROVIDERS[formProvider]}
							<div class="flex flex-col gap-1.5">
								<label for="byom-baseurl" class="text-xs font-medium text-foreground">
									Base URL
									{#if urlConfig.required}<span class="text-accent">*</span>{/if}
								</label>
								<input
									id="byom-baseurl"
									type="url"
									bind:value={formBaseUrl}
									placeholder={urlConfig.placeholder}
									class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
								/>
							</div>
						{/if}

						<!-- Provider-specific extras -->
						{#each PROVIDER_EXTRA_FIELDS[formProvider] as field (field.key)}
							<div class="flex flex-col gap-1.5">
								<label for="byom-extra-{field.key}" class="text-xs font-medium text-foreground">
									{field.label} <span class="text-accent">*</span>
								</label>
								{#if field.textarea}
									<textarea
										id="byom-extra-{field.key}"
										bind:value={formExtras[field.key]}
										placeholder={field.placeholder}
										rows="3"
										class="w-full rounded-xl border border-border bg-background px-4 py-2 font-mono text-xs text-foreground outline-none transition-all duration-200 placeholder:font-sans placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									></textarea>
								{:else}
									<input
										id="byom-extra-{field.key}"
										type="text"
										bind:value={formExtras[field.key]}
										placeholder={field.placeholder}
										class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
									/>
								{/if}
							</div>
						{/each}

						<!-- Actions -->
						<div class="flex items-center gap-2 pt-1">
							<button
								onclick={handleSubmit}
								disabled={formSubmitting}
								class="flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50"
							>
								{#if formSubmitting}
									<svg
										class="h-4 w-4 animate-spin"
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
								{/if}
								{isEditing ? 'Update' : 'Configure'}
							</button>
							<button
								onclick={closeConfigForm}
								disabled={formSubmitting}
								class="rounded-lg px-4 py-2 text-sm font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
							>
								Cancel
							</button>
						</div>
					</div>
				</div>
			</section>
		{/if}
	{/if}
</div>

<!-- Delete confirmation -->
<ConfirmationDialog
	open={deleteConfirmSlot !== null}
	title="Remove Model Configuration"
	message={`Remove the custom model for "${deleteSlotLabel}"? This slot will revert to the default model.`}
	confirmLabel={deleteLoading ? 'Removing...' : 'Remove'}
	destructive={true}
	onconfirm={handleDelete}
	oncancel={() => {
		deleteConfirmSlot = null;
	}}
/>
