<svelte:head>
	<title>Offline — Jatayu AI</title>
</svelte:head>

<div class="flex min-h-screen flex-col items-center justify-center bg-background px-4 sm:px-6">
	<div class="w-full max-w-md text-center">
		<!-- Wi-fi off illustration -->
		<div class="mb-10 flex justify-center">
			<div
				class="flex h-28 w-28 items-center justify-center rounded-3xl bg-accent-warning/[0.08] text-accent-warning/60"
			>
				<svg
					width="52"
					height="52"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<line x1="1" y1="1" x2="23" y2="23" />
					<path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
					<path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
					<path d="M10.71 5.05A16 16 0 0 1 22.56 9" />
					<path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
					<path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
					<line x1="12" y1="20" x2="12.01" y2="20" />
				</svg>
			</div>
		</div>

		<!-- Title & description -->
		<h1 class="font-junicode text-2xl tracking-tight text-foreground sm:text-3xl">
			You're offline
		</h1>
		<p class="mx-auto mt-3 max-w-sm text-base leading-relaxed text-subtle">
			It looks like you've lost your internet connection. Check your network and try again.
		</p>

		<!-- Actions -->
		<div class="mt-10 flex flex-wrap items-center justify-center gap-3">
			<button
				onclick={() => window.location.reload()}
				class="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-foreground px-6 py-2.5 text-sm font-medium text-background transition-all duration-200"
			>
				<svg
					class="h-4 w-4"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<polyline points="23 4 23 10 17 10" />
					<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
				</svg>
				Retry
			</button>
		</div>

		<!-- Helpful tips -->
		<div class="mx-auto mt-12 max-w-xs rounded-xl border border-border-subtle bg-surface p-5">
			<p class="mb-3 text-xs font-medium uppercase tracking-wider text-muted">Troubleshooting</p>
			<ul class="space-y-2 text-left text-sm text-subtle">
				<li class="flex items-start gap-2">
					<svg
						class="mt-0.5 h-4 w-4 shrink-0 text-muted"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<polyline points="9 11 12 14 22 4" />
						<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
					</svg>
					Check your Wi-Fi or ethernet connection
				</li>
				<li class="flex items-start gap-2">
					<svg
						class="mt-0.5 h-4 w-4 shrink-0 text-muted"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<polyline points="9 11 12 14 22 4" />
						<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
					</svg>
					Try restarting your router
				</li>
				<li class="flex items-start gap-2">
					<svg
						class="mt-0.5 h-4 w-4 shrink-0 text-muted"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<polyline points="9 11 12 14 22 4" />
						<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
					</svg>
					Disable VPN or proxy if enabled
				</li>
			</ul>
		</div>

		<!-- Footer -->
		<p class="mt-16 text-xs text-muted">Jatayu AI</p>
	</div>
</div>
