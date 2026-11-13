<script lang="ts">
	import {
		featureFlags,
		modifiedCount,
		setFlagState,
		resetAllFlags,
		type FlagState
	} from '$stores/featureFlags';
	import { toasts } from '$stores/toast';
	import { tooltip } from '$lib/actions/tooltip';

	function handleFlagChange(id: string, value: string): void {
		let state: FlagState;
		if (value === 'enabled') state = true;
		else if (value === 'disabled') state = false;
		else state = null;
		setFlagState(id, state);
	}

	function handleResetAll(): void {
		resetAllFlags();
		toasts.success('All flags reset to default.');
	}

	function selectValue(state: FlagState): string {
		if (state === true) return 'enabled';
		if (state === false) return 'disabled';
		return 'default';
	}
</script>

<svelte:head>
	<title>Experimental Features</title>
</svelte:head>

<div class="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6">
	<!-- Warning banner -->
	<div class="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3">
		<div class="flex items-start gap-3">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				width="18"
				height="18"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
			>
				<path
					d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
				/>
				<line x1="12" y1="9" x2="12" y2="13" />
				<line x1="12" y1="17" x2="12.01" y2="17" />
			</svg>
			<p class="text-sm text-amber-700 dark:text-amber-300">
				These are experimental features that are still in development. Enabling them may affect
				stability or change how the app behaves. Use at your own risk.
			</p>
		</div>
	</div>

	<!-- Header -->
	<div class="mb-6 flex items-center justify-between">
		<div>
			<div class="flex items-center gap-2.5">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					width="22"
					height="22"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.75"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="text-foreground"
				>
					<path d="M9 3h6v7l3 7H6l3-7V3z" />
					<path d="M6 17h12v2a2 2 0 01-2 2H8a2 2 0 01-2-2v-2z" />
					<line x1="10" y1="3" x2="10" y2="1" />
					<line x1="14" y1="3" x2="14" y2="1" />
				</svg>
				<h1 class="text-lg font-medium text-foreground">Experimental Features</h1>
			</div>
			{#if $modifiedCount > 0}
				<p class="mt-1 text-xs text-muted">
					{$modifiedCount} feature{$modifiedCount === 1 ? '' : 's'} modified from default
				</p>
			{:else}
				<p class="mt-1 text-xs text-muted">All features are at their default settings</p>
			{/if}
		</div>

		{#if $modifiedCount > 0}
			<button
				onclick={handleResetAll}
				class="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground transition-all duration-200 hover:bg-surface-2"
				use:tooltip={'Reset all flags to default'}
			>
				Reset all
			</button>
		{/if}
	</div>

	<!-- Flags list -->
	<div class="space-y-3">
		{#each $featureFlags as flag (flag.id)}
			{@const modified = flag.state !== null}
			<div
				class="rounded-xl border bg-surface px-5 py-4 transition-all duration-200 {modified
					? 'border-l-2 border-border ' +
						(flag.state === true ? 'border-l-coral' : 'border-l-red-400')
					: 'border-border-subtle'}"
			>
				<div class="flex items-start justify-between gap-4">
					<div class="min-w-0 flex-1">
						<h3 class="text-sm font-medium text-foreground">{flag.name}</h3>
						<p class="mt-1 text-xs leading-relaxed text-muted">
							{flag.description}
						</p>
						<span
							class="mt-2 inline-block rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-subtle"
						>
							{flag.id}
						</span>
					</div>

					<div class="shrink-0 pt-0.5">
						<select
							value={selectValue(flag.state)}
							onchange={(e) => handleFlagChange(flag.id, e.currentTarget.value)}
							class="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium text-foreground outline-none transition-all duration-200 focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)] {modified
								? 'border-accent/40'
								: ''}"
						>
							<option value="default">Default</option>
							<option value="enabled">Enabled</option>
							<option value="disabled">Disabled</option>
						</select>
					</div>
				</div>
			</div>
		{/each}
	</div>

	<!-- Footer -->
	<div class="mt-8 text-center">
		<p class="text-xs text-muted/60">
			Feature flags are stored locally and will not sync across devices.
		</p>
	</div>
</div>
