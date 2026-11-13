"""Component-level versioning for the Midsphere harness and adjacents.

Each component module defines a ``__version__`` string constant.
This module assembles them into a :class:`HarnessManifest` frozen dataclass
that is stored on ``SandboxRun.metadata["harness_manifest"]`` at run
creation time.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger("agent_server")

# Tool modules keyed by logical name → Python module path.
# These are importable from the sandbox tools directory.
_TOOL_MODULES: dict[str, str] = {
    "artifact": "artifact",
    "browse": "browse",
    "cli_tools": "cli_tools",
    "expose_port": "expose_port",
    "file_edit": "file.edit",
    "file_io": "file.io",
    "file_ops": "file.ops",
    "find": "find",
    "git_ops": "git_ops",
    "message": "message",
    "mobile": "mobile",
    "perception": "perception.tool",
    "plan": "plan",
    "reasoning": "reasoning",
    "search": "search",
    "shell": "shell",
    "skill": "skill",
    "web": "web",
}


def _get_agent_version() -> str:
    """Read the sukuna-pro package version from importlib metadata."""
    try:
        from importlib.metadata import version

        return version("sukuna-pro")
    except Exception:
        return "0.0.0"


@dataclass(frozen=True, slots=True)
class HarnessManifest:
    """Immutable snapshot of all component versions for a single run."""

    agent_version: str  # sukuna-pro package version
    harness: str
    prompts: str
    context_engine: str
    guardrails: str
    tool_surface: str
    knowledge_mgr: str
    tools: dict[str, str]  # {tool_module_name: version}
    tools_hash: str  # SHA-256 prefix of sorted tools dict
    skills: dict[str, str]  # {skill_name: content_hash}
    skills_hash: str  # SHA-256 prefix of sorted skills dict
    exo_commit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HarnessManifest:
        return cls(**d)


def _compute_hash(versions: dict[str, str]) -> str:
    """Deterministic 12-char hash of a ``{name: version}`` dict."""
    canonical = "|".join(f"{k}={v}" for k, v in sorted(versions.items()))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _get_exo_commit() -> str:
    """Read the pinned exo commit hash from pyproject.toml."""
    try:
        from pathlib import Path

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        for line in pyproject.read_text().splitlines():
            if "exo-core" in line and "rev" in line:
                start = line.index('rev = "') + 7
                end = line.index('"', start)
                return line[start:end]
    except Exception:
        pass
    return ""


def _collect_tool_versions() -> dict[str, str]:
    """Import each tool module and read its ``__version__``."""
    versions: dict[str, str] = {}
    for name, module_path in sorted(_TOOL_MODULES.items()):
        try:
            mod = importlib.import_module(module_path)
            versions[name] = getattr(mod, "__version__", "0.0.0")
        except Exception:
            versions[name] = "import_error"
    return versions


def build_manifest(skill_registry: Any | None = None) -> HarnessManifest:
    """Assemble the current HarnessManifest from all component ``__version__`` strings."""
    from agent_server.engine.context import __version__ as context_engine_v
    from agent_server.engine.harness import __version__ as harness_v
    from agent_server.engine.knowledge import __version__ as knowledge_mgr_v
    from agent_server.engine.prompts import __version__ as prompts_v
    from agent_server.infra.guards import __version__ as guardrails_v
    from agent_server.infra.registry import __version__ as tool_surface_v

    # Tool versions
    tool_versions = _collect_tool_versions()

    # Skill versions (content hash of usage body)
    skills_versions: dict[str, str] = {}
    if skill_registry is not None:
        skills = getattr(skill_registry, "skills", None)
        if skills:
            for skill in skills.values():
                content = getattr(skill, "usage", "") or ""
                skills_versions[skill.name] = hashlib.sha256(content.encode()).hexdigest()[:8]

    return HarnessManifest(
        agent_version=_get_agent_version(),
        harness=harness_v,
        prompts=prompts_v,
        context_engine=context_engine_v,
        guardrails=guardrails_v,
        tool_surface=tool_surface_v,
        knowledge_mgr=knowledge_mgr_v,
        tools=tool_versions,
        tools_hash=_compute_hash(tool_versions),
        skills=skills_versions,
        skills_hash=_compute_hash(skills_versions),
        exo_commit=_get_exo_commit(),
    )


def diff_manifests(a: HarnessManifest, b: HarnessManifest) -> dict[str, tuple[str, str]]:
    """Compare two manifests. Returns ``{component: (ver_a, ver_b)}`` for diffs only."""
    diffs: dict[str, tuple[str, str]] = {}
    for component in (
        "agent_version",
        "harness",
        "prompts",
        "context_engine",
        "guardrails",
        "tool_surface",
        "knowledge_mgr",
        "tools_hash",
        "skills_hash",
        "exo_commit",
    ):
        va = getattr(a, component)
        vb = getattr(b, component)
        if va != vb:
            diffs[component] = (str(va), str(vb))

    # Per-tool diffs
    all_tool_names = set(a.tools) | set(b.tools)
    for name in sorted(all_tool_names):
        ta = a.tools.get(name, "(absent)")
        tb = b.tools.get(name, "(absent)")
        if ta != tb:
            diffs[f"tool:{name}"] = (ta, tb)

    # Per-skill diffs
    all_skill_names = set(a.skills) | set(b.skills)
    for name in sorted(all_skill_names):
        sa = a.skills.get(name, "(absent)")
        sb = b.skills.get(name, "(absent)")
        if sa != sb:
            diffs[f"skill:{name}"] = (sa, sb)

    return diffs


def log_manifest(manifest: HarnessManifest, prefix: str = "Harness manifest") -> None:
    """Log the manifest at INFO level."""
    log.info(
        "%s: agent=%s harness=%s prompts=%s ctx=%s guards=%s tools=%s[%s] knowledge=%s skills=%s[%s] exo=%s",
        prefix,
        manifest.agent_version,
        manifest.harness,
        manifest.prompts,
        manifest.context_engine,
        manifest.guardrails,
        manifest.tool_surface,
        manifest.tools_hash,
        manifest.knowledge_mgr,
        manifest.skills_hash,
        len(manifest.skills),
        manifest.exo_commit,
    )
