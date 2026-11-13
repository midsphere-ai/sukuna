"""API route modules for the agent server.

This package splits the monolithic ``routes.py`` into focused modules:

- ``runs``     -- Run management + SSE streaming endpoints
- ``handlers`` -- HITL and MCP server management endpoints
- ``files``    -- File operations, health, conversations, and skills endpoints
- ``startup``  -- Server lifecycle (init_server, shutdown_server, _cli)

Importing this package registers all endpoint handlers on their respective
Django Ninja routers (side-effect of importing the sub-modules).
"""

from __future__ import annotations

# Import sub-modules so endpoint decorators execute and register on routers.
from agent_server.api.files import (  # noqa: F401
    _FILES_ROOT,
    _build_tree,
    _resolve_sandbox_path,
)
from agent_server.api.handlers import (  # noqa: F401
    AddMcpServerRequest,
    HitlResponseSchema,
)
from agent_server.api.integrations import (  # noqa: F401
    ClawConversationOut,
    ClawMessageRequest,
    ClawMessageResponse,
)
from agent_server.api.runs import (  # noqa: F401
    UPLOAD_DIR,
    BranchRequest,
    InjectMessageRequest,
    StartRunRequest,
    _fetch_events_after,
    _get_memory_store,
)
from agent_server.api.startup import (  # noqa: F401
    _cli,
    init_server,
    shutdown_server,
)
