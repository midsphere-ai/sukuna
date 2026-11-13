<script lang="ts">
	import { fade } from 'svelte/transition';
	import { formatDate, formatUptime } from '$utils/formatDate';
	import type { ClawStatus } from '$api/claw';

	let {
		status = null,
		loading = false,
		activating = false,
		onactivate,
		ondeactivate
	}: {
		status: ClawStatus | null;
		loading: boolean;
		activating: boolean;
		onactivate: () => void;
		ondeactivate: () => void;
	} = $props();

	let isActive = $derived(status?.active ?? false);
</script>

<div class="rounded-xl border border-border p-4" in:fade={{ duration: 100, delay: 30 }}>
	<div class="mb-3 flex items-center justify-between">
		<h2 class="text-sm font-medium text-foreground">Sandbox Status</h2>
		{#if status}
			<span
				class="rounded-full px-2.5 py-0.5 text-xs font-medium {isActive
					? 'bg-green-100 text-green-700'
					: 'bg-surface text-muted'}"
			>
				{isActive ? 'Active' : 'Inactive'}
			</span>
		{/if}
	</div>

	{#if loading && !status}
		<div class="flex items-center justify-center py-6">
			<svg
				class="h-5 w-5 animate-spin text-muted"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				aria-hidden="true"
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
	{:else if status}
		<div class="mb-4 grid grid-cols-2 gap-3 text-sm">
			<div>
				<p class="text-xs text-muted">State</p>
				<p class="font-medium text-foreground">{status.sandbox_state}</p>
			</div>
			<div>
				<p class="text-xs text-muted">Uptime</p>
				<p class="font-medium text-foreground">{formatUptime(status.uptime_seconds)}</p>
			</div>
			<div>
				<p class="text-xs text-muted">Last Used</p>
				<p class="font-medium text-foreground">{formatDate(status.last_used_at)}</p>
			</div>
			<div>
				<p class="text-xs text-muted">Created</p>
				<p class="font-medium text-foreground">{formatDate(status.created_at)}</p>
			</div>
		</div>

		<div class="flex gap-2">
			{#if isActive}
				<button
					onclick={ondeactivate}
					class="rounded-lg border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-surface"
				>
					Deactivate
				</button>
			{:else}
				<button
					onclick={onactivate}
					disabled={activating}
					class="rounded-xl bg-foreground px-6 py-3 text-sm font-medium text-background hover:opacity-70 disabled:opacity-50"
				>
					{#if activating}
						<span class="inline-flex items-center gap-2">
							<svg
								class="h-4 w-4 animate-spin"
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								aria-hidden="true"
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
							Activating...
						</span>
					{:else}
						Activate Sandbox
					{/if}
				</button>
			{/if}
		</div>
	{:else}
		<p class="py-4 text-sm text-muted">Unable to load sandbox status.</p>
		<button
			onclick={onactivate}
			disabled={activating}
			class="rounded-xl bg-foreground px-6 py-3 text-sm font-medium text-background hover:opacity-70 disabled:opacity-50"
		>
			{activating ? 'Activating...' : 'Activate Sandbox'}
		</button>
	{/if}
</div>
