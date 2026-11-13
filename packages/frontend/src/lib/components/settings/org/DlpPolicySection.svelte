<script lang="ts">
	import { onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { toasts } from '$stores/toast';
	import {
		getDlpPolicy,
		updateDlpPolicy,
		testDlpPolicy,
		type Organization,
		type DlpPolicy,
		type DlpPattern,
		type DlpTestResult
	} from '$api/organizations';

	let { orgId, org }: { orgId: string; org: Organization } = $props();

	let policy: DlpPolicy | null = $state(null);
	let loading = $state(true);
	let saving = $state(false);

	// Add pattern form
	let newPattern = $state('');
	let newType = $state('regex');
	let newAction = $state('block');

	// Test panel
	let testText = $state('');
	let testing = $state(false);
	let testResult: DlpTestResult | null = $state(null);

	async function load() {
		loading = true;
		try {
			policy = await getDlpPolicy(orgId);
		} catch {
			policy = { scan_patterns: [], is_active: false };
		} finally {
			loading = false;
		}
	}

	async function toggleActive() {
		if (!policy) return;
		saving = true;
		try {
			policy = await updateDlpPolicy(orgId, { is_active: !policy.is_active });
			toasts.success(`DLP policy ${policy.is_active ? 'enabled' : 'disabled'}.`);
		} catch {
			toasts.error('Failed to update DLP policy.');
		} finally {
			saving = false;
		}
	}

	async function addPattern() {
		if (!policy || !newPattern.trim()) return;
		saving = true;
		try {
			const patterns = [
				...policy.scan_patterns,
				{ pattern: newPattern.trim(), type: newType, action: newAction }
			];
			policy = await updateDlpPolicy(orgId, { scan_patterns: patterns });
			toasts.success('Pattern added.');
			newPattern = '';
			newType = 'regex';
			newAction = 'block';
		} catch {
			toasts.error('Failed to add pattern.');
		} finally {
			saving = false;
		}
	}

	async function removePattern(index: number) {
		if (!policy) return;
		saving = true;
		try {
			const patterns = policy.scan_patterns.filter((_, i) => i !== index);
			policy = await updateDlpPolicy(orgId, { scan_patterns: patterns });
			toasts.success('Pattern removed.');
		} catch {
			toasts.error('Failed to remove pattern.');
		} finally {
			saving = false;
		}
	}

	async function handleTest() {
		if (!testText.trim()) return;
		testing = true;
		testResult = null;
		try {
			testResult = await testDlpPolicy(orgId, { text: testText });
		} catch {
			toasts.error('Failed to test DLP policy.');
		} finally {
			testing = false;
		}
	}

	onMount(load);
</script>

<div class="space-y-4">
	<div class="flex items-center justify-between">
		<div>
			<h3 class="text-sm font-medium text-foreground">Data Loss Prevention</h3>
			<p class="text-xs text-muted">
				Scan agent outputs for sensitive patterns and block or redact matches.
			</p>
		</div>
		{#if policy && (org.your_role === 'admin' || org.your_role === 'owner')}
			<label class="relative inline-flex cursor-pointer items-center">
				<input
					type="checkbox"
					class="peer sr-only"
					checked={policy.is_active}
					onchange={toggleActive}
					disabled={saving}
				/>
				<div
					class="h-6 w-11 rounded-full bg-border-strong peer-checked:bg-accent peer-focus:outline-none after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all peer-checked:after:translate-x-5"
				></div>
			</label>
		{/if}
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-6">
			<svg
				class="h-5 w-5 animate-spin text-muted"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
				></circle><path
					class="opacity-75"
					fill="currentColor"
					d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
				></path></svg
			>
		</div>
	{:else if policy}
		<!-- Pattern list -->
		{#if policy.scan_patterns.length > 0}
			<div class="overflow-x-auto rounded-xl border border-border">
				<table class="w-full text-left">
					<thead class="bg-surface">
						<tr>
							<th class="px-4 py-2.5 text-xs font-medium text-muted">Pattern</th>
							<th class="px-4 py-2.5 text-xs font-medium text-muted">Type</th>
							<th class="px-4 py-2.5 text-xs font-medium text-muted">Action</th>
							<th class="px-4 py-2.5 text-xs font-medium text-muted"></th>
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each policy.scan_patterns as pat, i}
							<tr>
								<td class="px-4 py-2.5 font-mono text-xs text-foreground">{pat.pattern}</td>
								<td class="px-4 py-2.5">
									<span
										class="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
										>{pat.type}</span
									>
								</td>
								<td class="px-4 py-2.5">
									{#if pat.action === 'block'}
										<span
											class="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400"
											>block</span
										>
									{:else}
										<span
											class="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-400"
											>redact</span
										>
									{/if}
								</td>
								<td class="px-4 py-2.5 text-right">
									{#if org.your_role === 'admin' || org.your_role === 'owner'}
										<button
											onclick={() => removePattern(i)}
											disabled={saving}
											class="text-xs font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
											>Remove</button
										>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<p class="py-4 text-center text-xs text-muted">No DLP patterns configured.</p>
		{/if}

		<!-- Add pattern form -->
		{#if org.your_role === 'admin' || org.your_role === 'owner'}
			<div class="rounded-xl border border-border-subtle bg-surface p-4">
				<h4 class="mb-3 text-xs font-medium text-foreground">Add Pattern</h4>
				<div class="flex flex-col gap-3 sm:flex-row sm:items-end">
					<div class="flex-1">
						<label for="dlp-pattern" class="mb-1 block text-xs font-medium text-muted"
							>Pattern</label
						>
						<input
							id="dlp-pattern"
							type="text"
							bind:value={newPattern}
							placeholder="e.g. \b\d{3}-\d{2}-\d{4}\b"
							class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
						/>
					</div>
					<div class="w-32">
						<label for="dlp-type" class="mb-1 block text-xs font-medium text-muted">Type</label>
						<select
							id="dlp-type"
							bind:value={newType}
							class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
						>
							<option value="regex">regex</option>
							<option value="keyword">keyword</option>
						</select>
					</div>
					<div class="w-32">
						<label for="dlp-action" class="mb-1 block text-xs font-medium text-muted">Action</label>
						<select
							id="dlp-action"
							bind:value={newAction}
							class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
						>
							<option value="block">block</option>
							<option value="redact">redact</option>
						</select>
					</div>
					<button
						onclick={addPattern}
						disabled={saving || !newPattern.trim()}
						class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
					>
						Add
					</button>
				</div>
			</div>

			<!-- Test panel -->
			<div class="rounded-xl border border-border-subtle bg-surface p-4">
				<h4 class="mb-3 text-xs font-medium text-foreground">Test DLP Policy</h4>
				<div class="space-y-3">
					<textarea
						bind:value={testText}
						rows={3}
						placeholder="Enter sample text to test against your DLP patterns..."
						class="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
					></textarea>
					<div class="flex items-center gap-3">
						<button
							onclick={handleTest}
							disabled={testing || !testText.trim()}
							class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background hover:opacity-70 disabled:opacity-50"
						>
							{testing ? 'Testing...' : 'Test'}
						</button>
						{#if testResult}
							<div transition:fade={{ duration: 100 }}>
								{#if testResult.matches}
									<span class="text-xs font-medium text-red-600"
										>Matched: {testResult.matched_patterns.join(', ')}</span
									>
								{:else}
									<span class="text-xs font-medium text-green-600">No matches</span>
								{/if}
							</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	{/if}
</div>
