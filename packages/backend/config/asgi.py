"""
ASGI config for sukuna project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/dev/howto/deployment/asgi/

"""

import os
import sys
from pathlib import Path

import django
from django.core.asgi import get_asgi_application

from config.openbao import load_env_from_vault

load_env_from_vault()
BASE_DIR = Path(__file__).resolve(strict=True).parent.parent

sys.path.append(str(BASE_DIR / "sukuna"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

application = get_asgi_application()

# In DEBUG mode, serve static files through ASGI (uvicorn doesn't serve them)
from django.conf import settings  # noqa: E402

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

    application = ASGIStaticFilesHandler(application)
