# ruff: noqa
"""
Custom DigitalOcean Spaces storage backends.

DigitalOcean Spaces is S3-compatible, so we use django-storages S3Storage
with custom configuration for separate static and media buckets.
"""

from storages.backends.s3 import S3Storage


class DOStaticStorage(S3Storage):
    """
    Storage backend for static files on DigitalOcean Spaces.
    Uses a separate bucket specifically for static assets.

    Configuration is passed via STORAGES["staticfiles"]["OPTIONS"] in settings.
    """

    location = "static"
    default_acl = "public-read"


class DOMediaStorage(S3Storage):
    """
    Storage backend for media files on DigitalOcean Spaces.
    Uses a separate bucket specifically for user-uploaded media.

    Configuration is passed via STORAGES["default"]["OPTIONS"] in settings.
    """

    location = "media"
    file_overwrite = False
    default_acl = "public-read"
