"""Custom exception hierarchy for agent and sandbox proxy errors."""


class AgentError(Exception):
    """This is the default error of an agent based function"""

    pass


class AgentDoesNotExist(AgentError):
    """Agent does not exist"""

    pass


# Backward compatibility alias
AgentDoesNotExists = AgentDoesNotExist


class AgentLimitExceeded(AgentError):
    """Agent limit exceeded"""

    pass


class ConversationBusy(AgentError):
    """Agent conversation busy"""

    pass


# =============================================================================
# STRUCTURED PROXY ERRORS
# =============================================================================


class ProxyError(AgentError):
    """Base proxy error with status_code, error_type, retry_after."""

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        error_type: str = "proxy_error",
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.retry_after = retry_after


class SandboxUnreachable(ProxyError):
    """Connect timeout, DNS failure."""

    def __init__(self, message: str = "Sandbox is unreachable"):
        super().__init__(message, status_code=502, error_type="sandbox_unreachable")


class SandboxRateLimited(ProxyError):
    """429 from sandbox."""

    def __init__(
        self,
        message: str = "Sandbox rate limited",
        retry_after: int | None = None,
    ):
        super().__init__(
            message,
            status_code=429,
            error_type="sandbox_rate_limited",
            retry_after=retry_after,
        )


class SandboxAuthFailed(ProxyError):
    """401/403 from sandbox."""

    def __init__(self, message: str = "Sandbox auth failed"):
        super().__init__(message, status_code=502, error_type="sandbox_auth_failed")


class SandboxServerError(ProxyError):
    """500+ from sandbox."""

    def __init__(self, message: str = "Sandbox server error"):
        super().__init__(message, status_code=502, error_type="sandbox_server_error")


class SandboxCreateFailed(AgentError):
    """Raised when sandbox creation fails after all fallback attempts."""

    pass


class SandboxNotReady(AgentError):
    """Raised when the agent server inside the sandbox fails health checks."""

    pass
