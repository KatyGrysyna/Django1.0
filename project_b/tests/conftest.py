import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clean_test_cache():
    cache.clear()
    yield
    cache.clear()