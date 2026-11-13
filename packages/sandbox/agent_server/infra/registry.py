"""Tool registry — tool group management, CLI tool catalog, and skill registry."""

from __future__ import annotations

import logging
import os
from pathlib import Path as FilePath

from exo.skills import DictToolResolver, SkillRegistry
from exo.tool import Tool

log = logging.getLogger("agent_server")

__version__ = "0.1.0"

# ── Toggle-to-group mapping ──────────────────────────────────────────────────
# Toggle map for native (in-context) tool groups only.
TOGGLE_GROUP_MAP: dict[str, str] = {
    "web_search": "search",
    "browser": "browse",
    "shell_commands": "code",
    "computer_use": "mobile_init",
}

# Toggle map for CLI-offloaded tool groups.
CLI_TOGGLE_GROUP_MAP: dict[str, str] = {
    "complex_reasoning": "reasoning",
}

# Native/gated tools that should remain direct schemas even when an agent
# runs with ``ptc=True``.
PTC_EXCLUDED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "file",
        "shell",
        "match",
        "schedule",
        "search",
        "skill",
        "browser",
        "web_init",
        "mobile_init",
        "expose",
        "artifact",
    }
)


class ToolRegistry:
    """Stores tools in named groups and resolves user toggle preferences."""

    def __init__(self) -> None:
        self._groups: dict[str, list[Tool]] = {}
        self._tool_gates: dict[str, list[Tool]] = {}  # trigger_name -> gated tools
        self._gate_group_map: dict[str, str] = {}  # trigger_name -> group_name
        self._one_shot_triggers: set[str] = set()  # triggers that should disappear after firing

    def register_group(self, name: str, tools: list[Tool]) -> None:
        self._groups[name] = tools

    def register_gate(
        self,
        trigger_name: str,
        gated_tools: list[Tool],
        group: str,
        *,
        one_shot: bool = False,
    ) -> None:
        """Register tools that become available after a trigger tool executes.

        If ``one_shot`` is True, the trigger tool itself is removed from the
        agent's toolbox after it fires — used for project scaffolders like
        ``web_init``/``mobile_init`` that would clobber files on re-run.
        """
        self._tool_gates[trigger_name] = gated_tools
        self._gate_group_map[trigger_name] = group
        if one_shot:
            self._one_shot_triggers.add(trigger_name)

    def is_one_shot_trigger(self, trigger_name: str) -> bool:
        """True if the trigger should be removed from subsequent workers after firing."""
        return trigger_name in self._one_shot_triggers

    def get_group(self, name: str) -> list[Tool]:
        return self._groups.get(name, [])

    def all_tools(self) -> list[Tool]:
        result: list[Tool] = []
        for tools in self._groups.values():
            result.extend(tools)
        return result

    def get_tools_for_toggles(self, toggles: dict[str, bool]) -> list[Tool]:
        gated_groups: dict[str, str] = {}
        for toggle_name, group_name in TOGGLE_GROUP_MAP.items():
            gated_groups[group_name] = toggle_name

        result: list[Tool] = []
        for group_name, tools in self._groups.items():
            toggle_name = gated_groups.get(group_name)
            if toggle_name is None or toggles.get(toggle_name, True):
                result.extend(tools)
        return result

    def get_tool_gates(self, active_tools: list[Tool] | None = None) -> dict[str, list[Tool]]:
        """Return tool_gate dict for Agent, filtered by active tool set.

        Only includes gates whose trigger tool is in ``active_tools``.
        If ``active_tools`` is None, returns all gates.
        """
        if active_tools is None:
            return dict(self._tool_gates)
        active_names = {t.name for t in active_tools}
        return {name: tools for name, tools in self._tool_gates.items() if name in active_names}


# ── Singleton registry ───────────────────────────────────────────────────────
registry = ToolRegistry()


# ── Per-conversation unlocked-gate store ─────────────────────────────────────
# Tracks which gate triggers (e.g. ``web_init``) have fired during a
# conversation so that every subsequent executor built for that conversation
# — whether in the same run or a later one — inherits the unlocked tools.
# Without this, each new executor is constructed with an empty
# ``Agent._unlocked_gates`` and would have to re-run the trigger.
#
# Scope is the conversation, not the run: a user continuing a project
# across multiple ``/runs`` requests still has the same tools available
# because the scaffolding (package.json, tsconfig, etc.) lives on disk.

_conversation_unlocked_gates: dict[str, set[str]] = {}


def get_unlocked_gates(conversation_id: str) -> set[str]:
    """Return a copy of the gate triggers already fired in this conversation."""
    if not conversation_id:
        return set()
    return set(_conversation_unlocked_gates.get(conversation_id, set()))


def mark_gates_unlocked(conversation_id: str, triggers: set[str]) -> None:
    """Record that the given gate triggers have fired in this conversation."""
    if not conversation_id or not triggers:
        return
    bucket = _conversation_unlocked_gates.setdefault(conversation_id, set())
    bucket.update(triggers)


def clear_unlocked_gates(conversation_id: str) -> None:
    """Forget unlocked gates for a conversation (e.g. when it is deleted)."""
    _conversation_unlocked_gates.pop(conversation_id, None)


def _mark_ptc_excluded(tools: list[Tool]) -> None:
    """Mark selected tools so Exo keeps them outside ``__exo_ptc__``."""
    for tool in tools:
        if getattr(tool, "name", "") in PTC_EXCLUDED_TOOL_NAMES:
            tool._ptc_exclude = True


def populate_registry() -> int:
    """Import all tool modules and register their tool groups.

    Native (in-context) tool groups are registered here.  CLI-offloaded
    tools (media, perception, reasoning) are discovered at runtime by
    ``exo tool`` via ``tools/cli_tools.py``.
    """
    # isort: off
    from artifact import ARTIFACT_TOOLS
    from browse import BROWSER_GATED_TOOLS, BROWSER_TOOL
    from file import FILE_TOOLS
    from find import FIND_TOOLS
    from git_ops import git_tool
    from mobile import mobile_init_tool, mobile_project_tool, mobile_server_tool
    from plan import PLAN_TOOLS
    from search import SEARCH_TOOLS
    from shell import CODE_TOOLS
    from skill import SKILL_TOOLS
    from web import web_init_tool, web_project_tool, web_server_tool, web_env_tool, web_db_tool
    # isort: on

    registry.register_group("artifact", ARTIFACT_TOOLS)
    registry.register_group("file", FILE_TOOLS)
    registry.register_group("code", CODE_TOOLS)
    registry.register_group("match", FIND_TOOLS)
    registry.register_group("plan", PLAN_TOOLS)
    registry.register_group("search", SEARCH_TOOLS)
    registry.register_group("skill", SKILL_TOOLS)
    registry.register_group("browse", [BROWSER_TOOL])
    registry.register_gate("browser", BROWSER_GATED_TOOLS, group="browse")

    # Init tools are always visible; remaining tools are gated behind them
    registry.register_group("web_init", [web_init_tool])
    registry.register_group("mobile_init", [mobile_init_tool])
    from expose_port import expose_port_tool  # noqa: C0415

    _mark_ptc_excluded(
        [
            *ARTIFACT_TOOLS,
            *FILE_TOOLS,
            *CODE_TOOLS,
            *FIND_TOOLS,
            *PLAN_TOOLS,
            *SEARCH_TOOLS,
            *SKILL_TOOLS,
            BROWSER_TOOL,
            *BROWSER_GATED_TOOLS,
            web_init_tool,
            web_project_tool,
            web_server_tool,
            web_env_tool,
            web_db_tool,
            mobile_init_tool,
            mobile_project_tool,
            mobile_server_tool,
            git_tool,
            expose_port_tool,
        ]
    )

    registry.register_gate(
        "web_init",
        [web_project_tool, web_server_tool, web_env_tool, web_db_tool, git_tool, expose_port_tool],
        group="web",
        one_shot=True,
    )
    registry.register_gate(
        "mobile_init",
        [mobile_project_tool, mobile_server_tool, git_tool, expose_port_tool],
        group="mobile",
        one_shot=True,
    )

    total = len(registry.all_tools())
    log.info("Tool registry populated: %d native tools in %d groups (+3 CLI-offloaded)", total, len(registry._groups))
    return total


# ── CLI-offloaded tool catalog ──────────────────────────────────────────────
# Concise descriptions for instruction injection (first-line summaries).

_CLI_TOOL_CATALOG: dict[str, str] = {
    "perception": "Analyze images, transcribe audio, compare visuals, extract text from media.",
    "reasoning": "Deep reasoning and validation for complex problems via secondary LLM.",
}

# PATH binaries — plain Unix commands on $PATH, invoked via the shell tool
# without `exo tool call`. Not toggle-gated. Arguments are positional.
_PATH_BINARY_CATALOG: dict[str, str] = {
    "exo-pptx-to-pdf": "Convert a PowerPoint file (.pptx / .ppt) to PDF.  Usage: exo-pptx-to-pdf INPUT [OUTPUT]",
    "exo-doc-to-pdf": "Convert a Word document (.docx / .doc / .odt / .rtf) to PDF.  Usage: exo-doc-to-pdf INPUT [OUTPUT]",
    "exo-xlsx-to-pdf": "Convert a spreadsheet (.xlsx / .xls / .ods) to PDF.  Usage: exo-xlsx-to-pdf INPUT [OUTPUT]",
    "exo-markdown-to-pdf": "Convert a Markdown file (.md) to PDF via styled HTML.  Usage: exo-markdown-to-pdf INPUT [OUTPUT]",
}


def build_cli_tool_catalog(tool_toggles: dict[str, bool] | None = None) -> str:
    """Build a markdown catalog of CLI-offloaded tools for agent instructions.

    Respects toggle gating — omits tools whose toggle is disabled.
    """
    disabled_tools: set[str] = set()
    if tool_toggles:
        for toggle_name, tool_name in CLI_TOGGLE_GROUP_MAP.items():
            if not tool_toggles.get(toggle_name, True):
                disabled_tools.add(tool_name)

    lines: list[str] = []
    for tool_name, desc in _CLI_TOOL_CATALOG.items():
        if tool_name in disabled_tools:
            continue
        lines.append(f"- **{tool_name}**: {desc}")

    if not lines and not _PATH_BINARY_CATALOG:
        return ""

    sections: list[str] = []

    if lines:
        sections.append(
            "\n\n## CLI Tools\n"
            "\n"
            "The following tools are available via the command line. "
            "Call them using the shell tool:\n"
            "\n"
            "```\n"
            'exo tool call <tool_name> -j \'{"action": "...", "arg": "value"}\'\n'
            "```\n"
            "\n"
            "To see a tool's full schema and available actions:\n"
            "```\n"
            "exo tool schema <tool_name>\n"
            "```\n"
            "\n" + "\n".join(lines) + "\n\n"
            "**Important:** Always use `-j` with a valid JSON object. "
            "Check `exo tool schema <name>` if unsure about parameters. "
            "For detailed usage examples, load the `cli-tools` skill: "
            "`skill get cli-tools`.\n"
        )

    if _PATH_BINARY_CATALOG:
        path_lines = [f"- **{name}**: {desc}" for name, desc in _PATH_BINARY_CATALOG.items()]
        sections.append(
            "\n## PATH Binaries\n"
            "\n"
            "The following are plain Unix commands on $PATH. Invoke them directly "
            "with the shell tool — do NOT use `exo tool call`:\n"
            "\n"
            "```\n"
            "exo-pptx-to-pdf deck.pptx        # writes deck.pdf next to the input\n"
            "exo-doc-to-pdf  brief.docx out/brief.pdf\n"
            "```\n"
            "\n" + "\n".join(path_lines) + "\n\n"
            "All three print the produced PDF path on stdout and exit non-zero on "
            "failure. Output defaults to the input path with a `.pdf` extension. "
            "See the `cli-tools` skill for full usage patterns.\n"
        )

    return "".join(sections)


# ── Skill registry (loaded once at startup) ──────────────────────────────────
_BUNDLED_SKILLS_DIR = str(FilePath(__file__).resolve().parent.parent.parent / "skills")


def _workspace_root() -> str:
    return (
        os.environ.get("PROJECT_DIR")
        or os.environ.get("WORKSPACE")
        or os.environ.get("SANDBOX_WORKSPACE_ROOT")
        or str(FilePath.home())
    )


def _resolve_user_skills_dir() -> str:
    """Resolve user skills directory, creating it if missing."""
    explicit = os.environ.get("AGENT_USER_SKILLS_DIR")
    target = explicit or os.path.join(_workspace_root(), "skills")
    os.makedirs(target, exist_ok=True)
    return target


_USER_SKILLS_DIR = _resolve_user_skills_dir()

skill_registry = SkillRegistry()
skill_registry.register_source(_BUNDLED_SKILLS_DIR)
skill_registry.register_source(_USER_SKILLS_DIR)

skill_tool_resolver: DictToolResolver | None = None


def populate_skill_registry() -> int:
    """Load skills and build the tool resolver.

    Must be called AFTER populate_registry().  Builds a resolver that maps
    tool names to tool instances for skill ``tool_list`` resolution.
    """
    global skill_tool_resolver

    from expose_port import expose_port_tool  # noqa: C0415
    from git_ops import git_tool  # noqa: C0415
    from mobile import MOBILE_TOOLS  # noqa: C0415
    from web import WEB_TOOLS  # noqa: C0415

    skills = skill_registry.load_all()
    all_tools: dict[str, list[Tool]] = {}
    for t in MOBILE_TOOLS + WEB_TOOLS + [git_tool, expose_port_tool]:
        all_tools[t.name] = [t]
    skill_tool_resolver = DictToolResolver(all_tools)
    log.info("Skill registry loaded: %d skills", len(skills))
    return len(skills)
