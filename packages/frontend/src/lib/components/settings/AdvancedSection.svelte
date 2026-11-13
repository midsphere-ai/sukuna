<script lang="ts">
	import { userSettings, saveSettings } from '$stores/settings';
	import { getMCPConfigs, registerMCPConfig, unregisterMCPConfig } from '$lib/api/mcp';
	import type { UserMCPConfig, MCPConfigInput } from '$lib/api/types';
	import { toasts } from '$stores/toast';
	import { tooltip } from '$lib/actions/tooltip';
	import { flagEnabled } from '$stores/featureFlags';

	const localModeFlag = flagEnabled('enable-local-mode');
	const mcpFlag = flagEnabled('enable-custom-mcp');
	let showLocalMode = $state(true);
	let showMcp = $state(true);
	localModeFlag.subscribe((v) => {
		showLocalMode = v;
	});
	mcpFlag.subscribe((v) => {
		showMcp = v;
	});

	let backendUrl = $state('');
	let localMode = $state(false);
	let localSandboxUrl = $state('');

	userSettings.subscribe((s) => {
		backendUrl = s.backend_url;
		localMode = s.local_mode;
		localSandboxUrl = s.local_sandbox_url;
	});

	function saveField(field: string, value: string | boolean): void {
		saveSettings({ [field]: value });
	}

	// MCP Config state
	let configs: UserMCPConfig[] = $state([]);
	let configsLoading = $state(true);
	let configsError = $state('');

	// Add form state
	let showAddForm = $state(false);
	let formSubmitting = $state(false);
	let formServerName = $state('');
	let formServerType: MCPConfigInput['server_type'] = $state('stdio');
	let formCommand = $state('');
	let formUrl = $state('');
	let formArgs = $state('');
	let formEnv = $state('');
	let formTimeout = $state('');
	let formDescription = $state('');

	// Delete confirmation state
	let deleteConfirmId = $state('');
	let deleteLoading = $state(false);

	async function loadConfigs(): Promise<void> {
		configsLoading = true;
		configsError = '';
		try {
			const response = await getMCPConfigs();
			configs = response.items;
		} catch {
			configsError = 'Failed to load MCP configurations.';
		} finally {
			configsLoading = false;
		}
	}

	function resetForm(): void {
		formServerName = '';
		formServerType = 'stdio';
		formCommand = '';
		formUrl = '';
		formArgs = '';
		formEnv = '';
		formTimeout = '';
		formDescription = '';
		showAddForm = false;
	}

	async function handleAddConfig(): Promise<void> {
		if (!formServerName.trim()) {
			toasts.error('Server name is required.');
			return;
		}

		if (formServerType === 'stdio' && !formCommand.trim()) {
			toasts.error('Command is required for stdio servers.');
			return;
		}

		if ((formServerType === 'sse' || formServerType === 'streamable-http') && !formUrl.trim()) {
			toasts.error('URL is required for SSE/Streamable HTTP servers.');
			return;
		}

		formSubmitting = true;
		try {
			const input: MCPConfigInput = {
				server_name: formServerName.trim(),
				server_type: formServerType,
				description: formDescription.trim() || undefined
			};

			if (formServerType === 'stdio') {
				input.command = formCommand.trim();
				if (formArgs.trim()) {
					input.args = formArgs
						.split('\n')
						.map((a) => a.trim())
						.filter(Boolean);
				}
			} else {
				input.url = formUrl.trim();
			}

			if (formEnv.trim()) {
				try {
					input.env = JSON.parse(formEnv.trim());
				} catch {
					toasts.error('Environment variables must be valid JSON.');
					formSubmitting = false;
					return;
				}
			}

			if (formTimeout.trim()) {
				const t = parseInt(formTimeout.trim(), 10);
				if (!isNaN(t) && t > 0) {
					input.timeout = t;
				}
			}

			await registerMCPConfig(input);
			toasts.success(`MCP server "${formServerName}" added.`);
			resetForm();
			await loadConfigs();
		} catch {
			toasts.error('Failed to add MCP configuration.');
		} finally {
			formSubmitting = false;
		}
	}

	async function handleDeleteConfig(id: string, name: string): Promise<void> {
		deleteLoading = true;
		try {
			await unregisterMCPConfig(id);
			toasts.success(`MCP server "${name}" removed.`);
			deleteConfirmId = '';
			await loadConfigs();
		} catch {
			toasts.error('Failed to remove MCP configuration.');
		} finally {
			deleteLoading = false;
		}
	}

	function getServerTypeLabel(type: string): string {
		switch (type) {
			case 'stdio':
				return 'stdio';
			case 'sse':
				return 'SSE';
			case 'streamable-http':
				return 'Streamable HTTP';
			default:
				return type;
		}
	}

	// Load configs on mount
	$effect(() => {
		loadConfigs();
	});
</script>

<div class="space-y-5">
	<!-- Local Agent Server -->
	{#if showLocalMode}
		<section>
			<div>
				<h3 class="text-sm font-medium text-foreground">Local Agent Server</h3>
				<p class="text-xs text-muted">
					Run agents on a locally hosted server instead of cloud sandboxes.
				</p>
			</div>

			<div class="mt-3 space-y-3">
				<label class="flex items-center gap-3 cursor-pointer">
					<input
						type="checkbox"
						bind:checked={localMode}
						onchange={() => saveField('local_mode', localMode)}
						class="h-4 w-4 rounded border-border accent-foreground"
					/>
					<span class="text-sm text-foreground">Enable Local Mode</span>
				</label>

				{#if localMode}
					<div class="flex flex-col gap-1.5">
						<label for="settings-local-sandbox-url" class="text-sm font-medium text-foreground"
							>Agent Server URL</label
						>
						<input
							id="settings-local-sandbox-url"
							type="url"
							bind:value={localSandboxUrl}
							onblur={() => saveField('local_sandbox_url', localSandboxUrl)}
							placeholder="http://localhost:8000"
							class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
						/>
						<p class="text-xs text-muted">
							URL of your locally running agent server. The server manages its own LLM and tools —
							no additional configuration needed.
						</p>
					</div>
				{/if}
			</div>
		</section>
	{/if}

	<!-- Backend URL -->
	<section class="border-t border-border-subtle pt-4">
		<div>
			<h3 class="text-sm font-medium text-foreground">Backend URL</h3>
			<p class="text-xs text-muted">Configuration for power users.</p>
		</div>

		<div class="mt-3">
			<div class="flex flex-col gap-1.5">
				<label for="settings-backend-url" class="text-sm font-medium text-foreground"
					>API Endpoint</label
				>
				<input
					id="settings-backend-url"
					type="url"
					bind:value={backendUrl}
					onblur={() => saveField('backend_url', backendUrl)}
					placeholder="https://api.midsphere.com"
					class="w-full rounded-xl border border-border bg-surface-2 px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
				/>
				<p class="text-xs text-muted">
					Override the default API endpoint. Leave empty to use the default.
				</p>
			</div>
		</div>
	</section>

	<!-- Custom MCP Servers -->
	{#if showMcp}
		<section class="border-t border-border-subtle pt-4">
			<div class="flex items-center justify-between">
				<div>
					<h3 class="text-sm font-medium text-foreground">Custom MCP Servers</h3>
					<p class="text-xs text-muted">
						Add your own Model Context Protocol servers for agent tool access.
					</p>
				</div>
				{#if !showAddForm}
					<button
						onclick={() => (showAddForm = true)}
						class="flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-1.5 text-xs font-medium text-background transition-all duration-200"
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
						Add Server
					</button>
				{/if}
			</div>

			<!-- Add Form -->
			{#if showAddForm}
				<div class="mt-3 rounded-xl border border-border bg-surface p-4">
					<h4 class="text-sm font-medium text-foreground">New MCP Server</h4>

					<div class="mt-3 space-y-4">
						<!-- Server Name -->
						<div class="flex flex-col gap-1.5">
							<label for="mcp-server-name" class="text-xs font-medium text-foreground"
								>Server Name <span class="text-accent">*</span></label
							>
							<input
								id="mcp-server-name"
								type="text"
								bind:value={formServerName}
								placeholder="e.g. my-file-server"
								class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							/>
						</div>

						<!-- Server Type -->
						<div class="flex flex-col gap-1.5">
							<label for="mcp-server-type" class="text-xs font-medium text-foreground"
								>Server Type <span class="text-accent">*</span></label
							>
							<div class="flex gap-2">
								{#each ['stdio', 'sse', 'streamable-http'] as type (type)}
									<button
										onclick={() => (formServerType = type as MCPConfigInput['server_type'])}
										class="rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-200 {formServerType ===
										type
											? 'bg-foreground text-background'
											: 'bg-surface-2 text-subtle hover:bg-surface-2 hover:text-foreground'}"
									>
										{getServerTypeLabel(type)}
									</button>
								{/each}
							</div>
						</div>

						<!-- Command (stdio only) -->
						{#if formServerType === 'stdio'}
							<div class="flex flex-col gap-1.5">
								<label for="mcp-command" class="text-xs font-medium text-foreground"
									>Command <span class="text-accent">*</span></label
								>
								<input
									id="mcp-command"
									type="text"
									bind:value={formCommand}
									placeholder="e.g. npx -y @modelcontextprotocol/server-filesystem"
									class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm font-mono text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
								/>
							</div>

							<!-- Arguments -->
							<div class="flex flex-col gap-1.5">
								<label for="mcp-args" class="text-xs font-medium text-foreground"
									>Arguments <span class="text-muted">(one per line)</span></label
								>
								<textarea
									id="mcp-args"
									bind:value={formArgs}
									placeholder="/home/user/documents&#10;--read-only"
									rows={3}
									class="w-full resize-y rounded-xl border border-border bg-background px-4 py-2 text-sm font-mono text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
								></textarea>
							</div>
						{/if}

						<!-- URL (sse / streamable-http only) -->
						{#if formServerType === 'sse' || formServerType === 'streamable-http'}
							<div class="flex flex-col gap-1.5">
								<label for="mcp-url" class="text-xs font-medium text-foreground"
									>URL <span class="text-accent">*</span></label
								>
								<input
									id="mcp-url"
									type="url"
									bind:value={formUrl}
									placeholder="https://mcp.example.com/sse"
									class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm font-mono text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
								/>
							</div>
						{/if}

						<!-- Environment Variables -->
						<div class="flex flex-col gap-1.5">
							<label for="mcp-env" class="text-xs font-medium text-foreground"
								>Environment Variables <span class="text-muted">(JSON)</span></label
							>
							<textarea
								id="mcp-env"
								bind:value={formEnv}
								placeholder={'{"API_KEY": "sk-...", "NODE_ENV": "production"}'}
								rows={2}
								class="w-full resize-y rounded-xl border border-border bg-background px-4 py-2 text-sm font-mono text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							></textarea>
						</div>

						<!-- Timeout -->
						<div class="flex flex-col gap-1.5">
							<label for="mcp-timeout" class="text-xs font-medium text-foreground"
								>Timeout <span class="text-muted">(seconds)</span></label
							>
							<input
								id="mcp-timeout"
								type="number"
								bind:value={formTimeout}
								placeholder="30"
								min="1"
								class="w-48 rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							/>
						</div>

						<!-- Description -->
						<div class="flex flex-col gap-1.5">
							<label for="mcp-description" class="text-xs font-medium text-foreground"
								>Description</label
							>
							<input
								id="mcp-description"
								type="text"
								bind:value={formDescription}
								placeholder="What does this server provide?"
								class="w-full rounded-xl border border-border bg-background px-4 py-2 text-sm text-foreground outline-none transition-all duration-200 placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)]"
							/>
						</div>

						<!-- Form Actions -->
						<div class="flex items-center gap-2 pt-2">
							<button
								onclick={handleAddConfig}
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
								Add Server
							</button>
							<button
								onclick={resetForm}
								disabled={formSubmitting}
								class="rounded-lg px-4 py-2 text-sm font-medium text-subtle transition-colors hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
							>
								Cancel
							</button>
						</div>
					</div>
				</div>
			{/if}

			<!-- Configs List -->
			<div class="mt-3">
				{#if configsLoading}
					<div class="space-y-3">
						{#each [0, 1] as i (i)}
							<div class="animate-pulse rounded-xl border border-border-subtle bg-surface p-4">
								<div class="h-4 w-32 rounded bg-surface-2"></div>
								<div class="mt-2 h-3 w-48 rounded bg-surface-2"></div>
							</div>
						{/each}
					</div>
				{:else if configsError}
					<div
						class="rounded-xl border border-border-subtle bg-surface px-4 py-6 text-center text-sm text-muted"
					>
						{configsError}
						<button
							onclick={loadConfigs}
							class="mt-2 block w-full text-xs font-medium text-accent hover:underline"
						>
							Try again
						</button>
					</div>
				{:else if configs.length === 0}
					<div class="rounded-xl border border-dashed border-border-strong px-4 py-8 text-center">
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
							class="mx-auto text-muted"
						>
							<rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
							<rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
							<line x1="6" y1="6" x2="6.01" y2="6" />
							<line x1="6" y1="18" x2="6.01" y2="18" />
						</svg>
						<p class="mt-2 text-sm text-muted">No custom MCP servers configured.</p>
						<p class="mt-1 text-xs text-muted">
							Add servers to extend agent capabilities with your own tools.
						</p>
					</div>
				{:else}
					<div class="space-y-2">
						{#each configs as config (config.id)}
							<div
								class="group rounded-xl border border-border bg-surface px-4 py-3 transition-colors hover:bg-surface-2"
							>
								<div class="flex items-start justify-between gap-3">
									<div class="min-w-0 flex-1">
										<div class="flex items-center gap-2">
											<span class="text-sm font-medium text-foreground">{config.server_name}</span>
											<span
												class="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted"
											>
												{getServerTypeLabel(config.server_type)}
											</span>
										</div>
										{#if config.description}
											<p class="mt-0.5 text-xs text-muted">
												{config.description}
											</p>
										{/if}
										<p class="mt-1 truncate text-xs font-mono text-muted">
											{#if config.server_type === 'stdio'}
												{config.command || '—'}
											{:else}
												{config.url || '—'}
											{/if}
										</p>
									</div>

									<!-- Delete button / confirm -->
									{#if deleteConfirmId === config.id}
										<div class="flex shrink-0 items-center gap-1.5">
											<button
												onclick={() => handleDeleteConfig(config.id, config.server_name)}
												disabled={deleteLoading}
												class="rounded-lg bg-red-500/10 px-2.5 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-500/20 disabled:opacity-50 dark:text-red-400"
											>
												{deleteLoading ? 'Removing...' : 'Confirm'}
											</button>
											<button
												onclick={() => (deleteConfirmId = '')}
												disabled={deleteLoading}
												class="rounded-lg px-2 py-1 text-xs text-muted transition-colors hover:text-foreground disabled:opacity-50"
											>
												Cancel
											</button>
										</div>
									{:else}
										<button
											onclick={() => (deleteConfirmId = config.id)}
											class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-muted opacity-0 transition-all hover:bg-red-500/10 hover:text-red-500 group-hover:opacity-100"
											aria-label="Delete {config.server_name}"
											use:tooltip={'Delete'}
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
												<polyline points="3 6 5 6 21 6" />
												<path
													d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"
												/>
											</svg>
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</section>
	{/if}
</div>
