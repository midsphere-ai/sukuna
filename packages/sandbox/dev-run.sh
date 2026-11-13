#!/usr/bin/env bash
# Sandbox local dev runner with full event streaming
# Usage: ./dev-run.sh 'task description'
set -euo pipefail

SANDBOX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=52849  # host-reserved — see <reserved_ports> in executor prompt. Must NOT overlap with dev servers agents may start.
SERVER_LOG="/tmp/sandbox_server.log"

task="${1:?Usage: ./dev-run.sh 'task description'}"
conv_id="run-$(date +%s)"

# Source local env so VAULT_ADDR / VAULT_TOKEN and LLM creds can come
# from .env.local (which is gitignored — never commit secrets). Loaded
# here (not just inside the server-start branch) so the vault fetch
# below works even when the server is already running.
if [ -f "$SANDBOX_DIR/.env.local" ]; then
    set -a && source "$SANDBOX_DIR/.env.local" && set +a
fi

VAULT_ADDR="${VAULT_ADDR:?VAULT_ADDR not set — add to $SANDBOX_DIR/.env.local}"
VAULT_TOKEN="${VAULT_TOKEN:?VAULT_TOKEN not set — add to $SANDBOX_DIR/.env.local}"

# ── Colors ───────────────────────────────────────────────────────────
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_DIM='\033[2m'
C_PLANNER='\033[1;34m'   # blue
C_EXECUTOR='\033[1;32m'  # green
C_KM='\033[1;35m'        # magenta
C_RALPH='\033[1;33m'     # yellow
C_HARNESS='\033[1;36m'   # cyan
C_TOOL='\033[0;33m'      # yellow
C_HOOK='\033[1;93m'      # bright yellow
C_CTX='\033[0;95m'       # bright magenta
C_ERROR='\033[1;31m'     # red

# ── Get API key from vault ───────────────────────────────────────────
echo -e "${C_DIM}Fetching API key from vault...${C_RESET}"
api_key=$(curl -sk "$VAULT_ADDR/v1/cubbyhole/root" \
    -H "X-Vault-Token: $VAULT_TOKEN" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['SUKUNA_AGENT_SERVER_API_KEY'])")

# ── Start server if not running ──────────────────────────────────────
if ! curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
    echo -e "${C_BOLD}Starting server on port $PORT (AGENT_VERBOSE=1)...${C_RESET}"
    cd "$SANDBOX_DIR"
    # .env.local already sourced at top of script
    export PORT TEMPLATE_BASE_PATH="$SANDBOX_DIR/templates" LOCAL_MODE=1 AGENT_VERBOSE=1
    uv run python -m agent_server > "$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    echo -e "${C_DIM}Server PID: $SERVER_PID (log: $SERVER_LOG)${C_RESET}"

    for i in $(seq 1 30); do
        if curl -s "http://localhost:$PORT/health" > /dev/null 2>&1; then
            echo -e "${C_BOLD}Server ready.${C_RESET}"
            break
        fi
        if ! kill -0 $SERVER_PID 2>/dev/null; then
            echo -e "${C_ERROR}Server failed to start. Check $SERVER_LOG${C_RESET}"
            tail -20 "$SERVER_LOG"
            exit 1
        fi
        sleep 1
    done
else
    echo -e "${C_DIM}Server already running on port $PORT.${C_RESET}"
fi

# ── Spawn run ────────────────────────────────────────────────────────
echo ""
echo -e "${C_BOLD}Task: $task${C_RESET}"
echo -e "${C_BOLD}Conversation: $conv_id${C_RESET}"
echo ""

json_body=$(python3 -c "
import json, sys
print(json.dumps({'task': sys.argv[1], 'conversation_id': sys.argv[2]}))
" "$task" "$conv_id")

response=$(curl -s -X POST "http://localhost:$PORT/runs" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $api_key" \
    -d "$json_body")

run_id=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('run_id',''))" 2>/dev/null)

if [ -z "$run_id" ]; then
    echo -e "${C_ERROR}Failed to create run:${C_RESET}"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    exit 1
fi

echo -e "${C_BOLD}Run ID: $run_id${C_RESET}"
echo ""
echo -e "══════════════════════════════════════════════════════════════════"
echo ""

# ── Cleanup on exit ──────────────────────────────────────────────────
cleanup() {
    [ -n "${LOG_TAIL_PID:-}" ] && kill "$LOG_TAIL_PID" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT

# ── Server log stream: KM, hooks, context, guardrails ────────────────
tail -n 0 -f "$SERVER_LOG" 2>/dev/null | while IFS= read -r line; do
    # KM events
    if [[ "$line" == *"km_loop"* && "$line" == *"tick"* ]]; then
        msgs=$(echo "$line" | grep -oP 'n_messages=\K[0-9]+' || true)
        echo -e "${C_KM}[KM] tick — ${msgs:-?} messages${C_RESET}"
    elif [[ "$line" == *"km_nudge pushed"* ]]; then
        title=$(echo "$line" | grep -oP 'title=\K\S+' || true)
        urgency=$(echo "$line" | grep -oP 'urgency=\K\S+' || true)
        target=$(echo "$line" | grep -oP 'target=\K\S+' || true)
        echo -e "${C_KM}[KM] nudge -> ${target}: ${title} (${urgency})${C_RESET}"
    elif [[ "$line" == *"km_run:"* ]]; then
        clip=$(echo "$line" | sed 's/.*km_run: //' | cut -c1-140)
        echo -e "${C_KM}[KM] run: ${clip}${C_RESET}"

    # Context engine / compaction / summarization
    elif [[ "$line" == *"compaction:"* ]]; then
        clip=$(echo "$line" | sed 's/.*compaction:/compaction:/' | cut -c1-140)
        echo -e "${C_CTX}[CTX] ${clip}${C_RESET}"
    elif [[ "$line" == *"summarization:"* ]]; then
        clip=$(echo "$line" | sed 's/.*summarization:/summarization:/' | cut -c1-140)
        echo -e "${C_CTX}[CTX] ${clip}${C_RESET}"
    elif [[ "$line" == *"context engine:"* ]]; then
        clip=$(echo "$line" | sed 's/.*context engine:/context engine:/' | cut -c1-140)
        echo -e "${C_CTX}[CTX] ${clip}${C_RESET}"

    # Hook injections (from AGENT_VERBOSE=1)
    elif [[ "$line" == *"max_steps_warning_injected"* ]]; then
        echo -e "${C_ERROR}[HOOK] max_steps warning injected${C_RESET}"
    elif [[ "$line" == *"inject_ephemeral"* ]]; then
        clip=$(echo "$line" | sed 's/.*inject_ephemeral/inject_ephemeral/' | cut -c1-140)
        echo -e "${C_HOOK}[HOOK] ${clip}${C_RESET}"
    elif [[ "$line" == *"filesystem_first"* ]]; then
        echo -e "${C_HOOK}[HOOK] filesystem_first reminder${C_RESET}"
    elif [[ "$line" == *"advise_cache"* ]]; then
        reason=$(echo "$line" | grep -oP 'reason=\K\S+' || true)
        echo -e "${C_HOOK}[HOOK] advise cache invalidated (${reason})${C_RESET}"
    elif [[ "$line" == *"plan_context_hook"* ]]; then
        echo -e "${C_HOOK}[HOOK] plan context injected${C_RESET}"

    # Orchestration harness events (AGENT_VERBOSE=1)
    elif [[ "$line" == *"orchestrator_started"* ]]; then
        echo -e "${C_HARNESS}[HARNESS] orchestrator started${C_RESET}"
    elif [[ "$line" == *"handoff_to_executor"* ]]; then
        name=$(echo "$line" | grep -oP 'executor_name=\K\S+' || true)
        echo -e "${C_HARNESS}[HARNESS] handoff -> ${name}${C_RESET}"
    elif [[ "$line" == *"executor_created"* ]]; then
        name=$(echo "$line" | grep -oP 'executor_name=\K\S+' || true)
        echo -e "${C_HARNESS}[HARNESS] executor created: ${name}${C_RESET}"
    elif [[ "$line" == *"executor_completed"* ]]; then
        name=$(echo "$line" | grep -oP 'executor_name=\K\S+' || true)
        turns=$(echo "$line" | grep -oP 'turns=\K\S+' || true)
        echo -e "${C_HARNESS}[HARNESS] executor completed: ${name} (${turns} turns)${C_RESET}"
    elif [[ "$line" == *"executor_truncated"* ]]; then
        echo -e "${C_ERROR}[HARNESS] executor TRUNCATED (hit max_steps)${C_RESET}"
    elif [[ "$line" == *"delegation_detected"* ]]; then
        echo -e "${C_HARNESS}[HARNESS] delegation detected${C_RESET}"
    elif [[ "$line" == *"planner_direct_response"* ]]; then
        echo -e "${C_HARNESS}[HARNESS] planner responded directly (done)${C_RESET}"

    # Guardrails
    elif [[ "$line" == *"blocked by guardrail"* ]]; then
        who=$(echo "$line" | grep -oP 'Executor \K\S+' || echo "agent")
        echo -e "${C_ERROR}[GUARDRAIL] ${who} blocked${C_RESET}"
    elif [[ "$line" =~ Rail[[:space:]]+blocked|Rail:[[:space:]]+blocked|Rail[[:alnum:]]+[[:space:]]+blocked ]] \
      || [[ "$line" == *"ExecutorMessageModeRail"* ]] \
      || [[ "$line" == *"ExecutorResultFileRail"* ]] \
      || [[ "$line" == *"MarkdownContextStorageRail"* ]] \
      || [[ "$line" == *"PlannerToolEnforcementRail"* ]] \
      || [[ "$line" == *"PlannerPlanRequiredRail"* ]] \
      || [[ "$line" == *"ToolBlacklistRail"* ]] \
      || [[ "$line" == *"PromptLeakageRail"* ]]; then
        clip=$(echo "$line" | sed -E 's/.*(Rail[[:alnum:]]*)/\1/' | cut -c1-200)
        echo -e "${C_ERROR}[GUARDRAIL] ${clip}${C_RESET}"

    # Model provider errors
    elif [[ "$line" == *"ERROR"* && "$line" != *"no AgentRun"* ]]; then
        clip=$(echo "$line" | cut -c1-180)
        echo -e "${C_ERROR}${clip}${C_RESET}"
    fi
done &
LOG_TAIL_PID=$!

# ── SSE stream: planner, executor, ralph — all agent events ──────────
curl -sN "http://localhost:$PORT/runs/$run_id/stream?api_key=$api_key" | python3 -u -c "
import sys, json

PLANNER = '\033[1;34m'
EXECUTOR = '\033[1;32m'
RALPH = '\033[1;33m'
HARNESS = '\033[1;36m'
TOOL = '\033[0;33m'
ERROR = '\033[1;31m'
DIM = '\033[2m'
BOLD = '\033[1m'
RESET = '\033[0m'

def agent_color(name):
    if not name:
        return DIM
    n = name.lower()
    if 'planner' in n: return PLANNER
    if 'ralph' in n: return RALPH
    return EXECUTOR

def agent_tag(name):
    if not name:
        return '???'
    n = name.lower()
    if 'planner' in n: return 'PLANNER'
    if 'ralph' in n: return 'RALPH'
    return f'EXEC:{name[:12]}'

text_buffer = {}

for raw_line in sys.stdin:
    line = raw_line.strip()
    if not line or line.startswith(':') or not line.startswith('data:'):
        continue
    data_str = line[5:].strip()
    if not data_str:
        continue
    try:
        d = json.loads(data_str)
    except json.JSONDecodeError:
        continue

    t = d.get('type', '')
    seq = d.get('sequence', '?')
    agent = d.get('agent_name', '') or d.get('source_agent', '')
    color = agent_color(agent)
    tag = agent_tag(agent)

    if t == 'text':
        text = d.get('text', '')
        # Buffer text deltas into full lines (they're streamed word-by-word)
        buf = text_buffer.get(agent, '')
        buf += text
        if '\n' in buf or len(buf) > 200:
            for ln in buf.split('\n'):
                ln = ln.strip()
                if ln:
                    print(f'{color}[{tag}] {ln[:300]}{RESET}', flush=True)
            text_buffer[agent] = ''
        else:
            text_buffer[agent] = buf

    elif t == 'tool_call':
        # Flush any buffered text before tool call
        if text_buffer.get(agent):
            ln = text_buffer[agent].strip()
            if ln:
                print(f'{color}[{tag}] {ln[:300]}{RESET}', flush=True)
            text_buffer[agent] = ''
        name = d.get('tool_name', '') or d.get('name', '')
        args_raw = d.get('arguments', '')
        if isinstance(args_raw, str):
            try:
                args_raw = json.loads(args_raw)
            except:
                pass
        if isinstance(args_raw, dict):
            short_args = {k: (str(v)[:60] + '...' if len(str(v)) > 60 else v) for k, v in args_raw.items()}
            args_str = json.dumps(short_args, ensure_ascii=False)[:200]
        else:
            args_str = str(args_raw)[:150]
        print(f'{TOOL}[{tag}] → {name}({args_str}){RESET}', flush=True)

    elif t == 'tool_result':
        result = str(d.get('result', '') or d.get('content', ''))[:150]
        status = d.get('status', '')
        print(f'{DIM}[{tag}] ← {status}: {result}{RESET}', flush=True)

    elif t == 'step':
        status = d.get('status', '')
        if status == 'completed':
            # Flush text buffer
            if text_buffer.get(agent):
                ln = text_buffer[agent].strip()
                if ln:
                    print(f'{color}[{tag}] {ln[:300]}{RESET}', flush=True)
                text_buffer[agent] = ''

    elif t == 'harness':
        h_status = d.get('status', '')
        print(f'{HARNESS}[HARNESS] {h_status} {str(d)[:140]}{RESET}', flush=True)

    elif t == 'reasoning':
        text = d.get('text', '')[:200]
        if text.strip():
            print(f'{DIM}[{tag}] 🧠 {text}{RESET}', flush=True)

    elif t == 'error':
        err = d.get('error', '')
        print(f'{ERROR}[{tag}] ✗ {err}{RESET}', flush=True)

    elif t in ('run_completed', 'run_failed', 'run_cancelled'):
        print(f'{BOLD}═══ {t.upper()} ═══{RESET}', flush=True)
        break

    elif t == 'hitl_request':
        q = d.get('question', '') or d.get('text', '')
        print(f'{BOLD}[HITL] {q}{RESET}', flush=True)

    elif t == 'mcp_progress':
        server = d.get('server', '')
        tool_name = d.get('tool', '')
        msg = d.get('message', '')
        print(f'{TOOL}[MCP] {server}:{tool_name} {msg}{RESET}', flush=True)

    elif t == 'ralph_iteration':
        iter_n = d.get('iteration', '?')
        print(f'{RALPH}[RALPH] iteration {iter_n}{RESET}', flush=True)

    elif t == 'ralph_stop':
        reason = d.get('reason', '')
        print(f'{RALPH}[RALPH] stop: {reason}{RESET}', flush=True)

    elif t == 'message_injected':
        content = d.get('content', '')[:150]
        print(f'{BOLD}[INJECT] {content}{RESET}', flush=True)

    else:
        print(f'{DIM}[{seq}] {t}{RESET}', flush=True)
"

echo ""
echo -e "${C_BOLD}══════════════════════════════════════════════════════════════════${C_RESET}"
