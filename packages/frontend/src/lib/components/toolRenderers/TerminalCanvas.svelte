<script lang="ts">
	import type { ToolCallMessage } from '$services/sse';

	type Props = { toolCall: ToolCallMessage };
	let { toolCall }: Props = $props();

	interface SessionEntry {
		session: string;
		created?: string;
		last_activity?: string;
		windows?: string;
	}

	interface ShellResultData {
		success?: boolean;
		message?: string;
		error?: string;
		hint?: string;
		exit_code?: number;
		stdout?: string;
		stderr?: string;
		package_install_note?: string;
		session?: string;
		command?: string;
		sessions?: SessionEntry[];
		stdout_saved_to?: string;
		stdout_size_bytes?: number;
		stdout_total_lines?: number;
		stderr_saved_to?: string;
		stderr_size_bytes?: number;
		stderr_total_lines?: number;
	}

	const SHELL_ACTIONS = new Set(['exec', 'view', 'wait', 'send', 'kill']);

	let rawAction = $derived(
		typeof toolCall.args?.action === 'string' ? (toolCall.args.action as string) : 'exec'
	);
	let action = $derived(SHELL_ACTIONS.has(rawAction) ? rawAction : 'exec');

	let argSession = $derived(
		typeof toolCall.args?.session === 'string' ? (toolCall.args.session as string) : ''
	);
	let argInput = $derived(
		typeof toolCall.args?.input === 'string' ? (toolCall.args.input as string) : ''
	);
	let argTimeout = $derived(
		typeof toolCall.args?.timeout === 'number' ? (toolCall.args.timeout as number) : undefined
	);
	let command = $derived(
		typeof toolCall.args?.command === 'string' ? (toolCall.args.command as string) : ''
	);

	let resultData: ShellResultData = $derived.by(() => {
		const r = toolCall.result;
		if (r == null) return {};
		if (typeof r === 'string') return { stdout: r, exit_code: 0, success: true };
		if (typeof r !== 'object') return {};
		const obj = r as Record<string, unknown>;
		const s = (k: string) => (typeof obj[k] === 'string' ? (obj[k] as string) : undefined);
		const n = (k: string) => (typeof obj[k] === 'number' ? (obj[k] as number) : undefined);
		return {
			success: typeof obj.success === 'boolean' ? obj.success : undefined,
			message: s('message'),
			error: s('error'),
			hint: s('hint'),
			exit_code: n('exit_code'),
			stdout: s('stdout') ?? '',
			stderr: s('stderr') ?? '',
			package_install_note: s('package_install_note'),
			session: s('session'),
			command: s('command'),
			sessions: Array.isArray(obj.sessions) ? (obj.sessions as SessionEntry[]) : undefined,
			stdout_saved_to: s('stdout_saved_to'),
			stdout_size_bytes: n('stdout_size_bytes'),
			stdout_total_lines: n('stdout_total_lines'),
			stderr_saved_to: s('stderr_saved_to'),
			stderr_size_bytes: n('stderr_size_bytes'),
			stderr_total_lines: n('stderr_total_lines')
		};
	});

	let isRunning = $derived(toolCall.status === 'running' || toolCall.result == null);
	let isError = $derived(resultData.success === false);
	let exitCode = $derived(resultData.exit_code);
	let stdout = $derived(resultData.stdout ?? '');
	let stderr = $derived(resultData.stderr ?? '');
	let sessionId = $derived(resultData.session || argSession);
	let displayCommand = $derived(command || resultData.command || '');

	let copied = $state(false);

	function copyOutput(): void {
		const parts: string[] = [];
		if (stdout) parts.push(stdout);
		if (stderr) parts.push(stderr);
		if (!parts.length && resultData.message) parts.push(resultData.message);
		if (!parts.length) return;
		navigator.clipboard.writeText(parts.join('\n')).then(() => {
			copied = true;
			setTimeout(() => (copied = false), 2000);
		});
	}

	function formatBytes(bytes?: number): string {
		if (!bytes || bytes < 0) return '';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	const ANSI_STYLES: Record<string, string> = {
		'0': '',
		'1': 'font-weight: 500',
		'2': 'opacity:0.65',
		'3': 'font-style:italic',
		'4': 'text-decoration:underline',
		'22': 'font-weight:400',
		'23': 'font-style:normal',
		'24': 'text-decoration:none',
		'30': 'color:var(--ms-subtle-text)',
		'31': 'color:var(--ms-danger)',
		'32': 'color:var(--ms-green)',
		'33': 'color:var(--ms-warning)',
		'34': 'color:var(--ms-blue)',
		'35': 'color:#a65fa0',
		'36': 'color:#3a8b94',
		'37': 'color:var(--ms-dark)',
		'39': 'color:inherit',
		'90': 'color:var(--ms-subtle-text)',
		'91': 'color:var(--ms-danger)',
		'92': 'color:var(--ms-green)',
		'93': 'color:var(--ms-warning)',
		'94': 'color:var(--ms-blue)',
		'95': 'color:#a65fa0',
		'96': 'color:#3a8b94',
		'97': 'color:var(--ms-dark)'
	};

	function ansiToHtml(text: string): string {
		if (!text) return '';
		let escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
		let openSpans = 0;
		// eslint-disable-next-line no-control-regex
		escaped = escaped.replace(/\x1b\[([0-9;]*)m/g, (_m, codes: string) => {
			if (codes === '' || codes === '0') {
				if (openSpans > 0) {
					openSpans -= 1;
					return '</span>';
				}
				return '';
			}
			const styles = codes
				.split(';')
				.map((c) => ANSI_STYLES[c] || '')
				.filter(Boolean)
				.join(';');
			if (!styles) return '';
			openSpans += 1;
			return `<span style="${styles}">`;
		});
		// eslint-disable-next-line no-control-regex
		escaped = escaped.replace(/\x1b\[[0-9;?]*[A-HJKSTfimnsu]/g, '');
		while (openSpans > 0) {
			escaped += '</span>';
			openSpans -= 1;
		}
		return escaped;
	}

	const ACTION_LABELS: Record<string, string> = {
		exec: 'exec',
		view: 'sessions',
		wait: 'wait',
		send: 'send',
		kill: 'kill'
	};
</script>

<div class="h-full p-2" data-testid="terminal-canvas-wrapper">
	<div
		class="flex h-full flex-col overflow-hidden rounded-lg border border-border-subtle bg-surface-2 shadow-sm"
		data-testid="terminal-canvas"
	>
		<!-- Title bar -->
		<div
			class="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface px-3 py-2"
		>
			<div class="flex shrink-0 gap-1.5" aria-hidden="true">
				<div class="size-2.5 rounded-full bg-accent/70"></div>
				<div class="size-2.5 rounded-full bg-warning/70"></div>
				<div class="size-2.5 rounded-full bg-success/70"></div>
			</div>

			<div class="flex min-w-0 flex-1 items-center justify-center gap-2">
				<span class="font-mono text-[11px] font-medium uppercase tracking-wide text-muted">
					shell · {ACTION_LABELS[action] ?? action}
				</span>
				{#if sessionId}
					<span
						class="truncate rounded bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] text-accent"
						title="tmux session id"
						data-testid="terminal-canvas-session"
					>
						@{sessionId}
					</span>
				{/if}
			</div>

			<div class="flex shrink-0 items-center gap-2">
				{#if isRunning}
					<span
						class="flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-muted"
						data-testid="terminal-canvas-running"
					>
						<span
							class="inline-block size-1.5 animate-pulse rounded-full bg-accent"
							aria-hidden="true"
						></span>
						running
					</span>
				{:else if isError}
					<span
						class="rounded bg-accent/15 px-2 py-0.5 font-mono text-[11px] font-medium text-accent"
						data-testid="terminal-canvas-error-badge"
					>
						error
					</span>
				{:else if exitCode !== undefined}
					<span
						class="rounded px-2 py-0.5 font-mono text-[11px] font-medium {exitCode === 0
							? 'bg-success/15 text-success'
							: 'bg-accent/15 text-accent'}"
						data-testid="terminal-canvas-exit-code"
					>
						exit {exitCode}
					</span>
				{/if}

				<button
					onclick={copyOutput}
					class="rounded p-1 text-muted transition-colors hover:bg-surface-2 hover:text-accent"
					title="Copy output"
					aria-label="Copy output"
					data-testid="terminal-canvas-copy"
				>
					{#if copied}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="13"
							height="13"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="text-success"
						>
							<polyline points="20 6 9 17 4 12" />
						</svg>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="13"
							height="13"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
							<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
						</svg>
					{/if}
				</button>
			</div>
		</div>

		<!-- Content -->
		<div
			class="flex-1 overflow-auto bg-background p-4 font-mono text-[13px] leading-relaxed text-foreground"
			data-testid="terminal-canvas-body"
		>
			{#if action === 'exec' || action === 'wait'}
				{#if displayCommand}
					<div class="mb-3 flex gap-2" data-testid="terminal-canvas-command">
						<span class="shrink-0 select-none text-success">$</span>
						<span class="min-w-0 flex-1 whitespace-pre-wrap break-all text-foreground">
							{displayCommand}
						</span>
					</div>
				{/if}

				{#if resultData.package_install_note}
					<div
						class="mb-3 rounded border border-border-subtle bg-surface px-2.5 py-1.5 text-[11px] text-muted"
						data-testid="terminal-canvas-package-note"
					>
						{resultData.package_install_note}
					</div>
				{/if}

				{#if isRunning && !stdout && !stderr}
					<div class="flex items-center gap-2 text-muted">
						<span
							class="inline-block size-3 animate-spin rounded-full border-2 border-border-strong border-t-mid-blue"
							aria-hidden="true"
						></span>
						<span class="text-[12px]">Running…</span>
					</div>
				{/if}

				{#if stdout}
					<div class="whitespace-pre-wrap break-all" data-testid="terminal-canvas-stdout">
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html ansiToHtml(stdout)}
					</div>
				{/if}

				{#if resultData.stdout_saved_to}
					<div
						class="mt-2 rounded border border-border-subtle bg-surface px-2.5 py-1.5 text-[10px] text-subtle"
						data-testid="terminal-canvas-stdout-saved"
					>
						stdout truncated — full output saved to
						<span class="font-mono text-muted">{resultData.stdout_saved_to}</span>
						{#if resultData.stdout_total_lines}
							· {resultData.stdout_total_lines} lines
						{/if}
						{#if resultData.stdout_size_bytes}
							· {formatBytes(resultData.stdout_size_bytes)}
						{/if}
					</div>
				{/if}

				{#if stderr}
					<div
						class="mt-3 border-t border-accent/20 pt-3 whitespace-pre-wrap break-all text-accent"
						data-testid="terminal-canvas-stderr"
					>
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html ansiToHtml(stderr)}
					</div>
				{/if}

				{#if resultData.stderr_saved_to}
					<div
						class="mt-2 rounded border border-border-subtle bg-surface px-2.5 py-1.5 text-[10px] text-subtle"
						data-testid="terminal-canvas-stderr-saved"
					>
						stderr truncated — full output saved to
						<span class="font-mono text-muted">{resultData.stderr_saved_to}</span>
					</div>
				{/if}

				{#if !displayCommand && !stdout && !stderr && !isRunning && !isError}
					<span class="italic text-subtle">No output</span>
				{/if}
			{:else if action === 'view'}
				{#if resultData.sessions && resultData.sessions.length > 0}
					<div class="space-y-1.5" data-testid="terminal-canvas-sessions">
						<div class="px-2 pb-1 font-mono text-[10px] uppercase tracking-wide text-subtle">
							{resultData.sessions.length} session{resultData.sessions.length === 1 ? '' : 's'}
						</div>
						{#each resultData.sessions as s (s.session)}
							<div
								class="flex items-center justify-between gap-3 rounded border border-border-subtle bg-surface-2 px-3 py-2"
							>
								<div class="flex items-center gap-2 min-w-0">
									<span
										class="inline-block size-1.5 shrink-0 rounded-full bg-success"
										aria-hidden="true"
									></span>
									<span class="truncate font-mono text-[12px] text-foreground">{s.session}</span>
								</div>
								<div class="flex items-center gap-3 text-[10px] text-subtle">
									{#if s.windows}<span>{s.windows} win</span>{/if}
								</div>
							</div>
						{/each}
					</div>
				{:else if !isRunning}
					<span class="italic text-subtle">
						{resultData.message ?? 'No active sessions'}
					</span>
				{/if}
			{:else if action === 'send'}
				<div class="space-y-2" data-testid="terminal-canvas-send">
					<div class="text-[11px] uppercase tracking-wide text-subtle">stdin →</div>
					<div
						class="whitespace-pre-wrap rounded border border-border-subtle bg-surface px-3 py-2 text-foreground"
					>
						{argInput || '(empty)'}
					</div>
					{#if resultData.message && !isError}
						<div class="text-[11px] text-success">{resultData.message}</div>
					{/if}
				</div>
			{:else if action === 'kill'}
				<div class="text-[12px] text-muted" data-testid="terminal-canvas-kill">
					{#if isError}
						failed to terminate session
					{:else if resultData.message}
						{resultData.message}
					{:else if isRunning}
						terminating session…
					{/if}
				</div>
			{/if}

			{#if isError}
				<div
					class="mt-3 rounded border border-accent/30 bg-accent/5 px-3 py-2"
					data-testid="terminal-canvas-error"
				>
					<div class="font-mono text-[10px] font-medium uppercase tracking-wide text-accent">
						{resultData.error ?? 'error'}
					</div>
					{#if resultData.message}
						<div class="mt-1 text-[12px] text-foreground">{resultData.message}</div>
					{/if}
					{#if resultData.hint}
						<div class="mt-1 text-[11px] italic text-muted">hint: {resultData.hint}</div>
					{/if}
				</div>
			{/if}

			{#if argTimeout !== undefined && (action === 'exec' || action === 'wait')}
				<div class="mt-3 text-[10px] text-subtle" data-testid="terminal-canvas-timeout">
					timeout: {argTimeout}s
				</div>
			{/if}
		</div>
	</div>
</div>
