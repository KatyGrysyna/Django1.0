import logging

from django.core.cache import cache
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


@never_cache
@require_safe
def health(request):
    """Check database and cache connectivity for deployment monitoring."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

        cache.get("healthcheck")
    except (DatabaseError, RedisError):
        logger.exception("Health check failed")
        return JsonResponse({"status": "unavailable"}, status=503)

    return JsonResponse({"status": "ok"})
