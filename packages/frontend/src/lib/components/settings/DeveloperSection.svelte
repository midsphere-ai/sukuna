<script lang="ts">
	import { listAPIKeys, createAPIKey, revokeAPIKey } from '$lib/api/developer';
	import type { DeveloperAPIKey } from '$lib/api/types';
	import { ConfirmationDialog, EmptyState } from '$components/ui';
	import { toasts } from '$stores/toast';
	import { tooltip } from '$lib/actions/tooltip';

	const AVAILABLE_SCOPES = [
		{ id: 'conversations:read', label: 'Read Conversations' },
		{ id: 'conversations:write', label: 'Write Conversations' },
		{ id: 'tasks:read', label: 'Read Tasks' },
		{ id: 'tasks:write', label: 'Write Tasks' },
		{ id: 'files:read', label: 'Read Files' },
		{ id: 'files:write', label: 'Write Files' }
	];

	let keys: DeveloperAPIKey[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	// Create form state
	let showCreateForm = $state(false);
	let createSubmitting = $state(false);
	let createName = $state('');
	let createScopes: string[] = $state([]);
	let createExpiryEnabled = $state(false);
	let createExpiryDate = $state('');

	// Newly created key (shown once)
	let newlyCreatedKey = $state('');
	let newlyCreatedKeyName = $state('');
	let keyCopied = $state(false);

	// Revoke state
	let revokeConfirmId = $state('');
	let revokeConfirmName = $state('');
	let revokeLoading = $state(false);

	async function loadKeys(): Promise<void> {
		loading = true;
		error = '';
		try {
			keys = await listAPIKeys();
		} catch {
			error = 'Failed to load API keys.';
		} finally {
			loading = false;
		}
	}

	function toggleScope(scope: string): void {
		if (createScopes.includes(scope)) {
			createScopes = createScopes.filter((s) => s !== scope);
		} else {
			createScopes = [...createScopes, scope];
		}
	}

	function resetCreateForm(): void {
		createName = '';
		createScopes = [];
		createExpiryEnabled = false;
		createExpiryDate = '';
		showCreateForm = false;
	}

	async function handleCreate(): Promise<void> {
		if (!createName.trim()) {
			toasts.error('Key name is required.');
			return;
		}
		createSubmitting = true;
		try {
			const result = await createAPIKey({
				name: createName.trim(),
				scopes: createScopes,
				expires_at:
					createExpiryEnabled && createExpiryDate ? new Date(createExpiryDate).toISOString() : null
			});
			newlyCreatedKey = result.key;
			newlyCreatedKeyName = result.name;
			keyCopied = false;
			resetCreateForm();
			await loadKeys();
			toasts.success('API key created.');
		} catch {
			toasts.error('Failed to create API key.');
		} finally {
			createSubmitting = false;
		}
	}

	async function handleRevoke(): Promise<void> {
		revokeLoading = true;
		try {
			await revokeAPIKey(revokeConfirmId);
			toasts.success('API key revoked.');
			revokeConfirmId = '';
			revokeConfirmName = '';
			await loadKeys();
		} catch {
			toasts.error('Failed to revoke API key.');
		} finally {
			revokeLoading = false;
		}
	}

	function cancelRevoke(): void {
		revokeConfirmId = '';
		revokeConfirmName = '';
	}

	async function copyKey(): Promise<void> {
		try {
			await navigator.clipboard.writeText(newlyCreatedKey);
			keyCopied = true;
			toasts.success('API key copied to clipboard.');
		} catch {
			toasts.error('Failed to copy to clipboard.');
		}
	}

	function dismissNewKey(): void {
		newlyCreatedKey = '';
		newlyCreatedKeyName = '';
		keyCopied = false;
	}

	function getKeyStatus(key: DeveloperAPIKey): { label: string; classes: string } {
		if (!key.is_active) {
			return { label: 'Revoked', classes: 'bg-red-500/10 text-red-600 dark:text-red-400' };
		}
		if (key.expires_at && new Date(key.expires_at) < new Date()) {
			return { label: 'Expired', classes: 'bg-surface-2 text-muted' };
		}
		return { label: 'Active', classes: 'bg-green-500/10 text-green-600 dark:text-green-400' };
	}

	function formatDate(date: string): string {
		return new Date(date).toLocaleDateString('en-GB', {
			day: 'numeric',
			month: 'short',
			year: 'numeric'
		});
	}

	function formatDateTime(date: string): string {
		return new Date(date).toLocaleDateString('en-GB', {
			day: 'numeric',
			month: 'short',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	$effect(() => {
		loadKeys();
	});
</script>

<div class="space-y-5">
	<!-- Header + Create Button -->
	<section>
		<div class="flex items-center justify-between">
			<div>
				<h3 class="text-sm font-medium text-foreground">API Keys</h3>
				<p class="text-xs text-muted">Create and manage API keys for programmatic access.</p>
			</div>
			{#if !showCreateForm}
				<button
					onclick={() => (showCreateForm = true)}
					class="flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-all duration-200"
					use:tooltip={'Create a new API key'}
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
						<line x1="12" y1="5" x2="12" y2="19" />
						<line x1="5" y1="12" x2="19" y2="12" />
					</svg>
					New Key
				</button>
			{/if}
		</div>
	</section>

	<!-- Newly Created Key Banner -->
	{#if newlyCreatedKey}
		<section>
			<div class="rounded-xl border border-green-500/20 bg-green-500/5 p-4">
				<div class="flex items-start justify-between gap-3">
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
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
								class="shrink-0 text-green-600"
							>
								<path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
								<polyline points="22 4 12 14.01 9 11.01" />
							</svg>
							<p class="text-sm font-medium text-foreground">
								Key "{newlyCreatedKeyName}" created
							</p>
						</div>
						<p class="mt-1.5 text-xs text-subtle">
							Copy this key now. You won't be able to see it again.
						</p>
						<div class="mt-3 flex items-center gap-2">
							<code
								class="flex-1 truncate rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs text-foreground"
							>
								{newlyCreatedKey}
							</code>
							<button
								onclick={copyKey}
								class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-subtle transition-all hover:bg-surface-2 hover:text-foreground"
								use:tooltip={keyCopied ? 'Copied!' : 'Copy key'}
							>
								{#if keyCopied}
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
										class="text-green-600"
									>
										<polyline points="20 6 9 17 4 12" />
									</svg>
								{:else}
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
								{/if}
							</button>
						</div>
					</div>
					<button
						onclick={dismissNewKey}
						class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted transition-all hover:bg-surface-2 hover:text-foreground"
						aria-label="Dismiss"
						use:tooltip={'Dismiss'}
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
							<path d="M18 6L6 18" />
							<path d="M6 6l12 12" />
						</svg>
					</button>
				</div>
			</div>
		</section>
	{/if}

	<!-- Create Form -->
	{#if showCreateForm}
		<section>
			<div class="rounded-xl border border-border bg-surface p-4">
				<h4 class="text-sm font-medium text-foreground">New API Key</h4>

				<div class="mt-3 space-y-4">
					<!-- Name -->
					<div class="flex flex-col gap-1.5">
						<label for="create-key-name" class="text-xs font-medium text-foreground"
							>Name <span class="text-accent">*</span></label
						>
						<input
							id="create-key-name"
							type="text"
							bind:value={createName}
							placeholder="e.g. CI/CD Pipeline, My App"
							class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
						/>
					</div>

					<!-- Scopes -->
					<div class="flex flex-col gap-2">
						<p class="text-xs font-medium text-foreground">Scopes</p>
						<p class="text-xs text-muted">
							Select which permissions this key should have. Leave empty for full access.
						</p>
						<div class="grid grid-cols-2 gap-2">
							{#each AVAILABLE_SCOPES as scope (scope.id)}
								<label
									class="flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 transition-all duration-200 {createScopes.includes(
										scope.id
									)
										? 'border-accent/30 bg-accent/5'
										: 'border-border bg-background hover:border-border-strong'}"
								>
									<input
										type="checkbox"
										checked={createScopes.includes(scope.id)}
										onchange={() => toggleScope(scope.id)}
										class="sr-only"
									/>
									<div
										class="flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-all {createScopes.includes(
											scope.id
										)
											? 'border-accent bg-accent'
											: 'border-border-strong bg-background'}"
									>
										{#if createScopes.includes(scope.id)}
											<svg
												xmlns="http://www.w3.org/2000/svg"
												width="10"
												height="10"
												viewBox="0 0 24 24"
												fill="none"
												stroke="white"
												stroke-width="3"
												stroke-linecap="round"
												stroke-linejoin="round"
											>
												<polyline points="20 6 9 17 4 12" />
											</svg>
										{/if}
									</div>
									<span class="text-xs font-medium text-foreground">{scope.label}</span>
								</label>
							{/each}
						</div>
					</div>

					<!-- Expiry -->
					<div class="flex flex-col gap-2">
						<label class="flex cursor-pointer items-center gap-2.5">
							<input type="checkbox" bind:checked={createExpiryEnabled} class="sr-only" />
							<div
								class="relative h-5 w-9 rounded-full transition-colors duration-200 {createExpiryEnabled
									? 'bg-accent'
									: 'bg-foreground/20'}"
							>
								<span
									class="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 {createExpiryEnabled
										? 'translate-x-4'
										: 'translate-x-0'}"
								></span>
							</div>
							<span class="text-xs font-medium text-foreground">Set expiry date</span>
						</label>
						{#if createExpiryEnabled}
							<input
								type="date"
								bind:value={createExpiryDate}
								min={new Date().toISOString().split('T')[0]}
								class="w-48 rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							/>
						{/if}
					</div>

					<!-- Actions -->
					<div class="flex items-center gap-2 pt-1">
						<button
							onclick={handleCreate}
							disabled={createSubmitting}
							class="flex items-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{#if createSubmitting}
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
							Create Key
						</button>
						<button
							onclick={resetCreateForm}
							disabled={createSubmitting}
							class="rounded-lg px-4 py-2 text-sm font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
						>
							Cancel
						</button>
					</div>
				</div>
			</div>
		</section>
	{/if}

	<!-- Keys List -->
	<section class="border-t border-border-subtle pt-4">
		{#if loading}
			<div class="space-y-3">
				{#each [0, 1, 2] as i (i)}
					<div class="animate-pulse rounded-xl border border-border-subtle bg-surface p-4">
						<div class="flex items-center justify-between">
							<div class="space-y-2">
								<div class="h-4 w-48 rounded bg-surface-2"></div>
								<div class="h-3 w-32 rounded bg-surface-2"></div>
							</div>
							<div class="h-5 w-14 rounded-md bg-surface-2"></div>
						</div>
					</div>
				{/each}
			</div>
		{:else if error}
			<div
				class="rounded-xl border border-border-subtle bg-surface px-4 py-6 text-center text-sm text-muted"
			>
				{error}
				<button
					onclick={loadKeys}
					class="mt-2 block w-full text-xs font-medium text-accent hover:underline"
				>
					Try again
				</button>
			</div>
		{:else if keys.length === 0}
			<EmptyState
				title="No API keys yet"
				description="Create your first API key to start using the developer API. Keys allow programmatic access to your account."
			>
				{#snippet illustration()}
					<div
						class="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-2 text-muted"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="32"
							height="32"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.5"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path
								d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"
							/>
						</svg>
					</div>
				{/snippet}
			</EmptyState>
		{:else}
			<div class="space-y-3">
				{#each keys as key (key.id)}
					{@const status = getKeyStatus(key)}
					<div
						class="group rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:bg-surface-2"
					>
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2">
									<p class="truncate text-sm font-medium text-foreground">
										{key.name}
									</p>
									<span
										class="rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide {status.classes}"
									>
										{status.label}
									</span>
								</div>

								<div class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
									<span class="font-mono text-xs text-muted" use:tooltip={'Key prefix'}>
										{key.key_prefix}...
									</span>
									<span class="text-xs text-muted">
										Created {formatDate(key.date_created)}
									</span>
									{#if key.last_used_at}
										<span class="text-xs text-muted">
											Last used {formatDateTime(key.last_used_at)}
										</span>
									{:else}
										<span class="text-xs text-muted">Never used</span>
									{/if}
								</div>

								<!-- Scopes -->
								{#if key.scopes.length > 0}
									<div class="mt-2 flex flex-wrap gap-1">
										{#each key.scopes as scope (scope)}
											<span
												class="rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-medium text-subtle"
											>
												{scope}
											</span>
										{/each}
									</div>
								{:else}
									<p class="mt-2 text-[10px] text-muted">Full access (no scope restrictions)</p>
								{/if}

								{#if key.expires_at}
									<p class="mt-1.5 text-[10px] text-muted">
										{new Date(key.expires_at) < new Date()
											? `Expired ${formatDate(key.expires_at)}`
											: `Expires ${formatDate(key.expires_at)}`}
									</p>
								{/if}
							</div>

							<!-- Revoke button -->
							{#if key.is_active}
								<button
									onclick={() => {
										revokeConfirmId = key.id;
										revokeConfirmName = key.name;
									}}
									class="flex h-7 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-muted opacity-0 transition-all hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100"
									aria-label="Revoke key"
									use:tooltip={'Revoke this key'}
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
										<polyline points="3 6 5 6 21 6" />
										<path
											d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"
										/>
									</svg>
									Revoke
								</button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</section>
</div>

<!-- Revoke Confirmation Dialog -->
<ConfirmationDialog
	open={revokeConfirmId !== ''}
	title="Revoke API Key"
	message="Are you sure you want to revoke the key &quot;{revokeConfirmName}&quot;? This action cannot be undone. Any applications using this key will lose access immediately."
	confirmLabel={revokeLoading ? 'Revoking...' : 'Revoke Key'}
	destructive={true}
	onconfirm={handleRevoke}
	oncancel={cancelRevoke}
/>
