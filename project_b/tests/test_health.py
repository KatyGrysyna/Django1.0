from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.urls import reverse
from redis.exceptions import ConnectionError as RedisConnectionError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db,
]


def test_health_is_public_and_not_cached(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": True, "cache": True},
    }
    assert "no-store" in response.headers["Cache-Control"]


def test_database_failure_returns_503_without_internal_details(client):
    with patch(
        "warehouse_project.health.connection.cursor",
        side_effect=OperationalError("private database details"),
    ):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": False, "cache": True},
    }
    assert b"private database details" not in response.content


def test_cache_failure_returns_503_without_internal_details(client):
    with patch(
        "warehouse_project.health.cache.get",
        side_effect=RedisConnectionError("private cache details"),
    ):
        response = client.get(reverse("health"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": True, "cache": False},
    }
    assert b"private cache details" not in response.content


def test_health_rejects_post(client):
    response = client.post(reverse("health"))

    assert response.status_code == 405
