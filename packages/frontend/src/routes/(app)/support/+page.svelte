<script lang="ts">
	import { onMount } from 'svelte';
	import { Skeleton, EmptyState, PageHeader } from '$components/ui';
	import { pageTitle, showHeaderTitle } from '$stores/page';
	import { toasts } from '$stores/toast';
	import {
		getSupportTickets,
		createSupportTicket,
		updateSupportTicket,
		deleteSupportTicket
	} from '$api/billing';
	import type { SupportTicket } from '$api/types';

	let tickets: SupportTicket[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	// New ticket form
	let showNewForm = $state(false);
	let newTitle = $state('');
	let newMessage = $state('');
	let submitting = $state(false);

	// Detail view
	let selectedTicket: SupportTicket | null = $state(null);

	// Follow-up / edit
	let editingFollowUp = $state(false);
	let followUpMessage = $state('');
	let followUpLoading = $state(false);

	// Delete
	let deleteDialogOpen = $state(false);
	let deleteTarget: SupportTicket | null = $state(null);
	let deleteLoading = $state(false);

	// Sort
	let sortBy: 'date' | 'status' = $state('date');

	pageTitle.set('Support');
	showHeaderTitle.set(false);

	function statusColor(status: string): string {
		switch (status) {
			case 'open':
				return 'bg-accent/15 text-accent';
			case 'in_progress':
				return 'bg-amber-100 text-amber-700';
			case 'resolved':
				return 'bg-success/15 text-success';
			case 'closed':
				return 'bg-surface-2 text-subtle';
			default:
				return 'bg-surface-2 text-subtle';
		}
	}

	function statusLabel(status: string): string {
		switch (status) {
			case 'open':
				return 'Open';
			case 'in_progress':
				return 'In Progress';
			case 'resolved':
				return 'Resolved';
			case 'closed':
				return 'Closed';
			default:
				return status;
		}
	}

	const statusOrder: Record<string, number> = {
		open: 0,
		in_progress: 1,
		resolved: 2,
		closed: 3
	};

	let sortedTickets = $derived.by(() => {
		const sorted = [...tickets];
		if (sortBy === 'status') {
			sorted.sort((a, b) => (statusOrder[a.status] ?? 4) - (statusOrder[b.status] ?? 4));
		} else {
			sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
		}
		return sorted;
	});

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	}

	async function loadTickets(): Promise<void> {
		loading = true;
		error = '';
		try {
			const response = await getSupportTickets();
			tickets = response.items ?? (Array.isArray(response) ? (response as SupportTicket[]) : []);
		} catch {
			error = 'Failed to load support tickets.';
		} finally {
			loading = false;
		}
	}

	async function handleCreateTicket(): Promise<void> {
		if (!newTitle.trim() || !newMessage.trim()) return;
		submitting = true;
		try {
			const ticket = await createSupportTicket(newTitle.trim(), newMessage.trim());
			tickets = [ticket, ...tickets];
			newTitle = '';
			newMessage = '';
			showNewForm = false;
			toasts.success('Ticket created successfully.');
		} catch {
			toasts.error('Failed to create ticket.');
		} finally {
			submitting = false;
		}
	}

	async function handleFollowUp(): Promise<void> {
		if (!selectedTicket || !followUpMessage.trim()) return;
		followUpLoading = true;
		try {
			const updated = await updateSupportTicket(selectedTicket.id, {
				message: followUpMessage.trim()
			});
			tickets = tickets.map((t) => (t.id === updated.id ? updated : t));
			selectedTicket = updated;
			followUpMessage = '';
			editingFollowUp = false;
			toasts.success('Follow-up added.');
		} catch {
			toasts.error('Failed to add follow-up.');
		} finally {
			followUpLoading = false;
		}
	}

	function openDeleteDialog(ticket: SupportTicket): void {
		deleteTarget = ticket;
		deleteDialogOpen = true;
	}

	async function handleDelete(): Promise<void> {
		if (!deleteTarget) return;
		deleteLoading = true;
		try {
			await deleteSupportTicket(deleteTarget.id);
			tickets = tickets.filter((t) => t.id !== deleteTarget!.id);
			if (selectedTicket?.id === deleteTarget.id) {
				selectedTicket = null;
			}
			deleteDialogOpen = false;
			deleteTarget = null;
			toasts.success('Ticket deleted.');
		} catch {
			toasts.error('Failed to delete ticket.');
		} finally {
			deleteLoading = false;
		}
	}

	function selectTicket(ticket: SupportTicket): void {
		selectedTicket = ticket;
		editingFollowUp = false;
		followUpMessage = '';
	}

	function backToList(): void {
		selectedTicket = null;
		editingFollowUp = false;
	}

	onMount(() => {
		loadTickets();
	});
</script>

<svelte:head>
	<title>Support - Jatayu AI</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
	<!-- Page header -->
	<div class="mb-8 flex items-start justify-between">
		<PageHeader
			title="Support"
			description="Create and track support tickets for billing or technical issues."
		/>
		{#if !selectedTicket && !showNewForm}
			<button
				onclick={() => (showNewForm = true)}
				class="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90"
			>
				New Ticket
			</button>
		{/if}
	</div>

	{#if loading}
		<!-- Loading skeleton -->
		<div class="space-y-4">
			{#each [0, 1, 2] as i (i)}
				<div class="rounded-xl border border-border-subtle bg-background p-5">
					<Skeleton class="mb-3 h-5 w-48" />
					<Skeleton class="mb-2 h-4 w-full" />
					<Skeleton class="h-4 w-32" />
				</div>
			{/each}
		</div>
	{:else if error}
		<!-- Error state -->
		<div class="rounded-xl border border-accent/20 bg-accent/5 p-8 text-center">
			<svg
				class="mx-auto mb-3 h-8 w-8 text-accent/60"
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
			>
				<circle cx="12" cy="12" r="10" />
				<path d="M12 8v4m0 4h.01" />
			</svg>
			<p class="text-sm text-foreground">{error}</p>
			<button
				onclick={loadTickets}
				class="mt-4 rounded-lg bg-surface-2 px-4 py-2 text-xs font-medium text-foreground transition-colors hover:bg-surface-2"
			>
				Try again
			</button>
		</div>
	{:else if showNewForm}
		<!-- New Ticket Form -->
		<div class="rounded-xl border border-border-subtle bg-background p-6">
			<div class="mb-4 flex items-center justify-between">
				<h2 class="font-junicode text-lg text-foreground">New Ticket</h2>
				<button
					onclick={() => {
						showNewForm = false;
						newTitle = '';
						newMessage = '';
					}}
					class="text-sm text-subtle transition-colors hover:text-foreground"
				>
					Cancel
				</button>
			</div>
			<form
				onsubmit={(e) => {
					e.preventDefault();
					handleCreateTicket();
				}}
				class="space-y-4"
			>
				<div>
					<label for="ticket-title" class="mb-1 block text-sm font-medium text-foreground">
						Title
					</label>
					<input
						id="ticket-title"
						type="text"
						bind:value={newTitle}
						placeholder="Brief summary of your issue"
						required
						class="w-full rounded-lg border border-border bg-cream px-3 py-2 text-sm text-foreground placeholder:text-muted focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/20"
					/>
				</div>
				<div>
					<label for="ticket-message" class="mb-1 block text-sm font-medium text-foreground">
						Message
					</label>
					<textarea
						id="ticket-message"
						bind:value={newMessage}
						placeholder="Describe your issue in detail..."
						required
						rows={5}
						class="w-full resize-none rounded-lg border border-border bg-cream px-3 py-2 text-sm text-foreground placeholder:text-muted focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/20"
					></textarea>
				</div>
				<div class="flex justify-end">
					<button
						type="submit"
						disabled={submitting || !newTitle.trim() || !newMessage.trim()}
						class="rounded-lg bg-accent px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
					>
						{submitting ? 'Submitting...' : 'Submit Ticket'}
					</button>
				</div>
			</form>
		</div>
	{:else if selectedTicket}
		<!-- Ticket Detail View -->
		<div class="space-y-4">
			<button
				onclick={backToList}
				class="flex items-center gap-1 text-sm text-subtle transition-colors hover:text-foreground"
			>
				<svg
					class="h-4 w-4"
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<path d="M15 18l-6-6 6-6" />
				</svg>
				Back to tickets
			</button>

			<div class="rounded-xl border border-border-subtle bg-background p-6">
				<!-- Header -->
				<div class="mb-4 flex items-start justify-between">
					<div>
						<h2 class="font-junicode text-xl text-foreground">
							{selectedTicket.title}
						</h2>
						<div class="mt-2 flex items-center gap-3">
							<span
								class="rounded-full px-2.5 py-0.5 text-xs font-medium {statusColor(
									selectedTicket.status
								)}"
							>
								{statusLabel(selectedTicket.status)}
							</span>
							<span class="text-xs text-muted">
								Created {formatDate(selectedTicket.created_at)}
							</span>
						</div>
					</div>
					<button
						onclick={() => openDeleteDialog(selectedTicket!)}
						class="rounded-lg border border-accent/20 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/5"
					>
						Delete
					</button>
				</div>

				<!-- Message -->
				<div class="mb-4 rounded-lg bg-cream/60 p-4">
					<p class="whitespace-pre-wrap text-sm text-foreground">{selectedTicket.message}</p>
				</div>

				<!-- Updated timestamp -->
				{#if selectedTicket.updated_at !== selectedTicket.created_at}
					<p class="mb-4 text-xs text-muted">
						Last updated {formatDate(selectedTicket.updated_at)}
					</p>
				{/if}

				<!-- Follow-up actions -->
				{#if selectedTicket.status !== 'closed'}
					{#if editingFollowUp}
						<div class="border-t border-border-subtle pt-4">
							<label for="follow-up" class="mb-1 block text-sm font-medium text-foreground">
								Add follow-up
							</label>
							<textarea
								id="follow-up"
								bind:value={followUpMessage}
								placeholder="Add additional details or follow up on this ticket..."
								rows={3}
								class="mb-3 w-full resize-none rounded-lg border border-border bg-cream px-3 py-2 text-sm text-foreground placeholder:text-muted focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/20"
							></textarea>
							<div class="flex gap-2">
								<button
									onclick={handleFollowUp}
									disabled={followUpLoading || !followUpMessage.trim()}
									class="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
								>
									{followUpLoading ? 'Sending...' : 'Send'}
								</button>
								<button
									onclick={() => {
										editingFollowUp = false;
										followUpMessage = '';
									}}
									class="rounded-lg bg-surface-2 px-4 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
								>
									Cancel
								</button>
							</div>
						</div>
					{:else}
						<div class="border-t border-border-subtle pt-4">
							<button
								onclick={() => (editingFollowUp = true)}
								class="rounded-lg bg-surface-2 px-4 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
							>
								Add follow-up
							</button>
						</div>
					{/if}
				{/if}
			</div>
		</div>
	{:else}
		<!-- Ticket List -->
		<div class="space-y-4">
			<!-- Sort controls -->
			{#if tickets.length > 0}
				<div class="flex items-center gap-2">
					<span class="text-xs text-muted">Sort by:</span>
					<button
						onclick={() => (sortBy = 'date')}
						class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors {sortBy === 'date'
							? 'bg-surface-2 text-foreground'
							: 'text-subtle hover:text-foreground'}"
					>
						Date
					</button>
					<button
						onclick={() => (sortBy = 'status')}
						class="rounded-md px-2.5 py-1 text-xs font-medium transition-colors {sortBy === 'status'
							? 'bg-surface-2 text-foreground'
							: 'text-subtle hover:text-foreground'}"
					>
						Status
					</button>
				</div>
			{/if}

			{#if tickets.length === 0}
				<EmptyState
					title="No tickets"
					description="Need help? Create a support ticket and our team will get back to you."
					ctaLabel="Create ticket"
					onctaclick={() => (showNewForm = true)}
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
								><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg
							>
						</div>
					{/snippet}
				</EmptyState>
			{:else}
				{#each sortedTickets as ticket (ticket.id)}
					<!-- svelte-ignore a11y_interactive_supports_focus -->
					<div
						role="button"
						onclick={() => selectTicket(ticket)}
						onkeydown={(e) => e.key === 'Enter' && selectTicket(ticket)}
						class="cursor-pointer rounded-xl border border-border-subtle bg-background p-5 transition-colors hover:border-border-strong"
					>
						<div class="flex items-start justify-between gap-3">
							<div class="min-w-0 flex-1">
								<h3 class="truncate text-sm font-medium text-foreground">
									{ticket.title}
								</h3>
								<p class="mt-1 line-clamp-2 text-xs text-subtle">
									{ticket.message}
								</p>
							</div>
							<span
								class="shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium {statusColor(
									ticket.status
								)}"
							>
								{statusLabel(ticket.status)}
							</span>
						</div>
						<div class="mt-3 flex items-center gap-3 text-xs text-muted">
							<span>{formatDate(ticket.created_at)}</span>
							{#if ticket.updated_at !== ticket.created_at}
								<span>· Updated {formatDate(ticket.updated_at)}</span>
							{/if}
						</div>
					</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>

<!-- Delete Confirmation Dialog -->
{#if deleteDialogOpen && deleteTarget}
	<!-- svelte-ignore a11y_interactive_supports_focus -->
	<div
		role="dialog"
		aria-label="Delete ticket confirmation"
		class="fixed inset-0 z-50 flex items-center justify-center bg-foreground/30 p-4"
		onclick={() => {
			deleteDialogOpen = false;
			deleteTarget = null;
		}}
		onkeydown={(e) => {
			if (e.key === 'Escape') {
				deleteDialogOpen = false;
				deleteTarget = null;
			}
		}}
	>
		<div
			role="document"
			class="w-full max-w-md rounded-xl bg-background p-6 shadow-lg"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<h3 class="font-junicode text-lg text-foreground">Delete ticket?</h3>
			<p class="mt-2 text-sm text-subtle">
				Are you sure you want to delete "{deleteTarget.title}"? This action cannot be undone.
			</p>
			<div class="mt-6 flex justify-end gap-3">
				<button
					onclick={() => {
						deleteDialogOpen = false;
						deleteTarget = null;
					}}
					class="rounded-lg bg-surface-2 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
				>
					Cancel
				</button>
				<button
					onclick={handleDelete}
					disabled={deleteLoading}
					class="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
				>
					{deleteLoading ? 'Deleting...' : 'Delete'}
				</button>
			</div>
		</div>
	</div>
{/if}
