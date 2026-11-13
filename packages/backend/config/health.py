"""
Health check endpoints for load balancer and monitoring.

These endpoints are used by:
- DigitalOcean Load Balancers for health checking
- Kubernetes liveness/readiness probes
- External monitoring services
"""

import time

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET


@csrf_exempt
@require_GET
def health_check(request):
    """
    Main health check endpoint for Django/Uvicorn service.

    Used by the load balancer at: GET /health/
    Returns 200 OK if the service is healthy.
    """
    status_code = 200
    health_data = {
        "status": "healthy",
        "service": "django-main",
        "timestamp": time.time(),
    }

    # Database connectivity check
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_data["database"] = "connected"
    except Exception as e:
        health_data["database"] = "error"
        health_data["database_error"] = str(e)
        status_code = 503

    # Redis/cache connectivity check
    try:
        from django.core.cache import cache

        cache.set("health_check", "ok", timeout=10)
        if cache.get("health_check") == "ok":
            health_data["cache"] = "connected"
        else:
            health_data["cache"] = "error"
            status_code = 503
    except Exception as e:
        health_data["cache"] = "error"
        health_data["cache_error"] = str(e)
        status_code = 503

    if status_code == 503:
        health_data["status"] = "unhealthy"

    return JsonResponse(health_data, status=status_code)


@csrf_exempt
@require_GET
def liveness_check(request):
    """
    Simple liveness check - just confirms the process is running.

    Used by Kubernetes liveness probes.
    Returns 200 OK immediately without any external checks.
    """
    return JsonResponse(
        {
            "status": "alive",
            "timestamp": time.time(),
        },
        status=200,
    )


@csrf_exempt
@require_GET
def readiness_check(request):
    """
    Readiness check - confirms the service is ready to accept traffic.

    Used by Kubernetes readiness probes.
    Checks database and cache connectivity.
    """
    is_ready = True
    health_data = {
        "status": "ready",
        "timestamp": time.time(),
        "checks": {},
    }

    # Database check
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_data["checks"]["database"] = "ok"
    except Exception as e:
        health_data["checks"]["database"] = f"error: {str(e)}"
        is_ready = False

    # Cache check
    try:
        from django.core.cache import cache

        cache.set("readiness_check", "ok", timeout=10)
        if cache.get("readiness_check") == "ok":
            health_data["checks"]["cache"] = "ok"
        else:
            health_data["checks"]["cache"] = "error: cache read failed"
            is_ready = False
    except Exception as e:
        health_data["checks"]["cache"] = f"error: {str(e)}"
        is_ready = False

    if not is_ready:
        health_data["status"] = "not_ready"
        return JsonResponse(health_data, status=503)

    return JsonResponse(health_data, status=200)
