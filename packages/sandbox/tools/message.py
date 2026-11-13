"""Message tool — unified agent-to-user communication with HITL support.

Replaces both ``HumanInputTool`` and ``submit_attachments``.  The ``ask``
action triggers the same HITL flow (blocks until the user responds via HTTP).
The ``info`` and ``result`` actions are non-blocking.

This tool is NOT registered in the tool registry — it is constructed per-run
in ``server.py`` with the run's ``HTTPHumanInputHandler``.
"""

from __future__ import annotations

__version__ = "0.1.0"

import asyncio
import logging
import os
import traceback
from typing import Any

from _lib.utils import alias_hint, resolve_alias
from exo.human import HumanInputHandler
from exo.tool import Tool

logger = logging.getLogger(__name__)


_MESSAGE_ALIASES: dict[str, str] = {
    "notify": "info",
    "tell": "info",
    "inform": "info",
    "status": "info",
    "update": "info",
    "note": "info",
    "log": "info",
    "report": "info",
    "say": "info",
    "send": "info",
    "alert": "info",
    "question": "ask",
    "prompt": "ask",
    "query": "ask",
    "request": "ask",
    "inquire": "ask",
    "done": "result",
    "complete": "result",
    "finish": "result",
    "final": "result",
    "answer": "result",
    "respond": "result",
    "reply": "result",
    "deliver": "result",
    "submit": "result",
    "return": "result",
    "output": "result",
    "end": "result",
    "close": "result",
    "conclude": "result",
}


class MessageTool(Tool):
    """Primary interaction tool for agents with user"""

    name = "message"
    description = """Send messages to interact with the user.
    
    <instructions>
    - MUST use this tool for any communication with users instead of direct responses.
    - Users may send new messages at any time, even during ongoing tasks.
    - MUST respond immediately to new user messages before taking any other actions.
    - For new tasks, the first reply MUST be a brief acknowledgment without providing solutions.
    - NEVER provide direct answers without proper reasoning or prior analysis.
    - Actively use `info` type to provide progress updates, as no reply is needed from users.
    - Use `ask` type only when necessary to avoid blocking the task or disrupting the user.
    - MUST use `result` type to present final results and deliverables to the user at the end of the task.
    - The task will be marked as ended after a `result` type message is sent, users may ask follow-up questions to continue.
    - Use `result` type to respond if the user's message only requires a reply without additional actions (e.g., simple chat or follow-up questions).
    - When user explicitly requests to end the task, MUST immediately use `result` type to acknowledge and end the task.
    - MUST ensure the task plan has reached the final phase and is fully completed before using `result` type, unless the user explicitly requests to stop.
    - MUST attach all relevant files in `attachments`, as users may not have access to the sandbox filesystem.
    - NEVER deliver intermediate notes as the only result; MUST prepare information-rich but readable final versions.
    - In addition to final result files, also attach key supporting files such as images, raw data, or visualizations.
    - When delivering key files (e.g., reports), MUST keep message `text` concise and guide the user to view the attachments directly.
    - DO NOT repeatedly send `info` messages when waiting for necessary information or files from the user; use `ask` type instead.
    - MUST use `ask` type with `confirm_browser_operation` in `suggested_action` before sensitive browser operations (e.g., posting content, completing payment).
    - Use `ask` type with `take_over_browser` in `suggested_action` when user takeover is required (e.g., browser login, providing personal information in browser).
    - MUST ensure the corresponding webpage is already opened before suggesting user takeover.
    - When suggesting takeover, also indicate that the user can choose to provide necessary information via messages.
    - Use `ask` type with `upgrade_to_unlock_feature` in `suggested_action` when the user needs to upgrade subscription to unlock a feature.
    - When suggesting upgrade, MUST also provide alternative options if available, such as using a different tool or approach.
    - DO NOT send multiple consecutive messages when the user has not replied; if a user response is required, MUST use `ask` type.
    </instructions>

    <recommended_usage>
    - Use `info` to acknowledge initial user messages and confirm task start.
    - Use `info` to notify user of progress checkpoints or decisions made.
    - Use `ask` to disambiguate unclear goals, confirm intent, or get sensitive input.
    - Use `ask` to request help from the user when the task fails or stalls.
    - Use `ask` with `confirm_browser_operation` before posting, paying, or submitting forms.
    - Use `ask` with `take_over_browser` only when a browser login, CAPTCHA, or manual step in browser is required.
    - Use `ask` with `upgrade_to_unlock_feature` when required functionality is only available after subscription upgrade.
    - Use `result` to deliver final answer and attachments at the end of the task.
    - Use `result` to reply simple chat messages or follow-up questions without requiring further actions.
    - Use `result` to end the task when the user explicitly requests it.
    </recommended_usage>
    
    """
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "description": (
                    "The message type. "
                    "'info' sends a non-blocking status update. "
                    "'ask' blocks execution and waits for the user to reply (HITL). "
                    "'result' delivers output with optional file attachments."
                ),
            },
            "text": {
                "type": "string",
                "description": "The message or question text shown to the user.",
            },
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of absolute file paths to attach (result type only). "
                    "Files must exist on disk. Missing files are reported but "
                    "do not cause failure if at least one valid file is provided."
                ),
            },
            "suggested_action": {
                "type": "string",
                "description": (
                    "Optional hint to the UI about the expected user action: "
                    "'none', 'confirm_browser_operation', 'take_over_browser', "
                    "or 'upgrade_to_unlock_feature'."
                ),
            },
        },
        "required": ["type", "text"],
    }

    def __init__(
        self,
        *,
        handler: HumanInputHandler | None = None,
        timeout: float | None = None,
    ) -> None:
        self._handler = handler
        self._timeout = timeout

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Dispatch to info, ask, or result handler.

        Args:
            **kwargs: Tool arguments populated by the LLM.

        Returns:
            Structured result dict with success/message/metadata.
        """
        try:
            msg_type = kwargs.get("type", "info")
            msg_type, _alias = resolve_alias(msg_type, _MESSAGE_ALIASES)
            text = kwargs.get("text", "")

            if msg_type not in ("info", "ask", "result"):
                return {
                    "success": False,
                    "message": f"Unknown message type '{msg_type}'.",
                    "hint": "Valid types: 'info' (non-blocking update), 'ask' (blocks for user reply), 'result' (deliver files).",
                }

            if msg_type == "ask" and not text:
                return {
                    "success": False,
                    "message": "Cannot ask the user an empty question.",
                    "hint": "Provide a non-empty text parameter with the question to ask the user.",
                }

            if msg_type == "ask":
                return alias_hint(await self._handle_ask(text), _alias, msg_type, param_name="type")
            elif msg_type == "result":
                attachments = kwargs.get("attachments") or []
                return alias_hint(self._handle_result(text, attachments), _alias, msg_type, param_name="type")
            else:
                return alias_hint(self._handle_info(text), _alias, msg_type, param_name="type")
        except Exception as e:
            logger.exception("message_tool execute error: %s", e)
            return {
                "success": False,
                "message": f"Message operation failed: {e}",
                "hint": "An unexpected error occurred.",
            }

    # ── Action handlers ─────────────────────────────────────────────────────

    @staticmethod
    def _handle_info(text: str) -> dict[str, Any]:
        """Non-blocking informational message."""
        return {"success": True, "message": text}

    async def _handle_ask(self, text: str) -> dict[str, Any]:
        """Block until the user responds via HITL."""
        if self._handler is None:
            return {
                "success": False,
                "message": "No HITL handler configured — cannot ask the user.",
                "hint": "The MessageTool was not initialized with a HumanInputHandler. Use type='info' for non-blocking messages instead, or ensure the agent run was created with HITL support.",
            }
        try:
            if self._timeout is not None:
                response = await asyncio.wait_for(self._handler.get_input(text), timeout=self._timeout)
            else:
                response = await self._handler.get_input(text)
            return {
                "success": True,
                "message": "User responded",
                "metadata": {"response": response},
            }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "message": f"User did not respond within {self._timeout}s.",
                "hint": "The user did not reply in time. Retry with type='ask' to re-prompt, or proceed with a default action and notify the user with type='info'.",
            }
        except Exception as e:
            logger.exception("HITL ask failed")
            return {
                "success": False,
                "message": f"Error waiting for user input: {e}",
                "hint": "The HITL handler encountered an error. Retry the ask, or fall back to type='info' to send a non-blocking update and continue without user input.",
            }

    @staticmethod
    def _handle_result(text: str, attachments: list[str]) -> dict[str, Any]:
        """Deliver results with optional file attachments."""
        try:
            validated_files: list[str] = []
            missing_files: list[str] = []

            for file_path in attachments:
                full_path = os.path.expanduser(file_path)
                if os.path.exists(full_path):
                    validated_files.append(full_path)
                else:
                    missing_files.append(file_path)

            if attachments and not validated_files:
                return {
                    "success": False,
                    "message": "No valid files found to attach",
                    "hint": f"None of the provided file paths exist: {missing_files}. Use absolute paths and verify files were created before attaching.",
                    "metadata": {"missing_files": missing_files},
                }

            metadata: dict[str, Any] = {
                "files": validated_files,
                "file_count": len(validated_files),
            }
            if missing_files:
                metadata["missing_files"] = missing_files

            return {
                "success": True,
                "message": text or "Result delivered",
                "metadata": metadata,
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Error delivering result: {e}",
                "metadata": {"error": str(e), "traceback": traceback.format_exc()},
            }
