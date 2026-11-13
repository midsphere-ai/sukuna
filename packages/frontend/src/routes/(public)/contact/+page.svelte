<script lang="ts">
	let name = $state('');
	let email = $state('');
	let subject = $state('');
	let message = $state('');
	let sending = $state(false);
	let submitted = $state(false);
	let errorMsg = $state('');
	let touched: Record<string, boolean> = $state({});

	let nameError = $derived(touched.name && !name.trim() ? 'Name is required' : '');
	let emailError = $derived.by(() => {
		if (!touched.email) return '';
		if (!email.trim()) return 'Email is required';
		if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return 'Enter a valid email';
		return '';
	});
	let subjectError = $derived(touched.subject && !subject.trim() ? 'Subject is required' : '');
	let messageError = $derived(touched.message && !message.trim() ? 'Message is required' : '');

	let formValid = $derived(
		name.trim() !== '' &&
			/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) &&
			subject.trim() !== '' &&
			message.trim() !== ''
	);

	function markTouched(field: string) {
		touched[field] = true;
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		touched = { name: true, email: true, subject: true, message: true };
		if (!formValid) return;

		sending = true;
		errorMsg = '';
		try {
			const res = await fetch('/api/contact', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					name: name.trim(),
					email: email.trim(),
					subject: subject.trim(),
					message: message.trim()
				})
			});
			if (!res.ok) throw new Error('Failed to send');
			submitted = true;
		} catch {
			errorMsg = 'Something went wrong. Please try again or email us directly.';
		} finally {
			sending = false;
		}
	}

	function resetForm() {
		name = '';
		email = '';
		subject = '';
		message = '';
		touched = {};
		submitted = false;
		errorMsg = '';
	}
</script>

<svelte:head>
	<title>Contact - Jatayu AI</title>
	<meta
		name="description"
		content="Get in touch with the Jatayu AI team. Send us a message or reach out via email."
	/>
	<meta property="og:title" content="Contact - Jatayu AI" />
	<meta
		property="og:description"
		content="Get in touch with the Jatayu AI team. Send us a message or reach out via email."
	/>
	<meta property="og:type" content="website" />
	<meta name="twitter:card" content="summary" />
	<meta name="twitter:title" content="Contact - Jatayu AI" />
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
	<!-- Header -->
	<div class="mb-12">
		<h1 class="font-junicode text-3xl tracking-tight text-foreground sm:text-4xl">Contact Us</h1>
		<p class="mt-3 text-base leading-relaxed text-subtle">
			Have a question, feedback, or need help? We'd love to hear from you.
		</p>
	</div>

	<div class="space-y-6">
		<!-- Contact form -->
		<div class="rounded-xl border border-border-subtle bg-surface p-6">
			{#if submitted}
				<!-- Success state -->
				<div class="py-6 text-center">
					<div
						class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-positive/10"
					>
						<svg
							class="h-6 w-6 text-accent-positive"
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
						>
							<polyline points="20 6 9 17 4 12" />
						</svg>
					</div>
					<h2 class="font-junicode text-lg text-foreground">Message sent</h2>
					<p class="mt-2 text-sm leading-relaxed text-subtle">
						Thanks for reaching out. We'll get back to you within 24 hours.
					</p>
					<button
						onclick={resetForm}
						class="mt-5 rounded-lg bg-surface-2 px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-2"
					>
						Send another message
					</button>
				</div>
			{:else}
				<div class="mb-5 flex items-center gap-2">
					<svg
						class="h-5 w-5 text-accent"
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<path
							d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"
						/>
					</svg>
					<h2 class="font-junicode text-lg text-foreground">Send a message</h2>
				</div>

				{#if errorMsg}
					<div class="mb-5 rounded-lg border border-accent/20 bg-accent/5 px-4 py-3">
						<p class="text-sm text-accent">{errorMsg}</p>
					</div>
				{/if}

				<form onsubmit={handleSubmit} class="space-y-4" novalidate>
					<div class="grid gap-4 sm:grid-cols-2">
						<!-- Name -->
						<div>
							<label for="contact-name" class="mb-1.5 block text-sm font-medium text-foreground"
								>Name</label
							>
							<input
								id="contact-name"
								type="text"
								bind:value={name}
								onblur={() => markTouched('name')}
								placeholder="Your name"
								class="w-full rounded-lg border px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)] {nameError
									? 'border-accent/40 bg-accent/[0.02]'
									: 'border-border-strong bg-background'}"
							/>
							{#if nameError}
								<p class="mt-1 text-xs text-accent">{nameError}</p>
							{/if}
						</div>

						<!-- Email -->
						<div>
							<label for="contact-email" class="mb-1.5 block text-sm font-medium text-foreground"
								>Email</label
							>
							<input
								id="contact-email"
								type="email"
								bind:value={email}
								onblur={() => markTouched('email')}
								placeholder="you@example.com"
								class="w-full rounded-lg border px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)] {emailError
									? 'border-accent/40 bg-accent/[0.02]'
									: 'border-border-strong bg-background'}"
							/>
							{#if emailError}
								<p class="mt-1 text-xs text-accent">{emailError}</p>
							{/if}
						</div>
					</div>

					<!-- Subject -->
					<div>
						<label for="contact-subject" class="mb-1.5 block text-sm font-medium text-foreground"
							>Subject</label
						>
						<input
							id="contact-subject"
							type="text"
							bind:value={subject}
							onblur={() => markTouched('subject')}
							placeholder="What's this about?"
							class="w-full rounded-lg border px-3.5 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)] {subjectError
								? 'border-accent/40 bg-accent/[0.02]'
								: 'border-border-strong bg-background'}"
						/>
						{#if subjectError}
							<p class="mt-1 text-xs text-accent">{subjectError}</p>
						{/if}
					</div>

					<!-- Message -->
					<div>
						<label for="contact-message" class="mb-1.5 block text-sm font-medium text-foreground"
							>Message</label
						>
						<textarea
							id="contact-message"
							bind:value={message}
							onblur={() => markTouched('message')}
							placeholder="Tell us more..."
							rows="5"
							class="w-full resize-none rounded-lg border px-3.5 py-2.5 text-sm leading-relaxed text-foreground outline-none transition-colors placeholder:text-muted focus:border-border-strong focus:ring-1 focus:ring-[rgba(59,130,246,0.3)] {messageError
								? 'border-accent/40 bg-accent/[0.02]'
								: 'border-border-strong bg-background'}"
						></textarea>
						{#if messageError}
							<p class="mt-1 text-xs text-accent">{messageError}</p>
						{/if}
					</div>

					<div class="flex items-center justify-between pt-1">
						<p class="text-xs text-muted">We typically respond within 24 hours.</p>
						<button
							type="submit"
							disabled={sending}
							class="inline-flex items-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
						>
							{#if sending}
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
										d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
									></path>
								</svg>
								Sending...
							{:else}
								Send message
							{/if}
						</button>
					</div>
				</form>
			{/if}
		</div>

		<!-- Alternative contact methods -->
		<div class="grid gap-4 sm:grid-cols-2">
			<!-- Support tickets -->
			<div class="rounded-xl border border-border-subtle bg-surface p-5">
				<div class="mb-3 flex items-center gap-2">
					<svg
						class="h-5 w-5 text-accent"
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
					</svg>
					<h2 class="text-sm font-medium text-foreground">Support Tickets</h2>
				</div>
				<p class="mb-4 text-sm leading-relaxed text-subtle">
					Sign in to create and track support tickets.
				</p>
				<!-- eslint-disable svelte/no-navigation-without-resolve -->
				<a
					href="/login"
					class="inline-flex items-center gap-1.5 text-sm font-medium text-accent transition-colors hover:text-accent/80"
				>
					Sign in
					<svg
						class="h-3.5 w-3.5"
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
					>
						<path d="M9 18l6-6-6-6" />
					</svg>
				</a>
				<!-- eslint-enable svelte/no-navigation-without-resolve -->
			</div>

			<!-- Email -->
			<div class="rounded-xl border border-border-subtle bg-surface p-5">
				<div class="mb-3 flex items-center gap-2">
					<svg
						class="h-5 w-5 text-success"
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
						<polyline points="22,6 12,13 2,6" />
					</svg>
					<h2 class="text-sm font-medium text-foreground">Email Us</h2>
				</div>
				<p class="mb-3 text-sm leading-relaxed text-subtle">
					For general inquiries, reach out directly.
				</p>
				<a
					href="mailto:support@midsphere.com"
					class="text-sm font-medium text-accent transition-colors hover:text-accent/80"
				>
					support@midsphere.com
				</a>
			</div>
		</div>
	</div>
</div>
