"""Request ID middleware for request correlation in logs.

Generates a UUID for each incoming HTTP request and stores it in
thread-local storage so that log records can include it automatically
via the RequestIdFilter.
"""

import threading
import uuid

_local = threading.local()


def get_request_id() -> str | None:
    """Return the current request's ID, or None outside a request context."""
    return getattr(_local, "request_id", None)


def get_user_id() -> str | int | None:
    """Return the current request's authenticated user ID, or None."""
    return getattr(_local, "user_id", None)


class RequestIdMiddleware:
    """Generates a unique request_id per request and exposes it in logs and response headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Accept upstream request ID (e.g. from load balancer) or generate one
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        _local.request_id = request_id
        _local.user_id = None

        # Attach user_id if authenticated
        if hasattr(request, "user") and request.user.is_authenticated:
            _local.user_id = request.user.pk

        request.request_id = request_id

        response = self.get_response(request)
        response["X-Request-Id"] = request_id

        # Clean up thread-local
        _local.request_id = None
        _local.user_id = None

        return response
