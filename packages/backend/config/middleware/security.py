"""Security-related Django middleware.

Contains middleware classes that add HTTP security headers
(e.g. Content-Security-Policy) to responses.
"""

from django.conf import settings


class ContentSecurityPolicyMiddleware:
    """Middleware to add Content-Security-Policy header for API responses."""

    def __init__(self, get_response):
        """Initialise the middleware.

        Args:
            get_response: The next middleware or view in the chain.
        """
        self.get_response = get_response

    def __call__(self, request):
        """Process the request and add a Content-Security-Policy header if absent.

        The admin interface (Unfold) requires 'unsafe-eval' for Alpine.js and
        external style sources for Google Fonts, so it gets a relaxed policy.

        Args:
            request: The incoming HTTP request.

        Returns:
            The HTTP response with the CSP header applied.
        """
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            if request.path.startswith(f"/{settings.ADMIN_URL}"):
                response["Content-Security-Policy"] = (
                    "default-src 'self'; "
                    "script-src 'self' 'unsafe-eval'; "
                    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                    "font-src 'self' https://fonts.gstatic.com; "
                    "img-src 'self' data:"
                )
            else:
                response["Content-Security-Policy"] = "default-src 'self'"
        return response
