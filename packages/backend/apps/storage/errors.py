"""Custom exception classes for addon-related operations."""


class AddonError(Exception):
    """This is the default error of an addon based function"""

    pass


class NonExistentAddon(AddonError):
    """Addon does not exists in the database"""

    pass


class RegisterFailed(AddonError):
    """Addon has not been registered - this means it won't be displayed in tbe connectors"""

    pass


class AddonAlreadyRegistered(AddonError):
    """Addon has already been registered"""

    pass


class UnRegisterFailed(AddonError):
    """Addon has still registered for some reason"""

    pass


class AuthLinkAlreadyExists(AddonError):
    """Already an authentication link has been generated"""

    pass


class AlreadyAuthorised(AddonError):
    """No need to authenticate the addon as it is already registered"""

    pass


class AddonNotAuthorised(AddonError):
    """Addon has not been authorised yet but is registered."""

    pass


class NoToolsFound(AddonError):
    """When composio returns no tools"""


class AuthLinkNotExpired(AddonError):
    """Auth link cannot be regenerated because it hasn't expired or failed"""
