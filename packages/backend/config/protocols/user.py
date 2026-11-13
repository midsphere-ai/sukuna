"""Concrete user-profile service used for authentication lookups.

Implements the ``UserProfileService`` protocol by resolving Django REST
Framework token keys to ``User`` model instances, with both sync and
async variants.
"""

import logging
from typing import Optional

from asgiref.sync import sync_to_async
from dj_rest_auth.models import get_token_model
from django.core.handlers.wsgi import WSGIRequest

from apps.users.models import User


class WorkspaceUserService:
    """Adapter that resolves auth tokens to User objects.

    Used by BaseService and other infrastructure code that needs to
    look up the current user from a request or token key.
    """

    def get_profile_from_request(self, request: WSGIRequest) -> Optional[User]:
        """Extract profile from request using token lookup."""
        try:
            token = self._extract_token_from_request(request)
            if not token:
                return None
            return self.get_logged_in_user(token)
        except (ValueError, PermissionError) as e:
            logging.debug(f"Failed to get profile from request: {e}")
            return None
        except Exception as e:
            logging.error(
                f"Unexpected error in get_profile_from_request: {e}", exc_info=True
            )
            return None

    def get_logged_in_user(self, token: str) -> Optional[User]:
        """Resolve a token key to its User."""
        try:
            if not token:
                return None
            Token = get_token_model()
            return Token.objects.select_related("user").get(key=token).user
        except (ValueError, PermissionError) as e:
            logging.debug(f"Auth token invalid: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error in get_logged_in_user: {e}", exc_info=True)
            return None

    def _extract_token_from_request(self, request: WSGIRequest) -> Optional[str]:
        """Extract authentication token from request."""
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        # Check for session-based auth
        if hasattr(request, "user") and request.user.is_authenticated:
            return getattr(request.user, "auth_token", None)

        return None

    async def aget_logged_in_user(self, token: str) -> Optional[User]:
        """Async version: resolve a token key to its User."""
        try:
            if not token:
                return None
            Token = get_token_model()
            token_instance = await Token.objects.aget(key=token)
            user = await sync_to_async(lambda: token_instance.user)()
            return user
        except (ValueError, PermissionError) as e:
            logging.debug(f"Auth token invalid: {e}")
            return None
        except Exception as e:
            logging.error(
                f"Unexpected error in aget_logged_in_user: {e}", exc_info=True
            )
            return None

    async def aget_profile_from_request(self, request) -> Optional[User]:
        """Async version: Extract profile from request using token lookup."""
        try:
            token = self._extract_token_from_request(request)
            if not token:
                return None
            return await self.aget_logged_in_user(token)
        except (ValueError, PermissionError) as e:
            logging.debug(f"Failed to get profile from request: {e}")
            return None
        except Exception as e:
            logging.error(
                f"Unexpected error in aget_profile_from_request: {e}", exc_info=True
            )
            return None
