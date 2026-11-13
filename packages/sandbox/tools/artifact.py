"""
Artifact display tool.

Provides an ``artifact`` tool that lets the agent create rich displayable
content (HTML pages, markdown documents, SVGs, code snippets, mermaid
diagrams) which the frontend renders in the side panel.

The tool is stateless — it validates inputs, generates an ID, and returns
structured data.  The frontend consumes ``artifact_type``, ``content``,
``title``, and ``artifact_id`` from the tool result to render appropriately.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from exo import tool

__version__ = "0.1.0"


_ARTIFACT_ALIASES: dict[str, str] = {
    "new": "create",
    "make": "create",
    "generate": "create",
    "build": "create",
    "produce": "create",
    "render": "create",
    "edit": "update",
    "modify": "update",
    "change": "update",
    "revise": "update",
    "refresh": "update",
    "replace": "update",
}


@tool(name="artifact")
async def artifact_tool(
    action: Annotated[
        Literal["create", "update"],
        "The action to perform. Supported values: create, update.",
    ],
    artifact_type: Annotated[
        Literal["html", "markdown", "svg", "code", "mermaid", "pdf"],
        "The type of artifact content. Supported values: html, markdown, svg, code, mermaid, pdf.",
    ],
    content: Annotated[str, "The full content of the artifact."],
    title: Annotated[str, "A short human-readable title for the artifact."],
    artifact_id: Annotated[
        str | None,
        "ID of an existing artifact to update. Required for update action, omit for create.",
    ] = None,
    language: Annotated[
        str | None,
        "Programming language for code artifacts (e.g. python, javascript, typescript).",
    ] = None,
) -> dict:
    """Create or update a rich displayable artifact shown in the side panel.

    <instructions>
    - Use this tool to present interactive or formatted content to the user.
    - `html` type renders a complete HTML page in a sandboxed iframe. Include `<html>`, `<head>`, and `<body>` tags. External resources (CDN scripts/styles) are allowed.
    - `markdown` type renders with GitHub-Flavored Markdown. Supports headings, lists, tables, code blocks, and inline formatting.
    - `svg` type renders raw SVG markup. Provide the `<svg>...</svg>` content directly.
    - `code` type renders syntax-highlighted code. Set `language` to enable proper highlighting.
    - `mermaid` type renders diagrams using mermaid.js. Provide the raw mermaid syntax.
    - `pdf` type renders a PDF document inline. `content` must be a base64-encoded PDF byte string. Used primarily by the live document preview pipeline — agents typically do not emit pdf artifacts directly.
    - `create` action generates a new `artifact_id` that can be used for subsequent updates.
    - `update` action fully replaces the content of an existing artifact by `artifact_id`.
    - DO NOT write partial or truncated content; always output full artifact content.
    </instructions>

    <recommended_usage>
    - Use `create` with `html` for interactive pages, dashboards, or rich visualizations.
    - Use `create` with `markdown` for formatted documents, reports, or structured text.
    - Use `create` with `svg` for diagrams, charts, or vector graphics.
    - Use `create` with `code` for presenting syntax-highlighted code snippets.
    - Use `create` with `mermaid` for flowcharts, sequence diagrams, or architecture diagrams.
    - Use `update` to iteratively refine an artifact based on user feedback.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _ARTIFACT_ALIASES)

    if not content or not content.strip():
        return error_result(
            "'content' cannot be empty.",
            hint="Provide the full artifact content.",
        )

    if not title or not title.strip():
        return error_result(
            "'title' cannot be empty.",
            hint="Provide a short descriptive title for the artifact.",
        )

    if action == "create":
        new_id = uuid.uuid4().hex[:8]
        result = success_result(
            "Artifact created",
            artifact_id=new_id,
            artifact_type=artifact_type,
            title=title.strip(),
            content=content,
            language=language,
            version=1,
        )
        return alias_hint(result, _alias, action)

    if action == "update":
        if not artifact_id:
            return error_result(
                "'artifact_id' is required for the update action.",
                hint="Pass the artifact_id returned from a previous 'create' call.",
            )
        result = success_result(
            "Artifact updated",
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title.strip(),
            content=content,
            language=language,
            version=2,
        )
        return alias_hint(result, _alias, action)

    return error_result(f"Unknown action '{action}'.")


ARTIFACT_TOOLS = [artifact_tool]
