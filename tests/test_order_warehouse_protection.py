from uuid import uuid4

import pytest
from django.urls import reverse

from catalog.models import Order

from .factories import OrderItemFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def order_item(order):
    return OrderItemFactory(order=order, quantity=2)


def attempt_change(client, order, item, method):
    url = reverse("api:order-detail", args=[order.pk])

    if method == "delete":
        return client.delete(url)

    return getattr(client, method)(
        url,
        {
            "items": [{"book_id": item.book_id, "quantity": 9}],
            "warehouse_status": "none",
            "warehouse_reservation_id": None,
            "warehouse_expires_at": None,
        },
        format="json",
    )


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
@pytest.mark.parametrize(
    "warehouse_status",
    [
        Order.WarehouseStatus.REQUESTING,
        Order.WarehouseStatus.PENDING,
        Order.WarehouseStatus.CONFIRMED,
        Order.WarehouseStatus.RELEASING,
        Order.WarehouseStatus.RELEASED,
        Order.WarehouseStatus.EXPIRED,
        Order.WarehouseStatus.FAILED,
    ],
)
def test_order_with_warehouse_processing_cannot_be_changed(
    auth_api_client, order, order_item, method, warehouse_status
):
    order.warehouse_status = warehouse_status
    order.save(update_fields=["warehouse_status"])

    response = attempt_change(auth_api_client, order, order_item, method)

    assert response.status_code == 400

    order.refresh_from_db()
    order_item.refresh_from_db()

    assert order.status == "pending"
    assert order.warehouse_status == warehouse_status
    assert order.warehouse_reservation_id is None
    assert order.items.count() == 1
    assert order_item.quantity == 2


@pytest.mark.parametrize("method", ["patch", "put", "delete"])
def test_reservation_id_also_protects_order(auth_api_client, order, order_item, method):
    reservation_id = uuid4()
    order.warehouse_reservation_id = reservation_id
    order.save(update_fields=["warehouse_reservation_id"])

    response = attempt_change(auth_api_client, order, order_item, method)

    assert response.status_code == 400

    order.refresh_from_db()
    order_item.refresh_from_db()

    assert order.warehouse_reservation_id == reservation_id
    assert order.warehouse_status == Order.WarehouseStatus.NONE
    assert order.items.count() == 1
    assert order_item.quantity == 2


def test_client_cannot_forge_warehouse_fields_when_creating_order(
    auth_api_client, book
):
    response = auth_api_client.post(
        reverse("api:order-list"),
        {
            "items": [{"book_id": book.pk, "quantity": 1}],
            "warehouse_status": "confirmed",
            "warehouse_reservation_id": str(uuid4()),
            "warehouse_expires_at": "2099-01-01T00:00:00Z",
        },
        format="json",
    )

    assert response.status_code == 201

    order = Order.objects.get(pk=response.data["id"])

    assert order.warehouse_status == Order.WarehouseStatus.NONE
    assert order.warehouse_reservation_id is None
    assert order.warehouse_expires_at is None
