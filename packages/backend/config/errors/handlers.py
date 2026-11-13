"""
Standardised API Error Responses
=================================

Every NinjaAPI instance MUST register error handlers via ``register_error_handlers(api)``.

**Standard error envelope** returned by all endpoints on failure::

    {
        "error":      "Human-readable message",
        "error_code": "MACHINE_READABLE_CODE",
        "detail":     null | { ... },       # optional extra context
        "status":     400                    # mirrors HTTP status
    }

Special case — ``ProxyError`` subclasses (agents app) add ``retry_after``
to *detail* and set the ``Retry-After`` HTTP header when present.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import NinjaAPI, Schema

from config.errors.common import (
    FileProcessingError,
    InvalidInputError,
    NotFoundError,
    UnauthorizedAccessError,
)

# ---------------------------------------------------------------------------
# Schema (for OpenAPI docs — can be used as ``response={400: ErrorResponseSchema}``)
# ---------------------------------------------------------------------------


class ErrorResponseSchema(Schema):
    """Standard error response body."""

    error: str
    error_code: str
    detail: Optional[Any] = None
    status: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Maps exception *classes* → (http_status, error_code).
# Subclass maps are checked with isinstance() so order matters (most-specific first).
_COMMON_ERROR_MAP: list[tuple[Type[Exception], int, str]] = [
    (InvalidInputError, 400, "INVALID_INPUT"),
    (UnauthorizedAccessError, 401, "UNAUTHORIZED"),
    (NotFoundError, 404, "NOT_FOUND"),
    (FileProcessingError, 422, "FILE_PROCESSING_ERROR"),
]


def _error_code_from_class(exc: Exception) -> str:
    """Derive a SCREAMING_SNAKE error code from the exception class name."""
    name = type(exc).__name__
    # Convert CamelCase → SCREAMING_SNAKE
    import re

    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).upper()


def _build_json(
    exc: Exception,
    status: int,
    error_code: str,
    detail: Optional[Dict[str, Any]] = None,
) -> JsonResponse:
    body: Dict[str, Any] = {
        "error": str(exc),
        "error_code": error_code,
        "detail": detail,
        "status": status,
    }
    return JsonResponse(body, status=status)


# ---------------------------------------------------------------------------
# Per-app exception registries
# ---------------------------------------------------------------------------

# Each app can supply its own (ExceptionClass → status, error_code) tuples.
# These are checked *before* the common map so app-specific exceptions take
# priority over inherited base classes.


def _app_error_map() -> list[tuple[Type[Exception], int, str]]:
    """Lazily build the combined app-specific error map.

    Imports are deferred to avoid circular import issues at module level.
    """
    mapping: list[tuple[Type[Exception], int, str]] = []

    # -- agents ---------------------------------------------------------------
    try:
        from apps.agents.errors import (
            AgentDoesNotExist,
            AgentLimitExceeded,
            ConversationBusy,
            SandboxCreateFailed,
            SandboxNotReady,
        )

        mapping += [
            (AgentDoesNotExist, 404, "AGENT_NOT_FOUND"),
            (AgentLimitExceeded, 403, "AGENT_LIMIT_EXCEEDED"),
            (ConversationBusy, 409, "CONVERSATION_BUSY"),
            (SandboxCreateFailed, 502, "SANDBOX_CREATE_FAILED"),
            (SandboxNotReady, 502, "SANDBOX_NOT_READY"),
        ]
    except ImportError:
        pass

    # -- billing --------------------------------------------------------------
    try:
        from apps.billing.service import BillingException

        mapping.append((BillingException, 400, "BILLING_ERROR"))
    except ImportError:
        pass

    # -- storage (addons) -----------------------------------------------------
    try:
        from apps.storage.errors import (
            AddonAlreadyRegistered,
            AddonNotAuthorised,
            AlreadyAuthorised,
            AuthLinkAlreadyExists,
            AuthLinkNotExpired,
            NonExistentAddon,
            NoToolsFound,
            RegisterFailed,
            UnRegisterFailed,
        )

        mapping += [
            (NoToolsFound, 404, "NO_TOOLS_FOUND"),
            (NonExistentAddon, 404, "ADDON_NOT_FOUND"),
            (AddonAlreadyRegistered, 409, "ADDON_ALREADY_REGISTERED"),
            (AuthLinkAlreadyExists, 409, "AUTH_LINK_ALREADY_EXISTS"),
            (AlreadyAuthorised, 409, "ALREADY_AUTHORISED"),
            (AuthLinkNotExpired, 409, "AUTH_LINK_NOT_EXPIRED"),
            (AddonNotAuthorised, 401, "ADDON_NOT_AUTHORISED"),
            (RegisterFailed, 500, "REGISTER_FAILED"),
            (UnRegisterFailed, 500, "UNREGISTER_FAILED"),
        ]
    except ImportError:
        pass

    # -- storage (memory) -----------------------------------------------------
    try:
        from apps.storage.memory import ConversationNotFoundError

        mapping.append((ConversationNotFoundError, 404, "CONVERSATION_NOT_FOUND"))
    except ImportError:
        pass

    # -- spaces ---------------------------------------------------------------
    try:
        from apps.spaces.errors import (
            CreateProjectFailedError,
            ProjectObjectNotFoundError,
            ProjectsServiceError,
            UpdateProjectFailedError,
        )

        mapping += [
            (ProjectObjectNotFoundError, 404, "PROJECT_NOT_FOUND"),
            (CreateProjectFailedError, 400, "CREATE_PROJECT_FAILED"),
            (UpdateProjectFailedError, 400, "UPDATE_PROJECT_FAILED"),
            (ProjectsServiceError, 404, "PROJECTS_ERROR"),
        ]
    except ImportError:
        pass

    # -- workspace ------------------------------------------------------------
    try:
        from apps.workspace.errors import (
            UserAlreadyExistsError,
            UserDoesNotExistError,
            WorkspaceException,
        )

        mapping += [
            (UserAlreadyExistsError, 409, "USER_ALREADY_EXISTS"),
            (UserDoesNotExistError, 404, "USER_NOT_FOUND"),
            (WorkspaceException, 500, "WORKSPACE_ERROR"),
        ]
    except ImportError:
        pass

    # -- enterprise gate ------------------------------------------------------
    try:
        from apps.workspace.enterprise import EnterpriseDisabledError

        mapping.append((EnterpriseDisabledError, 403, "ENTERPRISE_FEATURES_DISABLED"))
    except ImportError:
        pass

    return mapping


_cached_app_map: list[tuple[Type[Exception], int, str]] | None = None


def _get_full_error_map() -> list[tuple[Type[Exception], int, str]]:
    global _cached_app_map
    if _cached_app_map is None:
        _cached_app_map = _app_error_map() + _COMMON_ERROR_MAP
    return _cached_app_map


# ---------------------------------------------------------------------------
# Core handler
# ---------------------------------------------------------------------------


def standard_exception_handler(
    request: HttpRequest, exc: Exception | type[Exception]
) -> HttpResponse:
    """Convert any registered exception into a standard JSON error response.

    This is the single handler registered on every NinjaAPI instance.
    """
    # Django Ninja types exc as Exception | type[Exception]; in practice it's
    # always an instance.  Narrow the type for downstream helpers.
    if not isinstance(exc, Exception):
        exc = Exception(str(exc))

    # 1) ProxyError — structured errors with extra metadata
    try:
        from apps.agents.errors import ProxyError

        if isinstance(exc, ProxyError):
            detail: Dict[str, Any] = {"error_type": exc.error_type}
            if exc.retry_after is not None:
                detail["retry_after"] = exc.retry_after
            response = _build_json(
                exc,
                status=exc.status_code,
                error_code=exc.error_type.upper(),
                detail=detail,
            )
            if exc.retry_after is not None:
                response["Retry-After"] = str(exc.retry_after)
            return response
    except ImportError:
        pass

    # 2) Walk the error map (most-specific first via isinstance)
    for exc_cls, status, code in _get_full_error_map():
        if isinstance(exc, exc_cls):
            return _build_json(exc, status=status, error_code=code)

    # 3) Fallback — unknown exception
    return _build_json(exc, status=500, error_code=_error_code_from_class(exc))


# ---------------------------------------------------------------------------
# Public API — call once per NinjaAPI instance at module level
# ---------------------------------------------------------------------------

# All base exception classes that should be caught.
_BASE_EXCEPTION_CLASSES: list[Type[Exception]] | None = None


def _get_base_exception_classes() -> list[Type[Exception]]:
    """Return the list of base exception classes to register handlers for."""
    global _BASE_EXCEPTION_CLASSES
    if _BASE_EXCEPTION_CLASSES is not None:
        return _BASE_EXCEPTION_CLASSES

    classes: list[Type[Exception]] = [
        # Common
        InvalidInputError,
        UnauthorizedAccessError,
        NotFoundError,
        FileProcessingError,
    ]

    # App-specific base classes (lazy imports to avoid circular deps)
    _optional_imports: list[tuple[str, str]] = [
        ("apps.agents.errors", "AgentError"),
        ("apps.billing.service", "BillingException"),
        ("apps.storage.errors", "AddonError"),
        ("apps.storage.memory", "MemoryServiceError"),
        ("apps.spaces.errors", "ProjectsServiceError"),
        ("apps.workspace.errors", "WorkspaceException"),
        ("apps.workspace.enterprise", "EnterpriseDisabledError"),
    ]
    for module_path, class_name in _optional_imports:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            classes.append(getattr(mod, class_name))
        except (ImportError, AttributeError):
            pass

    _BASE_EXCEPTION_CLASSES = classes
    return _BASE_EXCEPTION_CLASSES


def register_error_handlers(api_instance: NinjaAPI) -> None:
    """Register the standard exception handler on a NinjaAPI instance.

    Call this once for every ``NinjaAPI(...)`` in the project::

        from config.errors.handlers import register_error_handlers

        my_api = NinjaAPI(...)
        register_error_handlers(my_api)
    """
    for exc_cls in _get_base_exception_classes():
        api_instance.add_exception_handler(exc_cls, standard_exception_handler)
