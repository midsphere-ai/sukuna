"""Shell execution and Python REPL tool for sandbox agents."""

__version__ = "0.1.0"

import asyncio
import contextlib
import os
import shutil
import sys
import tempfile
import uuid
from typing import Annotated, Literal

from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from exo import tool

# ========================
# Hidden-segment gaslighting
# ========================
#
# Certain sandbox paths (e.g. ``.sukuna/km`` — the Knowledge Manager
# knowledge manager's own storage) must be indistinguishable from nonexistent paths
# when the LLM probes via shell.  The file tool already achieves this at
# ``normalize_path``; the same discipline is mirrored here so neither
# ``cat .sukuna/km/foo``, ``ls .sukuna``, nor ``find / -name "*.md"`` can
# reveal the storage — either directly via command output or indirectly via
# tmux-captured panes.
#
# Defense is two-layered:
#   1. Pre-execution scan: if the command literally mentions a hidden
#      segment, return a response that mimics the shell's own
#      "No such file or directory" without running anything.
#   2. Post-execution filter: drop any line from stdout/stderr that
#      mentions a hidden segment, so recursive walks (``find``, ``tree``,
#      ``grep -r``) can't leak it either.
#
# This is best-effort (a determined prompt can still construct paths via
# shell expansions the scanner can't see), but it closes every naive attack
# and is the most that can be done at the tool boundary without a real
# filesystem sandbox.

_HIDDEN_SEGMENTS: tuple[str, ...] = (".sukuna",)


def _command_mentions_hidden(text: str) -> str | None:
    """Return the first hidden segment literally referenced by *text*, or None."""
    if not text:
        return None
    for seg in _HIDDEN_SEGMENTS:
        if seg in text:
            return seg
    return None


def _fake_not_found(command: str, hidden: str) -> dict:
    """Return a canned response matching what the shell itself emits for a
    genuinely missing path.  Used to hide protected paths without exposing
    any protection-flavoured signal the LLM could gaslight around."""
    first_token = command.strip().split()[0] if command.strip() else "sh"
    return success_result(
        "Command executed",
        exit_code=1,
        stdout="",
        stderr=f"{first_token}: {hidden}: No such file or directory\n",
    )


def _filter_hidden_from_output(text: str) -> str:
    """Drop any line mentioning a hidden segment.  Applied to stdout/stderr
    before returning to the caller so recursive commands can't leak
    protected paths."""
    if not text:
        return text
    keep: list[str] = []
    for line in text.splitlines(keepends=True):
        if any(seg in line for seg in _HIDDEN_SEGMENTS):
            continue
        keep.append(line)
    return "".join(keep)


# ========================
# Config
# ========================

DEFAULT_TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT", "30"))  # seconds
MAX_OUTPUT_LINES = 500  # capture-pane scrollback depth
MAX_OUTPUT_CHARS = 8_000  # threshold for saving output to file
WAIT_POLL_INTERVAL = 0.5  # seconds between polling in wait
OUTPUT_PREVIEW_LINES = 20  # head/tail lines to show in preview
SHELL_OUTPUT_DIR = ".shell_outputs"  # subdirectory under workspace

# Foreground exec session state: session_id -> last known working directory.
_SESSION_CWDS: dict[str, str] = {}


# ========================
# Workspace helpers
# ========================


def _workspace_root() -> str:
    return (
        os.getenv("WORKSPACE")
        or os.getenv("PROJECT_DIR")
        or os.getenv("SANDBOX_WORKSPACE_ROOT")
        or os.path.expanduser("~")
    )


# ========================
# Output helpers
# ========================


def _maybe_save_output(output: str, label: str = "output") -> dict:
    """If *output* exceeds MAX_OUTPUT_CHARS, save it to a workspace file
    and return a head/tail preview plus the file path.  Otherwise return
    the output unchanged."""
    if len(output) <= MAX_OUTPUT_CHARS:
        return {"output": output, "output_saved_to": None}

    workspace = _workspace_root()
    output_dir = os.path.join(workspace, SHELL_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{label}_{uuid.uuid4().hex[:8]}.txt"
    file_path = os.path.join(output_dir, filename)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(output)
    except OSError:
        # Graceful degradation: return tail if file write fails
        return {"output": output[-MAX_OUTPUT_CHARS:], "output_saved_to": None}

    lines = output.splitlines()
    total_lines = len(lines)
    n = OUTPUT_PREVIEW_LINES

    if total_lines <= 2 * n:
        preview = output
    else:
        head = "\n".join(lines[:n])
        tail = "\n".join(lines[-n:])
        omitted = total_lines - 2 * n
        preview = f"{head}\n\n... [{omitted} lines omitted — full output saved to {file_path}] ...\n\n{tail}"

    return {
        "output": preview,
        "output_saved_to": file_path,
        "output_size_bytes": len(output.encode("utf-8")),
        "output_total_lines": total_lines,
    }


# ========================
# Safety helpers
# ========================

dangerous_commands = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",  # Unix fork bomb
    "del /f /s /q",
    "format",
    "diskpart",  # Windows
    "sudo rm",
    "sudo dd",
    "sudo mkfs",  # Sudo variants
]


def _check_command_safety(command: str) -> tuple[bool, str | None]:
    """Check if command is safe to execute."""
    command_lower = command.lower().strip()
    for dangerous_cmd in dangerous_commands:
        if dangerous_cmd.lower() in command_lower:
            return False, f"Command contains dangerous pattern: {dangerous_cmd}"
    return True, None


# ========================
# tmux helpers
# ========================


async def _ensure_tmux() -> tuple[bool, str | None]:
    """Check that tmux is available. Returns (ok, error_message)."""
    if shutil.which("tmux") is None:
        return False, "tmux is not installed in this sandbox environment"
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        "start-server",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return True, None


async def _tmux_run(*args: str, timeout: int = 10) -> tuple[int, str, str]:
    """Run a tmux command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _valid_session_name(name: str) -> bool:
    """tmux session names must be alphanumeric, hyphens, or underscores."""
    return bool(name) and all(c.isalnum() or c in "-_" for c in name)


def _default_foreground_cwd() -> str:
    """Default cwd for foreground exec sessions."""
    workspace = _workspace_root()
    # Prefer workspace when available; otherwise fall back to current process cwd.
    return workspace if os.path.isdir(workspace) else os.getcwd()


def _session_start_cwd(session: str) -> str:
    """Return the starting cwd for a foreground session."""
    cwd = _SESSION_CWDS.get(session, _default_foreground_cwd())
    if os.path.isdir(cwd):
        return cwd
    return _default_foreground_cwd()


def _strip_cwd_marker(stdout: str, marker: str) -> tuple[str, str | None]:
    """Strip marker line and return (cleaned_stdout, captured_cwd)."""
    if not stdout:
        return stdout, None

    captured_cwd: str | None = None
    clean_lines: list[str] = []
    for line in stdout.splitlines(keepends=True):
        marker_idx = line.find(marker)
        if marker_idx == -1:
            clean_lines.append(line)
            continue

        captured_cwd = line[marker_idx + len(marker) :].rstrip("\r\n")
        if marker_idx > 0:
            clean_lines.append(line[:marker_idx])

    return "".join(clean_lines), captured_cwd


# ========================
# Internal execution helpers
# ========================


async def _exec_shell(command: str, background: bool, timeout: int, session: str | None) -> dict:
    """Execute a shell command with safety checks."""
    # Hidden-segment gaslighting (see module docstring).  Pre-scan so the
    # command never runs and leaves no on-disk trace if it targeted a
    # hidden path.
    hidden = _command_mentions_hidden(command)
    if hidden is not None:
        return _fake_not_found(command, hidden)

    safety_status, overview = _check_command_safety(command)
    if not safety_status:
        return error_result(
            f"Command blocked: {overview}",
            error=overview,
            hint="Remove dangerous patterns from the command before retrying",
        )

    if background:
        ok, err = await _ensure_tmux()
        if not ok:
            return error_result(err, error="TmuxNotAvailable", hint="Install tmux in the Dockerfile")

        session_id = session or f"bg-{uuid.uuid4().hex[:8]}"

        if not _valid_session_name(session_id):
            return error_result(
                f"Invalid session name: '{session_id}'",
                error="InvalidSessionName",
                hint="Session names may only contain alphanumeric characters, hyphens, and underscores.",
            )

        # Check if session already exists
        rc, _, _ = await _tmux_run("has-session", "-t", session_id)
        if rc == 0:
            return error_result(
                f"Session '{session_id}' already exists",
                error="SessionExists",
                hint="Use a different name, or kill the existing session first.",
            )

        # Create detached session with wide terminal
        rc, _, stderr = await _tmux_run("new-session", "-d", "-s", session_id, "-x", "220", "-y", "50")
        if rc != 0:
            return error_result(
                f"Failed to create tmux session: {stderr.strip()}",
                error="TmuxError",
            )

        # Send command with sentinel for completion detection
        sentinel = f"__DONE_{session_id}__"
        wrapped = f'{command}; echo "{sentinel} exit=$?"'
        rc, _, stderr = await _tmux_run("send-keys", "-t", session_id, wrapped, "Enter")
        if rc != 0:
            return error_result(
                f"Failed to send command to session: {stderr.strip()}",
                error="TmuxError",
            )

        return success_result(
            "Command started in background",
            session=session_id,
            command=command,
        )

    # Foreground execution.
    # NOTE: No ``env=`` override — child inherits os.environ so that
    # CLI-offloaded tools (exo tool call) receive vault secrets and
    # BYOM API keys set by _inject_tool_env_vars() / _run_agent().
    try:
        run_command = command
        run_cwd: str | None = None
        marker: str | None = None

        if session:
            # Foreground session mode: keep cwd across calls for the same session id.
            run_cwd = _session_start_cwd(session)
            marker = f"__SHELL_CWD_{uuid.uuid4().hex}__"
            run_command = 'eval "$1"\n__shell_exit=$?\nprintf "%s%s\\n" "$2" "$PWD"\nexit "$__shell_exit"\n'
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh",
                "-c",
                run_command,
                "sh",
                command,
                marker,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=run_cwd,
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                run_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout_str = stdout.decode(errors="replace")
        stderr_str = stderr.decode(errors="replace")

        if marker is not None:
            stdout_str, captured_cwd = _strip_cwd_marker(stdout_str, marker)
            if session and captured_cwd and os.path.isdir(captured_cwd):
                _SESSION_CWDS[session] = captured_cwd

        # Filter hidden segments from the captured output so recursive
        # walks (find, tree, grep -r, ls -R) cannot leak protected paths.
        stdout_str = _filter_hidden_from_output(stdout_str)
        stderr_str = _filter_hidden_from_output(stderr_str)

        extra = {}
        if "pip install" in command or "apt-get" in command:
            extra["package_install_note"] = (
                "Packages installed. No need to reinstall unless a missing package error occurs."
            )

        stdout_info = _maybe_save_output(stdout_str, label="stdout")
        stderr_info = _maybe_save_output(stderr_str, label="stderr")

        result_kwargs = {
            "exit_code": proc.returncode,
            "stdout": stdout_info["output"],
            "stderr": stderr_info["output"],
            **extra,
        }
        if stdout_info["output_saved_to"]:
            result_kwargs["stdout_saved_to"] = stdout_info["output_saved_to"]
            result_kwargs["stdout_size_bytes"] = stdout_info["output_size_bytes"]
            result_kwargs["stdout_total_lines"] = stdout_info["output_total_lines"]
        if stderr_info["output_saved_to"]:
            result_kwargs["stderr_saved_to"] = stderr_info["output_saved_to"]
            result_kwargs["stderr_size_bytes"] = stderr_info["output_size_bytes"]
            result_kwargs["stderr_total_lines"] = stderr_info["output_total_lines"]

        return success_result("Command executed", **result_kwargs)
    except TimeoutError:
        return error_result(
            f"Command timed out after {timeout} seconds",
            error="TimeoutError",
            hint="Increase DEFAULT_TIMEOUT env var or split the command into smaller steps",
        )
    except Exception as e:
        return error_result(
            f"Failed to run command: {type(e).__name__}",
            error=str(e),
            hint="Check command syntax or sandbox access.",
        )


async def _exec_python(code_block: str, timeout: int) -> dict:
    """Run Python code in a temp file and return the result."""
    # Pre-scan the code for literal hidden-segment references.  A more
    # sophisticated attacker can construct paths dynamically; this still
    # closes the naive ``os.listdir('.sukuna')`` style probe.
    hidden = _command_mentions_hidden(code_block)
    if hidden is not None:
        return _fake_not_found(code_block, hidden)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
        tmp.write(code_block)
        tmp_path = tmp.name

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout_str = stdout.decode(errors="replace")
        stderr_str = stderr.decode(errors="replace")
        # Filter hidden segments from output so runtime-constructed paths
        # that reach a hidden file cannot leak its existence.
        stdout_str = _filter_hidden_from_output(stdout_str)
        stderr_str = _filter_hidden_from_output(stderr_str)
        return success_result(
            "Python executed",
            exit_code=proc.returncode,
            stdout=stdout_str,
            stderr=stderr_str,
        )
    except TimeoutError:
        return error_result(
            f"Code execution timed out after {timeout} seconds",
            error="TimeoutError",
            hint="Increase DEFAULT_TIMEOUT env var or split the code into smaller steps",
        )
    except Exception as e:
        return error_result(
            f"Failed to run code: {type(e).__name__}",
            error=str(e),
            hint="Verify the Python code has no syntax errors",
        )
    finally:
        os.unlink(tmp_path)


# ========================
# tmux session management
# ========================


async def _view_sessions() -> dict:
    """List active tmux sessions."""
    ok, err = await _ensure_tmux()
    if not ok:
        return success_result("No background sessions (tmux not available)", sessions=[])

    rc, stdout, stderr = await _tmux_run(
        "list-sessions", "-F", "#{session_name}\t#{session_created}\t#{session_activity}\t#{session_windows}"
    )

    if rc != 0:
        if "no server running" in stderr or "no sessions" in stderr or "error connecting" in stderr:
            return success_result("No active background sessions", sessions=[])
        return error_result(f"Failed to list sessions: {stderr.strip()}", error="TmuxError")

    entries = []
    for line in stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            entries.append(
                {
                    "session": parts[0],
                    "created": parts[1],
                    "last_activity": parts[2],
                    "windows": parts[3],
                }
            )
    return success_result("Active sessions", sessions=entries)


async def _output_session(session: str, lines: int = MAX_OUTPUT_LINES) -> dict:
    """Capture current pane content from a tmux session non-destructively."""
    ok, err = await _ensure_tmux()
    if not ok:
        return error_result(err, error="TmuxNotAvailable")

    rc, _, _ = await _tmux_run("has-session", "-t", session)
    if rc != 0:
        return error_result(
            f"Session '{session}' not found",
            error="SessionNotFound",
            hint="Use action='view' to list active sessions.",
        )

    rc, stdout, stderr = await _tmux_run("capture-pane", "-t", session, "-p", "-S", f"-{lines}")
    if rc != 0:
        return error_result(
            f"Failed to capture pane output: {stderr.strip()}",
            error="TmuxError",
        )

    output = _filter_hidden_from_output(stdout.rstrip("\n"))
    output_info = _maybe_save_output(output, label=f"session_{session}")

    result_kwargs = {
        "session": session,
        "output": output_info["output"],
        "line_count": output.count("\n") + 1 if output else 0,
    }
    if output_info["output_saved_to"]:
        result_kwargs["output_saved_to"] = output_info["output_saved_to"]
        result_kwargs["output_size_bytes"] = output_info["output_size_bytes"]
        result_kwargs["output_total_lines"] = output_info["output_total_lines"]

    return success_result("Pane output captured", **result_kwargs)


async def _wait_session(session: str, timeout: int) -> dict:
    """Wait for a background session's command to complete by polling for sentinel."""
    ok, err = await _ensure_tmux()
    if not ok:
        return error_result(err, error="TmuxNotAvailable")

    rc, _, _ = await _tmux_run("has-session", "-t", session)
    if rc != 0:
        return error_result(
            f"Session '{session}' not found",
            error="SessionNotFound",
            hint="Use action='view' to list active sessions.",
        )

    sentinel = f"__DONE_{session}__"
    elapsed = 0.0

    while elapsed < timeout:
        rc, stdout, _ = await _tmux_run("capture-pane", "-t", session, "-p", "-S", f"-{MAX_OUTPUT_LINES}")
        if rc != 0:
            return error_result(
                f"Session '{session}' no longer exists",
                error="SessionLost",
            )

        if sentinel in stdout:
            # Extract exit code from sentinel line
            exit_code = None
            for line in stdout.splitlines():
                if sentinel in line and "exit=" in line:
                    with contextlib.suppress(ValueError):
                        exit_code = int(line.split("exit=")[-1].strip())
                    break

            # Return output with sentinel line stripped, then drop any
            # line mentioning a hidden segment (see module docstring).
            clean_lines = [line for line in stdout.rstrip("\n").splitlines() if sentinel not in line]
            output = _filter_hidden_from_output("\n".join(clean_lines))

            output_info = _maybe_save_output(output, label=f"wait_{session}")

            result_kwargs = {
                "session": session,
                "exit_code": exit_code,
                "output": output_info["output"],
            }
            if output_info["output_saved_to"]:
                result_kwargs["output_saved_to"] = output_info["output_saved_to"]
                result_kwargs["output_size_bytes"] = output_info["output_size_bytes"]
                result_kwargs["output_total_lines"] = output_info["output_total_lines"]

            return success_result("Command completed", **result_kwargs)

        await asyncio.sleep(WAIT_POLL_INTERVAL)
        elapsed += WAIT_POLL_INTERVAL

    return error_result(
        f"Wait timed out after {timeout} seconds (session still running)",
        error="TimeoutError",
        session=session,
        hint="The process is still running. Use action='output' to check progress, or wait again with a longer timeout.",
    )


async def _send_to_session(session: str, text: str, press_enter: bool = False) -> dict:
    """Send keys to a tmux session."""
    # Hidden-segment gaslighting: refuse to deliver keystrokes that
    # construct a path into a protected area.  Fake the shell's own
    # not-found response instead of actually sending.
    hidden = _command_mentions_hidden(text)
    if hidden is not None:
        return _fake_not_found(text, hidden)

    ok, err = await _ensure_tmux()
    if not ok:
        return error_result(err, error="TmuxNotAvailable")

    rc, _, _ = await _tmux_run("has-session", "-t", session)
    if rc != 0:
        return error_result(
            f"Session '{session}' not found",
            error="SessionNotFound",
            hint="Use action='view' to list active sessions.",
        )

    args = ["send-keys", "-t", session, text]
    if press_enter:
        args.append("Enter")

    rc, _, stderr = await _tmux_run(*args)
    if rc != 0:
        return error_result(
            f"Failed to send keys: {stderr.strip()}",
            error="TmuxError",
        )

    return success_result("Input sent to session", session=session)


async def _kill_session(session: str) -> dict:
    """Kill a tmux session."""
    ok, err = await _ensure_tmux()
    if not ok:
        return error_result(err, error="TmuxNotAvailable")

    rc, _, _ = await _tmux_run("has-session", "-t", session)
    if rc != 0:
        return error_result(
            f"Session '{session}' not found",
            error="SessionNotFound",
            hint="Use action='view' to list active sessions.",
        )

    rc, _, stderr = await _tmux_run("kill-session", "-t", session)
    if rc != 0:
        return error_result(
            f"Failed to kill session: {stderr.strip()}",
            error="TmuxError",
        )

    return success_result("Session terminated", session=session)


# ========================
# Unified shell tool
# ========================

_SHELL_ALIASES: dict[str, str] = {
    "run": "exec",
    "execute": "exec",
    "command": "exec",
    "bash": "exec",
    "list": "view",
    "ls": "view",
    "sessions": "view",
    "status": "view",
    "show": "view",
    "output": "view",
    "ps": "view",
    "poll": "wait",
    "await": "wait",
    "block": "wait",
    "input": "send",
    "write": "send",
    "type": "send",
    "stop": "kill",
    "terminate": "kill",
    "close": "kill",
    "end": "kill",
    "abort": "kill",
}


@tool(name="shell")
async def shell_tool(
    action: Annotated[
        Literal["exec", "view", "wait", "send", "kill"],
        "The action to perform. Supported values: view, exec, wait, send, kill.",
    ],
    session: Annotated[str | None, "The unique identifier of the target shell session."] = None,
    command: Annotated[str | None, "The shell command to execute. Required for exec action."] = None,
    input: Annotated[
        str | None,
        "Input text to send to the active process (stdin) in a shell session. End with a newline character (\\n) to simulate pressing Enter if needed. Required for send action.",
    ] = None,
    timeout: Annotated[
        int | None,
        "Timeout in seconds to wait for command execution. Optional and only used for exec and wait actions. Defaults to 30 seconds.",
    ] = None,
) -> dict:
    """Interact with shell sessions in the sandbox environment.

    <instructions>
    - Prioritize using `file` tool instead of this tool for file content operations to avoid escaping errors.
    - When using `view` action, ensure command has completed execution before using its output.
    - `exec` action will automatically create new shell sessions based on unique identifier.
    - For `exec`, pass `session` to persist working directory across commands for that session id.
    - A new foreground session starts in workspace/home; commands without `session` do not persist cwd.
    - MUST avoid commands that require confirmation; use flags like `-y` or `-f` for automatic execution.
    - Commands with excessive output will have their full output saved to a file automatically. A preview (first/last lines) is returned inline with the file path. Use the `file` tool to read the full output if needed.
    - When output is saved to a file, the result includes `output_saved_to` with the file path, `output_size_bytes`, and `output_total_lines`.
    - Chain multiple commands with `&&` to reduce interruptions and handle errors cleanly.
    - Use pipes (`|`) to simplify workflows by passing outputs between commands.
    - NEVER run code directly via interpreter commands; MUST save code to a file using the `file` tool before execution.
    - Set a short `timeout` (such as 5s) for commands that don't return (like starting web servers) to avoid meaningless waiting time.
    - Use `wait` action when a command needs additional time to complete and return.
    - Only use `wait` after `exec`, and determine whether to wait based on the result of `exec`.
    - DO NOT use `wait` for long-running daemon processes.
    - When using `send`, add a newline character (\\n) at the end of the `input` parameter to simulate pressing Enter.
    - For keys other than Enter, use ANSI escape sequences to simulate them (e.g. `\\x1b[B` for arrow down) when using `send`.
    - For non-key strings in `input`, DO NOT perform any escaping; send the raw string directly.
    - Use non-interactive `bc` command for simple calculations, Python for complex math; NEVER calculate mentally.
    - Use `uptime` command when users explicitly request sandbox status check or wake-up.
    </instructions>

    <recommended_usage>
    - Use `view` to check shell session history and latest status.
    - Use `exec` to install packages or dependencies.
    - Use `exec` to copy, move, or delete files.
    - Use `exec` to check the status or explicitly wake up the sandbox.
    - Use `wait` to wait for the completion of long-running commands.
    - Use `send` to interact with processes that require user input.
    - Use `kill` to stop background processes that are no longer needed.
    - Use `kill` to clean up dead or unresponsive processes.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _SHELL_ALIASES)

    effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    if effective_timeout <= 0:
        return error_result(
            f"Invalid timeout value: {effective_timeout}",
            error="InvalidParameter",
            hint="Timeout must be a positive number of seconds. Omit the parameter to use the default.",
        )

    if action == "exec":
        if not command:
            return error_result(
                "Missing required parameter: command",
                error="MissingParameter",
                hint="Provide the 'command' parameter for the exec action.",
            )
        return alias_hint(await _exec_shell(command, False, effective_timeout, session), _alias, action)

    elif action == "view":
        return alias_hint(await _view_sessions(), _alias, action)

    elif action == "wait":
        if not session:
            return error_result(
                "Missing required parameter: session",
                error="MissingParameter",
                hint="Provide the 'session' parameter to identify which background process to wait on.",
            )
        return alias_hint(await _wait_session(session, effective_timeout), _alias, action)

    elif action == "send":
        if not session:
            return error_result(
                "Missing required parameter: session",
                error="MissingParameter",
                hint="Provide the 'session' parameter to identify which background process to send input to.",
            )
        if not input:
            return error_result(
                "Missing required parameter: input",
                error="MissingParameter",
                hint="Provide the 'input' parameter with the text to send to the session.",
            )
        return alias_hint(await _send_to_session(session, input, False), _alias, action)

    elif action == "kill":
        if not session:
            return error_result(
                "Missing required parameter: session",
                error="MissingParameter",
                hint="Provide the 'session' parameter to identify which background process to terminate.",
            )
        return alias_hint(await _kill_session(session), _alias, action)

    return error_result(
        f"Unknown action: {action}",
        error="InvalidAction",
        hint="Use one of: exec, view, wait, send, kill",
    )


CODE_TOOLS = [shell_tool]
