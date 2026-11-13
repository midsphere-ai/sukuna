"""Celery application configuration for the Sukuna platform.

Configures the Celery worker, loads secrets from OpenBao/Vault,
auto-discovers tasks from installed Django apps, and wires up
Django's logging configuration for the worker process.
"""

import os

from celery import Celery
from celery.signals import setup_logging

from config.openbao import load_env_from_vault

# set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

load_env_from_vault()

app = Celery("sukuna")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")


## IMPORTANT: Do not modify this.
## This is required for the tasks not to "forget"
app.conf.worker_concurrency = 1
app.conf.worker_prefetch_multiplier = 1
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True  # Requeue if worker dies


@setup_logging.connect
def config_loggers(*args, **kwargs):
    """Apply Django's LOGGING configuration to the Celery worker process."""
    from logging.config import dictConfig  # noqa: PLC0415

    from django.conf import settings  # noqa: PLC0415

    dictConfig(settings.LOGGING)


# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
