"""Tolerant structured-output parser for chat-tuned LLMs.

Small / open / chat-tuned models often wrap their structured output in
markdown code fences (```` ```json ... ``` ````) or surround it with a
leading prose preamble even when the system prompt asks for raw JSON.
``BaseModel.model_validate_json`` chokes on those wrappers.

``try_parse_structured`` walks three progressively-looser strategies:

    1. Validate the text as-is.
    2. Strip a ```` ```json ... ``` ```` fence and validate the inner body.
    3. Extract the first balanced ``{...}`` block and validate that.

If every pass fails, raises :class:`StructuredOutputError` carrying the
original text and the underlying validation error so callers can log a
useful diagnostic without losing the raw payload.

Currently consumed only by the ralph-loop worker result parser
(``engine/run.py``). The executor and KM keep their existing parsers —
this is a focused fix for the ralph case where structured fields drive
loop control flow.
"""

from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

_T = TypeVar("_T", bound=BaseModel)


_CODE_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _balanced_object_candidates(text: str):
    """Yield each balanced ``{...}`` substring in *text*, in order.

    For each ``{`` in *text*, scans forward tracking brace depth (and
    ignoring braces that appear inside JSON string literals) until the
    matching ``}`` closes it.  If the scan reaches end-of-text without
    closing, that opener is abandoned and we try the next ``{``.

    This matters when a worker emits a malformed first attempt followed
    by a corrected retry — the recovery block is yielded even if the
    earlier opener never closed.
    """

    def _scan(start: int) -> int:
        depth = 0
        in_string = False
        escape = False
        for j in range(start, len(text)):
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return j
        return -1

    i = 0
    while True:
        i = text.find("{", i)
        if i == -1:
            return
        end = _scan(i)
        if end == -1:
            # This opener never closes; move past it and try the next.
            i += 1
            continue
        yield text[i : end + 1]
        i = end + 1


class StructuredOutputError(ValueError):
    """Raised when no parsing strategy could validate the text.

    Attributes:
        text: The original raw text that failed to parse.
        last_error: The validation/JSON error from the final attempted pass.
    """

    def __init__(self, message: str, *, text: str, last_error: Exception) -> None:
        super().__init__(message)
        self.text = text
        self.last_error = last_error


def try_parse_structured(text: str, model_cls: type[_T]) -> _T:
    """Validate *text* against *model_cls* with fence-strip / object-extract fallbacks.

    Order:
      1. ``model_cls.model_validate_json(text)`` — happy path.
      2. Inner body of the first ```` ```json ... ``` ```` fence.
      3. First balanced ``{...}`` substring.

    Raises:
        StructuredOutputError: If every strategy fails. ``.text`` carries
            the original input, ``.last_error`` the most recent failure.
    """
    if not text or not text.strip():
        raise StructuredOutputError(
            "Structured output is empty",
            text=text or "",
            last_error=ValueError("empty text"),
        )

    last_error: Exception | None = None

    # Pass 1 — straight validate.
    try:
        return model_cls.model_validate_json(text)
    except (ValidationError, ValueError) as exc:
        last_error = exc

    # Pass 2 — strip a ```json ... ``` fence.
    fence_match = _CODE_FENCE_RE.search(text)
    if fence_match is not None:
        inner = fence_match.group(1).strip()
        if inner:
            try:
                return model_cls.model_validate_json(inner)
            except (ValidationError, ValueError) as exc:
                last_error = exc

    # Pass 3 — try each balanced {...} block, in order. Workers often
    # emit a malformed first attempt followed by a corrected retry, so
    # we keep going until one validates instead of giving up on the first.
    for candidate in _balanced_object_candidates(text):
        try:
            return model_cls.model_validate_json(candidate)
        except (ValidationError, ValueError) as exc:
            last_error = exc

    raise StructuredOutputError(
        f"Could not parse {model_cls.__name__} from text",
        text=text,
        last_error=last_error or ValueError("no parsing strategy succeeded"),
    )
