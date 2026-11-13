"""CLI-offloaded tools — discovered by ``exo tool list`` / ``exo tool call``.

These tools are NOT loaded into the agent's native ``tools=`` parameter.
Instead the agent calls them via shell::

    exo tool call <tool_name> -j '{"action": "...", "arg": "value"}'

The ``EXO_TOOL_SOURCE`` env var points here so ``--from`` is not needed.
"""

from __future__ import annotations

__version__ = "0.1.0"

import sys
from pathlib import Path

# Ensure the tools/ directory is on sys.path so that internal imports
# within each tool module (e.g. ``from _lib.utils import ...``) resolve
# when this file is loaded by ``exo tool`` in a subprocess.
_tools_dir = str(Path(__file__).resolve().parent)
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from perception import perception_tool  # noqa: E402, F401
from reasoning import reasoning_tool  # noqa: E402, F401

# Conventional list for exo tool discovery.
# web, mobile, git, expose, and artifact tools are now native (in-context) — see registry.
tools = [
    perception_tool,
    reasoning_tool,
]
