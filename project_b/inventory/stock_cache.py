import logging
from hashlib import sha256
from uuid import uuid4

from django.core.cache import cache
from django.utils.translation import get_language
from redis.exceptions import RedisError


logger = logging.getLogger(__name__)

CACHE_VERSION_KEY = "stock:version"
CACHE_TIMEOUT = 60


def get_stock_list_cache(request):
    try:
        version = cache.get_or_set(
            CACHE_VERSION_KEY,
            lambda: uuid4().hex,
            timeout=None,
        )
        source = f"{get_language()}:{request.build_absolute_uri()}"
        digest = sha256(source.encode("utf-8")).hexdigest()
        key = f"stock:list:v1:{version}:{digest}"

        return key, cache.get(key)
    except RedisError:
        logger.warning("Stock cache read failed", exc_info=True)
        return None, None


def set_stock_list_cache(key, data):
    if key is None:
        return

    try:
        cache.set(key, data, timeout=CACHE_TIMEOUT)
    except RedisError:
        logger.warning("Stock cache write failed", exc_info=True)


def invalidate_stock_cache():
    try:
        cache.set(CACHE_VERSION_KEY, uuid4().hex, timeout=None)
    except RedisError:
        logger.warning("Stock cache invalidation failed", exc_info=True)