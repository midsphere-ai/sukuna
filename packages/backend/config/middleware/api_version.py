"""API version header middleware.

Adds an ``X-API-Version`` response header to every request whose path
falls under the versioned public API prefix (``/api/v1/``).
"""

API_VERSION = "v1"
API_PREFIX = "/api/v1/"


class APIVersionHeaderMiddleware:
    """Inject ``X-API-Version: v1`` into responses for versioned API routes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(API_PREFIX):
            response["X-API-Version"] = API_VERSION
        return response
