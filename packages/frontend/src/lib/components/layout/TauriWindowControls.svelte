<script lang="ts">
	import { isMaximized, windowActions, isMacOS } from '$stores/tauri';

	let maximized = $state(false);
	let mac = $state(false);
	const unsubMax = isMaximized.subscribe((v) => (maximized = v));
	const unsubMac = isMacOS.subscribe((v) => (mac = v));

	import { onDestroy } from 'svelte';
	onDestroy(() => {
		unsubMax();
		unsubMac();
	});
</script>

{#if !mac}
	<div class="flex items-center h-full">
		<button onclick={() => windowActions.minimize()} class="wc-btn" aria-label="Minimize">
			<svg width="10" height="10" viewBox="0 0 10 10">
				<rect x="1" y="4.5" width="8" height="1" fill="currentColor" rx="0.5" />
			</svg>
		</button>
		<button
			onclick={() => windowActions.toggleMaximize()}
			class="wc-btn"
			aria-label={maximized ? 'Restore' : 'Maximize'}
		>
			{#if maximized}
				<svg width="10" height="10" viewBox="0 0 10 10">
					<path d="M3 1h6v6H7V3H3V1Z" fill="currentColor" />
					<rect
						x="1"
						y="3"
						width="6"
						height="6"
						fill="none"
						stroke="currentColor"
						stroke-width="1"
					/>
				</svg>
			{:else}
				<svg width="10" height="10" viewBox="0 0 10 10">
					<rect
						x="1"
						y="1"
						width="8"
						height="8"
						fill="none"
						stroke="currentColor"
						stroke-width="1"
						rx="0.5"
					/>
				</svg>
			{/if}
		</button>
		<button onclick={() => windowActions.close()} class="wc-btn wc-close" aria-label="Close">
			<svg width="10" height="10" viewBox="0 0 10 10">
				<path
					d="M1.5 1.5L8.5 8.5M8.5 1.5L1.5 8.5"
					stroke="currentColor"
					stroke-width="1.2"
					stroke-linecap="round"
				/>
			</svg>
		</button>
	</div>
{/if}

<style>
	.wc-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 46px;
		height: var(--header-height, 48px);
		color: var(--ms-subtle-text);
		background: transparent;
		border: none;
		cursor: pointer;
		transition:
			background 120ms,
			color 120ms;
	}
	.wc-btn:hover {
		background: var(--ms-elevated);
		color: var(--ms-dark);
	}
	.wc-close:hover {
		background: #e81123;
		color: #ffffff;
	}
</style>
