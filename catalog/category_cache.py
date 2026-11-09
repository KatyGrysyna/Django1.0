from functools import wraps
from uuid import uuid4

from django.core.cache import cache
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import cache_page


VERSION_KEY = 'catalog:category-list:version'


def invalidate_category_list_cache():
    """Make all cached versions of the category list obsolete."""
    cache.delete(VERSION_KEY)


def cache_category_list(view):
    """Cache the public category list for the current catalogue version."""
    @wraps(view)
    async def wrapped(request, *args, **kwargs):
        version = await cache.aget_or_set(
            VERSION_KEY,
            lambda: uuid4().hex,
            timeout=None,
        )

        cached_view = cache_page(
            300,
            key_prefix=f'public_categories.{version}',
        )(view)

        response = await cached_view(request, *args, **kwargs)
        patch_cache_control(response, max_age=0, must_revalidate=True)
        return response

    return wrapped