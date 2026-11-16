from unittest.mock import patch

import pytest
from django.db import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

pytestmark = pytest.mark.django_db


def test_health_returns_ok_without_authentication(client):
    # Generated with AI, reviewed and modified
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "no-store" in response.headers["Cache-Control"]


def test_health_supports_head_requests(client):
    # Generated with AI, reviewed and modified
    response = client.head("/health/")

    assert response.status_code == 200
    assert response.content == b""


def test_health_returns_503_when_database_is_unavailable(client):
    # Generated with AI, reviewed and modified
    with patch(
        "shop_project.health.connection.cursor",
        side_effect=OperationalError("Database unavailable"),
    ):
        response = client.get("/health/")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "no-store" in response.headers["Cache-Control"]


def test_health_returns_503_when_redis_is_unavailable(client):
    # Generated with AI, reviewed and modified
    with patch(
        "shop_project.health.cache.get",
        side_effect=RedisConnectionError("Redis unavailable"),
    ):
        response = client.get("/health/")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "no-store" in response.headers["Cache-Control"]


def test_health_rejects_post_requests(client):
    # Generated with AI, reviewed and modified
    response = client.post("/health/", {})

    assert response.status_code == 405
