# CLI-Offloaded Tools — System Prompt Reference

This file documents the tool offloading setup for reference when writing
or editing the agent's system prompt (`AGENT_INSTRUCTIONS` env var).

## Architecture

The agent has three categories of tools:

### Native Tools (in LLM context window)
Loaded as `tools=` parameters — the LLM sees their schemas directly.

| Tool | Group | Toggle-Gated? |
|------|-------|---------------|
| `file` | file | No |
| `shell` | code | Yes (`shell_commands`) |
| `match` | match | No |
| `plan` | plan | No |
| `search` | search | Yes (`web_search`) |
| `browse` | browse | Yes (`browser`) |

Plus dynamically added: `ralph_loop`, `call_executor`, `spawn_self`, `human_input`, `skill`

### CLI Tools (offloaded via `exo tool`)
NOT in the context window. Called via shell tool:

| Tool | Toggle-Gated? | Description |
|------|---------------|-------------|
| `artifact` | No | Rich displayable artifacts (HTML, SVG, code, mermaid) |
| `git` | No | Git checkpoint management |
| `mobiledev` | Yes (`computer_use`) | Expo mobile dev |
| `perception` | No | Image/audio/video analysis |
| `reasoning` | Yes (`complex_reasoning`) | Deep reasoning via secondary LLM |
| `webdev` | No | Next.js web dev |
| `expose` | No | Expose sandbox ports |

### PATH Binaries (plain Unix commands on $PATH)
NOT `exo tool call` targets. Invoked directly with the shell tool. No schema, no toggle gating, positional args only.

| Binary | Backend | Description |
|--------|---------|-------------|
| `exo-pptx-to-pdf` | libreoffice --headless | Convert `.pptx` / `.ppt` → PDF |
| `exo-doc-to-pdf` | libreoffice --headless | Convert `.docx` / `.doc` / `.odt` / `.rtf` → PDF |
| `exo-xlsx-to-pdf` | libreoffice --headless | Convert `.xlsx` / `.xls` / `.ods` → PDF |
| `exo-markdown-to-pdf` | python-markdown + playwright chromium | Convert `.md` → styled HTML → PDF |

Scripts live in `tools/bin/`; the Dockerfile writes thin bash wrappers into `/usr/local/bin/` that exec them with the venv python so `markdown` and `playwright` resolve.

## How It Works

1. `EXO_TOOL_SOURCE` env var points to `tools/cli_tools.py` (barrel module)
2. `PYTHONPATH` includes `tools/` for internal imports
3. Agent uses shell to run: `exo tool call <name> -j '{...}'`
4. `exo tool schema <name>` for self-service schema discovery
5. Toggle gating is handled by `build_cli_tool_catalog()` in `agent_server/infra/registry.py`

## System Prompt Snippet

The `build_cli_tool_catalog()` function in `agent_server/infra/registry.py`
generates this automatically and injects it into agent instructions. It emits
two sections: a `## CLI Tools` section for `exo tool call` targets and a
`## PATH Binaries` section for the direct-invocation helpers. PATH binaries
are not toggle-gated — they're always included.

A detailed `cli-tools` skill is available in `skills/cli-tools/skill.md`
with full parameter docs, examples, and usage patterns for every entry.

## Key Files

- `tools/cli_tools.py` — Barrel module for `exo tool` discovery
- `tools/bin/exo-*-to-pdf` — PATH-binary PDF conversion helpers
- `agent_server/infra/registry.py` — `build_cli_tool_catalog()`, `_CLI_TOOL_CATALOG`, `_PATH_BINARY_CATALOG`
- `agent_server/orchestrator_harness.py` — CLI catalog threaded to executor agents
- `skills/cli-tools/skill.md` — Detailed skill reference for agents
- `e2b/Dockerfile` — `exo` CLI symlinked into PATH; PATH-binary wrappers installed into `/usr/local/bin/`
