import logging

from django.core.cache import cache
from django.db import DatabaseError, InterfaceError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@never_cache
@require_safe
def health_check(request):
    checks = {"database": False, "cache": False}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            checks["database"] = cursor.fetchone() == (1,)
    except (DatabaseError, InterfaceError) as exc:
        logger.warning(
            "Warehouse health check failed: dependency=database error=%s",
            type(exc).__name__,
        )

    try:
        cache.get("health:probe")
        checks["cache"] = True
    except Exception as exc:
        logger.warning(
            "Warehouse health check failed: dependency=cache error=%s",
            type(exc).__name__,
        )

    healthy = all(checks.values())

    return JsonResponse(
        {
            "status": "ok" if healthy else "unavailable",
            "checks": checks,
        },
        status=200 if healthy else 503,
    )
