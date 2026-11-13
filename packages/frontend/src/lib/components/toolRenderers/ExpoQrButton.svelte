<script lang="ts">
	import QRCode from 'qrcode';
	import QrCode from '@lucide/svelte/icons/qr-code';
	import Dialog from '$lib/components/ui/Dialog.svelte';

	type Props = {
		publicUrl: string;
	};

	let { publicUrl }: Props = $props();

	let open = $state(false);
	let qrDataUrl = $state<string | null>(null);
	let qrError = $state<string | null>(null);
	let showLink = $state(false);

	const expoUrl = $derived(`exp://${publicUrl.replace(/^https?:\/\//, '')}`);

	$effect(() => {
		const target = expoUrl;
		qrError = null;
		QRCode.toDataURL(target, {
			width: 256,
			margin: 2,
			color: { dark: '#141413', light: '#faf9f5' }
		})
			.then((url) => {
				qrDataUrl = url;
			})
			.catch((err: unknown) => {
				qrError = err instanceof Error ? err.message : String(err);
				qrDataUrl = null;
			});
	});

	function openDialog(): void {
		open = true;
	}

	function closeDialog(): void {
		open = false;
		showLink = false;
	}
</script>

<button
	type="button"
	onclick={openDialog}
	title="Open on your phone"
	aria-label="Open on your phone"
	class="flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-muted transition-colors hover:bg-surface hover:text-foreground"
	data-testid="expo-qr-button"
>
	<QrCode size={14} strokeWidth={2} aria-hidden="true" />
</button>

<Dialog bind:open onclose={closeDialog} aria-label="Open on your phone">
	<div class="flex flex-col gap-4 p-6">
		<div>
			<h2 class="font-sans text-lg font-medium text-foreground">Open on your phone</h2>
			<p class="mt-2 font-sans text-sm leading-relaxed text-muted">
				Scan this code with your phone's camera to open the app. Make sure you have the
				<strong class="text-foreground">Expo Go</strong> app installed — it's free in the App Store and
				Google Play.
			</p>
		</div>

		<div
			class="flex items-center justify-center rounded-lg border border-border-subtle bg-background p-4"
		>
			{#if qrDataUrl}
				<img src={qrDataUrl} alt="Scan to open on your phone" class="h-64 w-64" />
			{:else if qrError}
				<div
					class="flex h-64 w-64 items-center justify-center text-center font-sans text-[12px] text-accent"
				>
					Couldn't make the QR code. Please try again.
				</div>
			{:else}
				<div class="flex h-64 w-64 items-center justify-center font-sans text-[12px] text-muted">
					Getting the code ready…
				</div>
			{/if}
		</div>

		<div class="flex flex-col items-start gap-2">
			<button
				type="button"
				onclick={() => (showLink = !showLink)}
				class="font-sans text-xs text-muted underline underline-offset-2 hover:text-foreground"
			>
				{showLink ? 'Hide link' : 'Show link (for Expo Go paste)'}
			</button>
			{#if showLink}
				<div
					class="mt-1 w-full select-all break-all rounded border border-border-subtle bg-surface px-2 py-1.5 font-mono text-[11px] text-muted"
				>
					{expoUrl}
				</div>
			{/if}
		</div>

		<div class="flex justify-end">
			<button
				type="button"
				onclick={closeDialog}
				class="rounded-lg border border-border-strong px-4 py-2 font-sans text-sm text-foreground transition-colors hover:bg-foreground hover:text-background"
			>
				Done
			</button>
		</div>
	</div>
</Dialog>
