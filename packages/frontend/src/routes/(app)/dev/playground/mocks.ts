/**
 * Static fixtures for the chat UI playground route.
 *
 * Every fixture is typed against the real interfaces exported from
 * `$services/sse` / `stream-types.ts`.
 *
 * **Tool names are the real exo-registered sandbox tool names** — one per
 * `@tool(name=...)` in `packages/sandbox/tools/`. Using the real names
 * means the rendered labels, canvas routing, and tool icons match what a
 * user sees in a live run.
 */

import type {
	Message,
	UserMessage,
	TextMessage,
	ToolCallMessage,
	ErrorMessage,
	HitlMessage,
	ReasoningMessage,
	PlanState
} from '$services/sse';

// ─── Message fixtures (for individual views) ──────────────────────────────

export const userMessageShort: UserMessage = {
	type: 'user',
	text: 'Ship an admin page for feature flags with a toggle per environment.'
};

export const userMessageWithFiles: UserMessage = {
	type: 'user',
	text: "Here's the mockup Sarah sent and a voice note from standup about the icon.",
	files: ['designs/flag-icon-mockup.png', 'notes/standup-voice.mp3']
};

export const userMessageLongMarkdown: UserMessage = {
	type: 'user',
	text: 'Requirements:\n\n1. **List** all flags with current state per environment\n2. **Toggle** each env/flag combination with optimistic UI\n3. **Admin-only** — gate behind the existing admin guard\n\nUse the existing `flags_featureflag` table. No new migrations.'
};

export const agentMessageShort: TextMessage = {
	type: 'assistant',
	text: "On it. I'll explore the existing flags code first, then scaffold the admin route.",
	isStreaming: false
};

export const agentMessageMarkdown: TextMessage = {
	type: 'assistant',
	isStreaming: false,
	text: '### What I\'m building\n\nThe table has 5 flags today. The admin page will:\n\n1. **List** all flags with their current state per environment\n2. **Toggle** individual env/flag combinations with an optimistic update\n3. **Surface rollouts** — a small badge showing which envs the flag is live in\n\nI\'ll put it at `/admin/flags` behind the existing admin guard.\n\n```python\n@router.post("/flags/{flag_id}/toggle")\ndef toggle_flag_environment(request, flag_id: int, payload: ToggleFlagBody):\n    flag = get_object_or_404(FeatureFlag, pk=flag_id)\n    envs = set(flag.environments)\n    if payload.enabled:\n        envs.add(payload.environment)\n    else:\n        envs.discard(payload.environment)\n    flag.environments = sorted(envs)\n    flag.save(update_fields=["environments"])\n    return {"ok": True, "environments": flag.environments}\n```\n\n| Env | Flags live |\n|---|---|\n| prod | 2 |\n| staging | 3 |\n| dev | 3 |\n\n> Rolling out `mfa_required` last — it affects every authenticated request.'
};

export const agentMessageStreaming: TextMessage = {
	type: 'assistant',
	text: 'While you decide — one thing I want to flag about the rollout path: the `mfa_required` flag currently',
	isStreaming: true
};

export const agentMessageMuted: TextMessage = {
	type: 'assistant',
	text: 'Sub-agent reporting back — all green.',
	isStreaming: false
};

export const agentMessageStartedBy: TextMessage = {
	type: 'assistant',
	text: 'Verification passed on all 11 test cases.',
	isStreaming: false,
	started_by_name: 'Verifier'
};

export const errorMessageNetwork: ErrorMessage = {
	type: 'error',
	message: 'Connection to sandbox briefly dropped — reconnecting…'
};

export const errorMessageAuth: ErrorMessage = {
	type: 'error',
	message: 'Your session has expired. Please sign in again to continue.'
};

export const hitlPending: HitlMessage = {
	type: 'hitl',
	requestId: 'req-pending',
	prompt: 'Ship it?',
	choices: ['Merge to main', 'Open PR against feat/flags', 'Let me review first']
};

export const hitlFreeText: HitlMessage = {
	type: 'hitl',
	requestId: 'req-free-text',
	prompt: 'What should the commit message be?'
};

export const hitlAnswered: HitlMessage = {
	type: 'hitl',
	requestId: 'req-answered',
	prompt:
		"I'm about to run the dev server and verify the toggle flow end-to-end. That'll take about 30 seconds. OK to proceed?",
	choices: ['Proceed', 'Skip', 'Cancel'],
	response: 'Proceed'
};

export const reasoningShort: ReasoningMessage = {
	type: 'reasoning',
	text: 'Plan: read the existing flags schema, sketch the UI, then scaffold the admin page.'
};

export const reasoningLong: ReasoningMessage = {
	type: 'reasoning',
	text: "Starting with a grep for existing flag code, then reading the model, then the API surface. Once I understand the shape, I'll sketch the page and wire the toggle action. Rollout order matters — `mfa_required` goes last because it affects every authenticated request."
};

// ─── Generic tool call states (for the ToolCallMessage row fixture) ───────

export const toolCallRunning: ToolCallMessage = {
	type: 'tool_call',
	callId: 'generic-running',
	toolName: 'shell',
	args: { action: 'exec', command: 'pytest apps/flags -x -q' },
	status: 'running'
};

export const toolCallSuccess: ToolCallMessage = {
	type: 'tool_call',
	callId: 'generic-success',
	toolName: 'file',
	args: { action: 'read', path: 'apps/flags/models.py' },
	status: 'success',
	durationMs: 18
};

export const toolCallError: ToolCallMessage = {
	type: 'tool_call',
	callId: 'generic-error',
	toolName: 'shell',
	args: { action: 'exec', command: 'pytest apps/billing/test_plan_quota.py' },
	status: 'error',
	durationMs: 2831,
	error: 'Exited with code 1',
	result: {
		success: true,
		message: 'Command executed',
		exit_code: 1,
		stdout: 'collected 14 items\n\ntests/test_billing.py::test_plan_quota FAILED',
		stderr:
			'E   AssertionError: expected 10, got 8\nE   +  where 8 = UserBillingState.quota\n\n=========== 1 failed, 13 passed in 2.81s ==========='
	}
};

// ─── Canvas fixtures — one per reachable canvas, real exo tool names ─────

export const tcTerminalShell: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-terminal-shell',
	toolName: 'shell',
	args: { action: 'exec', command: 'pytest apps/flags -x -q', session: 'tests' },
	status: 'success',
	durationMs: 1840,
	result: {
		success: true,
		message: 'Command executed',
		exit_code: 0,
		stdout:
			'\u001b[32m============================= test session starts ==============================\u001b[0m\nplatform linux -- Python 3.12.0, pytest-8.2.0\nrootdir: /workspace\ncollected 11 items\n\ntests/test_flags_api.py \u001b[32m...........\u001b[0m                                     [100%]\n\n\u001b[32m============================== 11 passed in 1.81s ===============================\u001b[0m',
		stderr: ''
	}
};

export const tcDiff: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-diff',
	toolName: 'file',
	args: {
		action: 'edit',
		path: 'apps/flags/api.py',
		edits: [
			{
				old_text: '@router.get("/flags")',
				new_text:
					'@router.post("/flags/{flag_id}/toggle")\ndef toggle_flag_environment(request, flag_id: int, payload: ToggleFlagBody):\n    flag = get_object_or_404(FeatureFlag, pk=flag_id)\n    envs = set(flag.environments)\n    if payload.enabled:\n        envs.add(payload.environment)\n    else:\n        envs.discard(payload.environment)\n    flag.environments = sorted(envs)\n    flag.save(update_fields=["environments"])\n    return {"ok": True, "environments": flag.environments}\n\n\n@router.get("/flags")'
			}
		]
	},
	status: 'success',
	durationMs: 96,
	result: {
		success: true,
		message: 'Applied 1 edit',
		file_path: 'apps/flags/api.py',
		dry_run: false,
		match_results: [{ edit_index: 0, match_type: 'exact', details: 'Matched at line 24' }],
		diff: '@@ -20,6 +20,18 @@\n     return [{"key": f.key, "is_enabled": f.is_enabled, "environments": f.environments} for f in flags]\n \n \n+@router.post("/flags/{flag_id}/toggle")\n+def toggle_flag_environment(request, flag_id: int, payload: ToggleFlagBody):\n+    flag = get_object_or_404(FeatureFlag, pk=flag_id)\n+    envs = set(flag.environments)\n+    if payload.enabled:\n+        envs.add(payload.environment)\n+    else:\n+        envs.discard(payload.environment)\n+    flag.environments = sorted(envs)\n+    flag.save(update_fields=["environments"])\n+    return {"ok": True, "environments": flag.environments}\n+\n+\n @router.get("/flags")\n def list_feature_flags(request):\n     flags = FeatureFlag.objects.all()'
	}
};

// file action=read returns the raw string content directly (per ops.py::_read_file)
export const tcCodeViewer: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-code-viewer',
	toolName: 'file',
	args: { action: 'read', path: 'apps/flags/models.py' },
	status: 'success',
	durationMs: 18,
	result:
		'from django.db import models\n\n\nclass FeatureFlag(models.Model):\n    key = models.CharField(max_length=64, unique=True)\n    description = models.TextField(blank=True)\n    is_enabled = models.BooleanField(default=False)\n    environments = models.JSONField(default=list)\n    created_at = models.DateTimeField(auto_now_add=True)\n\n    def __str__(self):\n        return self.key\n'
};

// file action=view returns a list of entries
export const tcFileTree: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-file-tree',
	toolName: 'file',
	args: { action: 'view', path: 'apps/flags' },
	status: 'success',
	durationMs: 14,
	result: {
		success: true,
		message: 'Listed apps/flags',
		path: 'apps/flags',
		files: [
			{ name: 'migrations', type: 'directory' },
			{ name: 'tests', type: 'directory' },
			{ name: '__init__.py', type: 'file', size: 0 },
			{ name: 'admin.py', type: 'file', size: 412 },
			{ name: 'api.py', type: 'file', size: 2184 },
			{ name: 'models.py', type: 'file', size: 378 },
			{ name: 'views.py', type: 'file', size: 1024 }
		],
		total: 7
	}
};

export const tcFileStatusSave: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-file-status',
	toolName: 'file',
	args: {
		action: 'write',
		path: 'packages/frontend/src/routes/(app)/admin/flags/+page.svelte'
	},
	status: 'success',
	durationMs: 22,
	result: {
		success: true,
		message: 'Wrote 142 lines',
		file_path: 'packages/frontend/src/routes/(app)/admin/flags/+page.svelte',
		size: 4212,
		bytes_written: 4212
	}
};

export const tcSearchWeb: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-search',
	toolName: 'search',
	args: { type: 'info', queries: ['svelte 5 admin toggle UI pattern'] },
	status: 'success',
	durationMs: 380,
	result: {
		success: true,
		message: 'Found 3 results',
		query: 'svelte 5 admin toggle UI pattern',
		count: 3,
		results: [
			{
				title: 'Toggles — Melt UI',
				url: 'https://melt-ui.com/docs/builders/toggle',
				snippet: 'Accessible toggle switch primitives for Svelte with keyboard support.',
				display_link: 'melt-ui.com'
			},
			{
				title: 'Svelte 5: Building admin dashboards',
				url: 'https://joyofcode.xyz/svelte-5-admin',
				snippet:
					'A practical guide to building admin UIs with runes, optimistic updates, and server actions.',
				display_link: 'joyofcode.xyz'
			},
			{
				title: 'Feature flag UX patterns',
				url: 'https://www.growthbook.io/blog/feature-flag-ux',
				snippet:
					'Common patterns for listing, grouping, and toggling feature flags in admin panels.',
				display_link: 'growthbook.io'
			}
		]
	}
};

export const tcSearchImages: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-search-images',
	toolName: 'search',
	args: { type: 'image', queries: ['minimalist toggle switch icon'] },
	status: 'success',
	durationMs: 520,
	result: {
		success: true,
		message: 'Found 9 images',
		query: 'minimalist toggle switch icon',
		count: 9,
		results: [
			{
				title: 'Flat toggle switch',
				image_path: 'https://placehold.co/400x280/c96442/faf9f5?text=toggle+1',
				url: 'https://example.com/a',
				display_link: 'example.com'
			},
			{
				title: 'iOS-style switch',
				image_path: 'https://placehold.co/300x400/6e8365/faf9f5?text=toggle+2',
				url: 'https://example.com/b',
				display_link: 'example.com'
			},
			{
				title: 'Rounded toggle — active',
				image_path: 'https://placehold.co/400x320/3898ec/faf9f5?text=toggle+3',
				url: 'https://example.com/c',
				display_link: 'example.com'
			},
			{
				title: 'Pill toggle',
				image_path: 'https://placehold.co/420x250/d97757/faf9f5?text=toggle+4',
				url: 'https://example.com/d',
				display_link: 'example.com'
			},
			{
				title: 'Coral toggle glow',
				image_path: 'https://placehold.co/320x420/c96442/faf9f5?text=toggle+5',
				url: 'https://example.com/e',
				display_link: 'example.com'
			},
			{
				title: 'Stone toggle',
				image_path: 'https://placehold.co/360x360/87867f/faf9f5?text=toggle+6',
				url: 'https://example.com/f',
				display_link: 'example.com'
			},
			{
				title: 'Warm toggle',
				image_path: 'https://placehold.co/400x240/e8e6dc/141413?text=toggle+7',
				url: 'https://example.com/g',
				display_link: 'example.com'
			},
			{
				title: 'Flat brand toggle',
				image_path: 'https://placehold.co/280x420/c96442/faf9f5?text=toggle+8',
				url: 'https://example.com/h',
				display_link: 'example.com'
			},
			{
				title: 'Shadow toggle',
				image_path: 'https://placehold.co/380x300/141413/faf9f5?text=toggle+9',
				url: 'https://example.com/i',
				display_link: 'example.com'
			}
		]
	}
};

export const tcBrowser: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-browser',
	toolName: 'browser',
	args: {
		url: 'http://localhost:5173/admin/flags',
		intent: 'transactional',
		focus: 'Toggle mfa_required in dev and verify the row updates'
	},
	status: 'success',
	durationMs: 12400,
	result: {
		success: true,
		message: 'Page loaded and interaction complete',
		url: 'http://localhost:5173/admin/flags',
		has_forms: true,
		output:
			'Title: Admin — Feature flags\nURL: http://localhost:5173/admin/flags\nClean screenshot path: /tmp/browser-screenshot-a1b2.png\n\n# Feature flags (5)\n\n| Key | prod | staging | dev |\n| --- | --- | --- | --- |\n| credit_metering_v2 | ✓ | ✓ | — |\n| delegate_groups | ✓ | ✓ | ✓ |\n| enterprise_compliance | — | — | ✓ |\n| **mfa_required** | — | — | **✓ (just now)** |\n| new_chat_shell | — | ✓ | ✓ |\n',
		screenshot_path: 'https://placehold.co/1200x700/faf9f5/141413?text=admin+flags+page',
		links: [
			{ url: 'http://localhost:5173/admin/flags', text: 'Flags' },
			{ url: 'http://localhost:5173/admin/users', text: 'Users' },
			{ url: 'http://localhost:5173/admin/billing', text: 'Billing' },
			{ url: 'http://localhost:5173/admin/audit', text: 'Audit log' }
		]
	}
};

export const tcDatabase: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-database',
	toolName: 'web_db',
	args: {
		action: 'sql',
		query: 'SELECT key, is_enabled, environments FROM flags_featureflag ORDER BY key'
	},
	status: 'success',
	durationMs: 41,
	result: {
		success: true,
		message: 'Query returned 5 rows',
		columns: ['key', 'is_enabled', 'environments'],
		rows: [
			{ key: 'credit_metering_v2', is_enabled: true, environments: '["prod","staging"]' },
			{ key: 'delegate_groups', is_enabled: true, environments: '["prod","staging","dev"]' },
			{ key: 'enterprise_compliance', is_enabled: false, environments: '["dev"]' },
			{ key: 'mfa_required', is_enabled: true, environments: '["dev"]' },
			{ key: 'new_chat_shell', is_enabled: true, environments: '["dev","staging"]' }
		],
		count: 5
	}
};

export const tcMedia: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-media',
	toolName: 'generate',
	args: {
		action: 'create_image',
		prompt: 'Minimalist rounded toggle switch icon, coral active state, soft glow, flat style',
		output_path: 'assets/flag-toggle.png'
	},
	status: 'success',
	durationMs: 7600,
	result: {
		success: true,
		message: 'Generated 1 image',
		file_path: 'https://placehold.co/640x640/c96442/faf9f5?text=flag+toggle',
		width: 1024,
		height: 1024,
		aspect_ratio: '1:1'
	}
};

export const tcAudio: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-audio',
	toolName: 'perception',
	args: { action: 'transcribe', source: 'notes/standup-voice.mp3' },
	status: 'success',
	durationMs: 3100,
	result: {
		success: true,
		message: 'Transcribed audio',
		transcription:
			"OK so for the flags page icon — think a simple toggle switch, rounded, two states, with a subtle glow when it's on. Coral for on, neutral for off. Keep it minimal — no gradients, no shadows beyond a soft 6 pixel blur. We want it to look at home next to the rest of the admin icons.",
		language: 'en',
		duration: 24.3
	}
};

export const tcVision: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-vision',
	toolName: 'perception',
	args: {
		action: 'analyze',
		source: 'https://placehold.co/640x400/c96442/faf9f5?text=mockup',
		question: 'What visual style and palette does this icon use?'
	},
	status: 'success',
	durationMs: 1480,
	result: {
		success: true,
		message: 'Analysis complete',
		result:
			'**Style**\n\nMinimalist rounded toggle with a small circular knob. The active state uses a warm coral (#c96442), while the inactive state falls back to a muted warm grey (#e8e6dc). A 6-pixel coral-tinted blur provides a subtle glow on the active state.\n\n**Palette**\n\n- **Active**: `#c96442` (terracotta)\n- **Inactive**: `#e8e6dc` (warm tan)\n- **Knob**: `#faf9f5` (ivory)\n\n**Treatment**\n\nFlat with subtle depth — no gradients, no hard shadows, the glow is the only ornamentation. Corner radius appears to be half the height (pill shape). The knob has a 1px inner border in `#87867f` for definition against the ivory.',
		frames_processed: 1
	}
};

export const tcDevServer: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-dev-server',
	toolName: 'web_server',
	args: { action: 'start', port: 5173 },
	status: 'success',
	durationMs: 2600,
	result: {
		success: true,
		message: 'Dev server started',
		url: 'http://localhost:5173',
		port: 5173,
		status: 'running'
	}
};

export const tcDownload: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-download',
	toolName: 'file',
	args: {
		action: 'download',
		path: '/tmp/flags-export.csv',
		url: 'https://flags-admin.sandbox.midsphere.dev/api/flags/export.csv'
	},
	status: 'success',
	durationMs: 640,
	result: {
		success: true,
		message: 'Downloaded file',
		file_path: '/tmp/flags-export.csv',
		size: 4312,
		bytes_written: 4312
	}
};

export const tcReasoning: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-reasoning',
	toolName: 'reasoning',
	args: {
		action: 'reason',
		question: 'What is the safest order to toggle flags during verification?',
		style: 'step-by-step'
	},
	status: 'success',
	durationMs: 540,
	result: {
		success: true,
		message: 'Reasoning complete',
		result:
			"Toggle from lowest to highest blast radius.\n\n1. `mfa_required` in `dev` first — no real users affected, the DB write is reversible, and the feature flag read path is idempotent.\n2. `enterprise_compliance` next — still dev-only, but it touches the audit log writer, so we want to verify the log rotation still works.\n3. Leave `new_chat_shell` and `delegate_groups` alone — they're already live in staging and flipping them risks surfacing latent bugs.\n4. Production-facing flags (`credit_metering_v2`) are out of scope for this verification; any change there goes through a separate release.\n\n**Final Answer:** Start with `mfa_required(dev)`, then `enterprise_compliance(dev)`, skip everything else."
	}
};

export const tcSettings: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-settings',
	toolName: 'web_env',
	args: { action: 'list' },
	status: 'success',
	durationMs: 14,
	result: {
		success: true,
		message: 'Listed 5 environment variables',
		env_vars: {
			FEATURE_FLAGS_CACHE_TTL: '60',
			DATABASE_URL: 'postgres://app:secretpw@db.internal/flags',
			SENTRY_DSN: 'https://abc123@sentry.io/4',
			ADMIN_API_TOKEN: 'sk_live_example',
			LOG_LEVEL: 'info'
		}
	}
};

export const tcCheckpoint: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-checkpoint',
	toolName: 'git',
	args: { action: 'checkpoint', commit_message: 'Scaffold flags admin API + page' },
	status: 'success',
	durationMs: 180,
	result: {
		success: true,
		message: 'Checkpoint saved',
		commit: '9f4a2b1',
		commit_message: 'Scaffold flags admin API + page',
		time: '2026-04-15T09:31:00Z'
	}
};

export const tcArtifact: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-artifact',
	toolName: 'artifact',
	args: {
		action: 'create',
		artifact_type: 'markdown',
		title: 'Feature flags admin — ship notes',
		content:
			'# Feature flags admin — ship notes\n\n## What shipped\n\n- `POST /flags/:id/toggle` API endpoint\n- `/admin/flags` Svelte page with optimistic toggle\n- `FEATURE_FLAGS_CACHE_TTL=60` env var for the flag cache\n\n## Rollout order\n\n1. `mfa_required(dev)` — verified, safe\n2. `enterprise_compliance(dev)` — next\n3. Production flags — separate release\n\n## Tests\n\n11 pytest cases passing in `tests/test_flags_api.py`, plus end-to-end browser verification of the toggle round-trip.\n'
	},
	status: 'success',
	durationMs: 220,
	result: {
		success: true,
		message: 'Artifact created',
		artifact_id: 'art_01HK2C8F',
		title: 'Feature flags admin — ship notes',
		type: 'markdown',
		content_preview:
			'# Feature flags admin — ship notes\n\n## What shipped\n\n- `POST /flags/:id/toggle` API endpoint\n- `/admin/flags` Svelte page with optimistic toggle\n- `FEATURE_FLAGS_CACHE_TTL=60` env var for the flag cache\n\n## Rollout order\n\n1. `mfa_required(dev)` — verified, safe\n2. `enterprise_compliance(dev)` — next',
		content:
			'# Feature flags admin — ship notes\n\n## What shipped\n\n- `POST /flags/:id/toggle` API endpoint\n- `/admin/flags` Svelte page with optimistic toggle\n- `FEATURE_FLAGS_CACHE_TTL=60` env var for the flag cache\n\n## Rollout order\n\n1. `mfa_required(dev)` — verified, safe\n2. `enterprise_compliance(dev)` — next\n3. Production flags — separate release\n\n## Tests\n\n11 pytest cases passing in `tests/test_flags_api.py`, plus end-to-end browser verification of the toggle round-trip.\n'
	}
};

export const tcPreview: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-preview',
	toolName: 'expose',
	args: { port: 5173, label: 'Feature flags admin (dev)' },
	status: 'success',
	durationMs: 140,
	result: {
		success: true,
		message: 'Port exposed',
		port: 5173,
		url: 'https://pg-5173-demo.sandbox.midsphere.dev',
		label: 'Feature flags admin (dev)'
	}
};

export const tcProject: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-project',
	toolName: 'web_init',
	args: { template: 'sveltekit-ts', name: 'flags-admin' },
	status: 'success',
	durationMs: 4200,
	result: {
		success: true,
		message: 'Initialized SvelteKit project',
		project_type: 'web',
		template: 'sveltekit-ts',
		name: 'flags-admin',
		path: '/workspace/flags-admin',
		framework: 'SvelteKit 2 + Svelte 5',
		package_manager: 'npm'
	}
};

export const tcKm: ToolCallMessage = {
	type: 'tool_call',
	callId: 'tc-km',
	toolName: 'km_read',
	args: { key: 'flags/toggle-api-contract' },
	status: 'success',
	durationMs: 32,
	result: {
		success: true,
		message: 'Read knowledge entry',
		key: 'flags/toggle-api-contract',
		scope: 'project',
		category: 'api',
		content:
			"# Toggle API contract\n\n`POST /flags/:id/toggle`\n\n**Body**: `{ environment: 'prod' | 'staging' | 'dev', enabled: bool }`\n\n**Response**: `{ ok: bool, environments: string[] }`\n\n**Idempotency**: Writes are idempotent. Sending `enabled: true` twice is a no-op on the second call.\n\n**Admin-gate**: The route is wrapped by `@admin_required`. Non-admin users get a 403 with no body.\n\n## Notes\n\n- Uses `update_fields=['environments']` to avoid touching `updated_at` on every toggle.\n- The response returns the full `environments` array so the client can reconcile optimistic state without a follow-up read."
	}
};

// ─── Plan state (seeded into planStateStore so CodeEditorPanel shows it) ──

export const planStateExample: PlanState = {
	goal: 'Ship admin page for feature_flags',
	currentPhaseId: 'phase-2',
	phases: [
		{
			id: 'phase-1',
			description: 'Explore existing flag code',
			status: 'completed',
			startedAt: '2026-04-15T09:00:00Z',
			completedAt: '2026-04-15T09:12:00Z'
		},
		{
			id: 'phase-2',
			description: 'Scaffold admin route + toggle API',
			status: 'in_progress',
			startedAt: '2026-04-15T09:12:00Z'
		},
		{
			id: 'phase-3',
			description: 'Verify end-to-end in browser',
			status: 'pending'
		},
		{
			id: 'phase-4',
			description: 'Ship',
			status: 'pending'
		}
	]
};

// ─── Simulated conversation thread ────────────────────────────────────────
//
// A realistic single-agent coding session using ONLY exo-registered tool
// names from `packages/sandbox/tools/`. Clicking any tool call row in the
// chat pins its canvas in the computer panel on the right.

const thread: Message[] = [
	// 1. User kickoff
	{
		type: 'user',
		text: 'Ship an admin page for feature flags: list all flags, toggle each on/off per environment. Use the existing `flags_featureflag` table — no new migrations.',
		sender_name: 'You'
	},

	// 2. Reasoning (inline italic row)
	reasoningShort,

	// 3. Agent plan
	{
		type: 'assistant',
		isStreaming: false,
		text: "On it. I'll explore the existing flag code first, then scaffold the admin page. Click any tool call row below to pin its canvas in the computer panel on the right."
	},

	// 4. file view → file-tree canvas
	tcFileTree,

	// 5. file read → code-viewer canvas
	tcCodeViewer,

	// 6. km_read → km canvas
	tcKm,

	// 7. search web → search canvas
	tcSearchWeb,

	// 8. web_db → database canvas
	tcDatabase,

	// 9. Rich markdown agent reply
	agentMessageMarkdown,

	// 10. file edit → diff canvas
	tcDiff,

	// 11. file write → file-status canvas
	tcFileStatusSave,

	// 12. web_env list → settings canvas
	tcSettings,

	// 13. git checkpoint → checkpoint canvas
	tcCheckpoint,

	// 14. HITL answered (user approved the verification step)
	hitlAnswered,

	// 15. reasoning → reasoning canvas
	tcReasoning,

	// 16. web_server start → dev-server canvas
	tcDevServer,

	// 17. expose → preview canvas
	tcPreview,

	// 18. browser → browser canvas
	tcBrowser,

	// 19. Transient error mid-run
	errorMessageNetwork,

	// 20. Recovery
	{
		type: 'assistant',
		isStreaming: false,
		text: 'Reconnected. Browser verification passed — toggled `mfa_required` in `dev` and the DB row updated. Wrapping up with the supporting assets you asked for.'
	},

	// 21. User attaches files mid-run
	userMessageWithFiles,

	// 22. perception transcribe → audio canvas
	tcAudio,

	// 23. perception analyze → vision canvas
	tcVision,

	// 24. search images → image masonry in search canvas
	tcSearchImages,

	// 25. generate create_image → media canvas
	tcMedia,

	// 26. artifact create → artifact canvas
	tcArtifact,

	// 27. shell exec (pytest) → terminal canvas
	tcTerminalShell,

	// 28. file download → download canvas
	tcDownload,

	// 29. web_init → project canvas
	tcProject,

	// 30. Final summary
	{
		type: 'assistant',
		isStreaming: false,
		text: '### Done\n\n- **API**: `POST /flags/:id/toggle` added, 11 tests passing.\n- **UI**: `/admin/flags` scaffolded with optimistic toggle.\n- **Icon**: generated from the mockup, saved to `assets/flag-toggle.png`.\n- **Ship notes**: artifact saved for the rollout thread.\n- **Export**: `flags-export.csv` downloaded for the rollout spreadsheet.\n\nReady to merge to main or open a PR against `feat/flags`?'
	},

	// 31. HITL pending (choice buttons render)
	hitlPending,

	// 32. Streaming tail
	agentMessageStreaming
];

export const conversationThread: Message[] = thread;

// Convenience — just the tool calls from the thread.
export const threadToolCalls: ToolCallMessage[] = thread.filter(
	(msg): msg is ToolCallMessage => msg.type === 'tool_call'
);
