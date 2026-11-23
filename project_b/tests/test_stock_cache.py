from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from inventory.models import StockItem


pytestmark = [pytest.mark.api, pytest.mark.django_db]


@pytest.fixture
def viewer_client(db, django_user_model):
    call_command("setup_warehouse_groups", stdout=StringIO())

    user = django_user_model.objects.create_user(
        username="cache_viewer",
        password="Cache-test-password-123",
    )
    user.groups.add(Group.objects.get(name="warehouse_viewers"))

    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    return client


@pytest.fixture
def stock_item(db):
    return StockItem.objects.create(
        external_book_id=101,
        title="Cached book",
        quantity=10,
        reserved=2,
    )


def test_second_request_uses_cache(viewer_client, stock_item):
    url = reverse("stock-list")
    first = viewer_client.get(url)

    assert first.status_code == 200
    assert first.data["results"][0]["available"] == 8

    with CaptureQueriesContext(connection) as queries:
        second = viewer_client.get(url)

    assert second.status_code == 200
    assert second.data == first.data
    assert second["Cache-Control"] == "private, no-store"

    table = StockItem._meta.db_table
    assert not any(
        table in query["sql"]
        for query in queries.captured_queries
    )


def test_cache_separates_filters(viewer_client, stock_item):
    StockItem.objects.create(
        external_book_id=202,
        title="Second book",
        quantity=3,
    )
    url = reverse("stock-list")

    all_items = viewer_client.get(url)
    filtered = viewer_client.get(url, {"external_book_id": 101})

    assert all_items.status_code == 200
    assert all_items.data["count"] == 2

    assert filtered.status_code == 200
    assert filtered.data["count"] == 1
    assert filtered.data["results"][0]["external_book_id"] == 101

    assert viewer_client.get(url).data["count"] == 2


@pytest.mark.parametrize(
    ("action", "expected_count"),
    [
        ("create", 2),
        ("update", 1),
        ("delete", 0),
    ],
)
def test_stock_changes_refresh_cache(
    viewer_client,
    stock_item,
    django_capture_on_commit_callbacks,
    action,
    expected_count,
):
    url = reverse("stock-list")
    before = viewer_client.get(url)

    assert before.status_code == 200
    assert before.data["count"] == 1

    with django_capture_on_commit_callbacks(execute=True):
        if action == "create":
            StockItem.objects.create(
                external_book_id=202,
                title="New book",
                quantity=3,
            )
        elif action == "update":
            stock_item.quantity = 20
            stock_item.save(update_fields=["quantity", "updated_at"])
        else:
            stock_item.delete()

        pending = viewer_client.get(url)

        assert pending.status_code == 200
        assert pending.data == before.data

    after = viewer_client.get(url)

    assert after.status_code == 200
    assert after.data["count"] == expected_count

    if action == "update":
        assert after.data["results"][0]["quantity"] == 20
        assert after.data["results"][0]["available"] == 18


@pytest.mark.parametrize("method", ["get_or_set", "set"])
def test_cache_failure_does_not_break_api(
    viewer_client,
    stock_item,
    caplog,
    method,
):
    with patch(
        f"inventory.stock_cache.cache.{method}",
        side_effect=RedisConnectionError("Simulated Redis outage"),
    ):
        response = viewer_client.get(reverse("stock-list"))

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["available"] == 8
    assert "Stock cache" in caplog.text