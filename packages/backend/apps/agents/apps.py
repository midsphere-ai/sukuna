"""Django app configuration for the agents app."""

from django.apps import AppConfig


class AgentsConfig(AppConfig):
    """Configuration for the agents app, including startup sandbox pool seeding."""

    default_auto_field = "django.db.models.BigAutoField"
    label = "agents"
    name = "apps." + label

    def ready(self):
        """Initialize app: seed the sandbox pool."""
        self._seed_sandbox_pool()

    @staticmethod
    def _seed_sandbox_pool():
        """Fire replenish_sandbox_pool once at startup so the pool is warm immediately."""
        import logging

        from django.conf import settings
        from django.core.cache import cache

        if getattr(settings, "SANDBOX_POOL_SIZE", 0) <= 0:
            return

        seed_lock_key = "agents:pool:startup_seed_lock"
        if not cache.add(seed_lock_key, "1", timeout=120):
            return

        try:
            from apps.agents.tasks import replenish_sandbox_pool

            replenish_sandbox_pool.delay()
            logging.getLogger(__name__).info("[POOL] Dispatched initial pool replenish")
        except Exception as e:
            # Celery broker may not be up yet in some environments (e.g. tests)
            logging.getLogger(__name__).warning(
                f"[POOL] Could not dispatch initial replenish: {e}"
            )
            cache.delete(seed_lock_key)
