<script lang="ts">
	import { onMount } from 'svelte';
	import { toasts } from '$stores/toast';
	import {
		getArchives,
		verifyArchive,
		type ArchivePage,
		type ArchiveFilters,
		type ArchiveVerifyResult
	} from '$api/compliance';

	let archiveData: ArchivePage | null = $state(null);
	let loading = $state(true);

	// Filter state
	let filterOrgId = $state('');
	let filterConversationId = $state('');
	let filterDateFrom = $state('');
	let filterDateTo = $state('');
	let page = $state(1);
	let pageSize = 25;

	// Verification state per row
	let verifyResults: Record<string, ArchiveVerifyResult> = $state({});
	let verifyingId: string | null = $state(null);

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

	function truncate(str: string, len: number): string {
		if (!str) return '-';
		return str.length > len ? str.slice(0, len) + '...' : str;
	}

	async function loadArchives(): Promise<void> {
		loading = true;
		try {
			const filters: ArchiveFilters = {
				page,
				page_size: pageSize
			};
			if (filterOrgId.trim()) filters.organization_id = filterOrgId.trim();
			if (filterConversationId.trim()) filters.conversation_id = filterConversationId.trim();
			if (filterDateFrom) filters.date_from = filterDateFrom;
			if (filterDateTo) filters.date_to = filterDateTo;
			archiveData = await getArchives(filters);
		} catch {
			// Error handled by API client
		} finally {
			loading = false;
		}
	}

	function handleSearch(): void {
		page = 1;
		verifyResults = {};
		loadArchives();
	}

	function handlePage(newPage: number): void {
		page = newPage;
		verifyResults = {};
		loadArchives();
	}

	async function handleVerify(id: string): Promise<void> {
		verifyingId = id;
		try {
			const result = await verifyArchive(id);
			verifyResults[id] = result;
		} catch {
			toasts.error('Failed to verify archive.');
		} finally {
			verifyingId = null;
		}
	}

	function copyToClipboard(text: string): void {
		navigator.clipboard.writeText(text).then(
			() => toasts.success('Copied to clipboard.'),
			() => toasts.error('Failed to copy.')
		);
	}

	onMount(() => {
		loadArchives();
	});
</script>

<div class="space-y-4">
	<div>
		<h3 class="text-sm font-medium text-foreground">Conversation Archives</h3>
		<p class="text-xs text-muted">Browse and verify archived conversation integrity.</p>
	</div>

	<!-- Filter Bar -->
	<div class="flex flex-wrap items-end gap-3">
		<div>
			<label for="archive-org" class="mb-1 block text-xs font-medium text-muted"
				>Organization ID</label
			>
			<input
				id="archive-org"
				type="text"
				bind:value={filterOrgId}
				placeholder="org-..."
				class="w-40 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
			/>
		</div>
		<div>
			<label for="archive-conv" class="mb-1 block text-xs font-medium text-muted"
				>Conversation ID</label
			>
			<input
				id="archive-conv"
				type="text"
				bind:value={filterConversationId}
				placeholder="conv-..."
				class="w-40 rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
			/>
		</div>
		<div>
			<label for="archive-from" class="mb-1 block text-xs font-medium text-muted">From</label>
			<input
				id="archive-from"
				type="date"
				bind:value={filterDateFrom}
				class="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
			/>
		</div>
		<div>
			<label for="archive-to" class="mb-1 block text-xs font-medium text-muted">To</label>
			<input
				id="archive-to"
				type="date"
				bind:value={filterDateTo}
				class="rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none"
			/>
		</div>
		<button
			onclick={handleSearch}
			class="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background"
		>
			Search
		</button>
	</div>

	<!-- Table -->
	{#if loading}
		<div class="flex items-center justify-center py-12">
			<svg
				class="h-5 w-5 animate-spin text-muted"
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
	{:else if archiveData && archiveData.results.length > 0}
		<div class="overflow-x-auto rounded-xl border border-border">
			<table class="w-full text-left text-sm">
				<thead>
					<tr class="border-b border-border-subtle bg-surface">
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Archived At</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Conversation</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Organization</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Archived By</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Content Hash</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Version</th>
						<th class="px-4 py-2.5 text-xs font-medium text-muted">Verify</th>
					</tr>
				</thead>
				<tbody>
					{#each archiveData.results as entry (entry.id)}
						<tr class="border-b border-border-subtle last:border-0">
							<td class="whitespace-nowrap px-4 py-2.5 text-xs text-foreground">
								{formatDate(entry.archived_at)}
							</td>
							<td class="px-4 py-2.5 text-xs text-foreground">
								{entry.conversation_id ? truncate(entry.conversation_id, 12) : '-'}
							</td>
							<td class="px-4 py-2.5 text-xs text-muted">
								{truncate(entry.organization_id, 12)}
							</td>
							<td class="px-4 py-2.5 text-xs text-muted">{entry.archived_by}</td>
							<td class="px-4 py-2.5">
								<button
									onclick={() => copyToClipboard(entry.content_hash)}
									class="font-mono text-xs text-muted hover:text-foreground"
									title="Click to copy full hash"
								>
									{truncate(entry.content_hash, 16)}
								</button>
							</td>
							<td class="px-4 py-2.5 text-xs text-muted">{entry.version}</td>
							<td class="px-4 py-2.5">
								{#if verifyResults[entry.id]}
									{#if verifyResults[entry.id].verified}
										<span class="flex items-center gap-1 text-xs font-medium text-success">
											<svg
												class="h-4 w-4"
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="2"
												stroke="currentColor"
											>
												<path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
											</svg>
											Verified
										</span>
									{:else}
										<span class="flex items-center gap-1 text-xs font-medium text-red-600">
											<svg
												class="h-4 w-4"
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="2"
												stroke="currentColor"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													d="M6 18L18 6M6 6l12 12"
												/>
											</svg>
											Tampered
										</span>
										<div class="mt-1 text-[10px] text-muted">
											stored: {truncate(verifyResults[entry.id].stored_hash, 12)}<br />
											computed: {truncate(verifyResults[entry.id].computed_hash, 12)}
										</div>
									{/if}
								{:else}
									<button
										onclick={() => handleVerify(entry.id)}
										disabled={verifyingId === entry.id}
										class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-surface disabled:opacity-50"
									>
										{verifyingId === entry.id ? 'Verifying...' : 'Verify'}
									</button>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Pagination -->
		{#if archiveData.total_pages > 1}
			<div class="flex items-center justify-between">
				<p class="text-xs text-muted">
					Page {archiveData.page} of {archiveData.total_pages} ({archiveData.total} total)
				</p>
				<div class="flex gap-2">
					{#if archiveData.page > 1}
						<button
							onclick={() => handlePage(archiveData!.page - 1)}
							class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface"
						>
							Previous
						</button>
					{/if}
					{#if archiveData.page < archiveData.total_pages}
						<button
							onclick={() => handlePage(archiveData!.page + 1)}
							class="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface"
						>
							Next
						</button>
					{/if}
				</div>
			</div>
		{/if}
	{:else}
		<p class="py-8 text-center text-sm text-muted">No archives found.</p>
	{/if}
</div>
