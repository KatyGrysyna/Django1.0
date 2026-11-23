from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from catalog.models import Order
from catalog.warehouse_client import (
    WarehouseAPIError,
    WarehouseAuthenticationError,
    WarehouseConfigurationError,
    WarehouseProtocolError,
    WarehouseUnavailable,
)
from catalog.warehouse_services import (
    OrderWarehouseConflict,
    reserve_order_stock,
)

from .factories import OrderItemFactory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture(autouse=True)
def warehouse_client(settings):
    settings.WAREHOUSE_ENABLED = True

    with patch(
        "catalog.warehouse_services.WarehouseClient",
        autospec=True,
    ) as factory:
        client = factory.return_value
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        yield client


@pytest.fixture
def order_item(order):
    return OrderItemFactory(order=order, quantity=2)


@pytest.fixture
def reservation_data(order, order_item):
    return {
        "id": str(uuid4()),
        "external_order_id": order.pk,
        "status": "pending",
        "expires_at": (timezone.now() + timedelta(hours=1)).isoformat(),
        "items": [
            {
                "external_book_id": order_item.book_id,
                "quantity": 2,
                "title": order_item.book.title,
            }
        ],
    }


def test_reservation_freezes_order_before_http_request(
    warehouse_client, order, order_item, reservation_data
):
    expected_items = [{"external_book_id": order_item.book_id, "quantity": 2}]

    def warehouse_reply(**kwargs):
        assert transaction.get_autocommit() is True

        saved_order = Order.objects.get(pk=order.pk)
        assert saved_order.warehouse_status == "requesting"
        assert saved_order.can_modify is False
        assert kwargs == {
            "external_order_id": order.pk,
            "items": expected_items,
        }
        return reservation_data

    warehouse_client.reserve.side_effect = warehouse_reply

    result = reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert result.pk == order.pk
    assert order.status == "pending"
    assert order.warehouse_status == "pending"
    assert order.warehouse_reservation_id == UUID(reservation_data["id"])
    assert order.warehouse_expires_at.isoformat() == reservation_data["expires_at"]
    warehouse_client.reserve.assert_called_once()
    warehouse_client.get_reservation.assert_not_called()


def test_timeout_preserves_request_for_safe_retry(
    warehouse_client, order, reservation_data
):
    warehouse_client.reserve.side_effect = [
        WarehouseUnavailable("Connection timed out"),
        reservation_data,
    ]

    with pytest.raises(WarehouseUnavailable):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "requesting"
    assert order.warehouse_reservation_id is None
    assert order.can_modify is False
    assert warehouse_client.reserve.call_count == 1

    result = reserve_order_stock(order.pk)

    assert result.warehouse_status == "pending"
    assert result.warehouse_reservation_id == UUID(reservation_data["id"])

    calls = warehouse_client.reserve.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs == calls[1].kwargs


def test_existing_reservation_is_read_without_creating_another(
    warehouse_client, order, reservation_data
):
    warehouse_client.reserve.return_value = reservation_data
    first = reserve_order_stock(order.pk)

    warehouse_client.get_reservation.return_value = reservation_data
    second = reserve_order_stock(order.pk)

    assert first.warehouse_reservation_id == second.warehouse_reservation_id
    assert second.warehouse_status == "pending"
    warehouse_client.reserve.assert_called_once()
    warehouse_client.get_reservation.assert_called_once_with(
        first.warehouse_reservation_id
    )


def test_duplicate_book_lines_are_combined(
    warehouse_client, order, order_item, reservation_data
):
    OrderItemFactory(
        order=order,
        book=order_item.book,
        quantity=3,
    )
    reservation_data["items"][0]["quantity"] = 5
    warehouse_client.reserve.return_value = reservation_data

    reserve_order_stock(order.pk)

    warehouse_client.reserve.assert_called_once_with(
        external_order_id=order.pk,
        items=[{"external_book_id": order_item.book_id, "quantity": 5}],
    )
    assert order.items.count() == 2


@pytest.mark.parametrize("status_code", [400, 409])
def test_business_rejection_marks_order_as_failed(
    warehouse_client, order, order_item, status_code
):
    warehouse_client.reserve.side_effect = WarehouseAPIError(status_code)

    with pytest.raises(WarehouseAPIError) as error:
        reserve_order_stock(order.pk)

    assert error.value.status_code == status_code

    order.refresh_from_db()
    order_item.refresh_from_db()

    assert order.warehouse_status == "failed"
    assert order.warehouse_reservation_id is None
    assert order_item.quantity == 2
    warehouse_client.reserve.assert_called_once()


def test_authentication_failure_keeps_order_retryable(
    warehouse_client, order, order_item
):
    warehouse_client.reserve.side_effect = WarehouseAuthenticationError(
        "Authentication failed"
    )

    with pytest.raises(WarehouseAuthenticationError):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "requesting"
    assert order.warehouse_reservation_id is None


@pytest.mark.parametrize(
    "case",
    ["order_id", "uuid", "quantity", "duplicates", "expiry", "status"],
)
def test_invalid_response_cannot_be_saved(
    warehouse_client, order, reservation_data, case
):
    data = deepcopy(reservation_data)

    if case == "order_id":
        data["external_order_id"] += 1
    elif case == "uuid":
        data["id"] = "not-a-uuid"
    elif case == "quantity":
        data["items"][0]["quantity"] += 1
    elif case == "duplicates":
        data["items"].append(dict(data["items"][0]))
    elif case == "expiry":
        data["expires_at"] = "2099-01-01T00:00:00"
    elif case == "status":
        data["status"] = "requesting"

    warehouse_client.reserve.return_value = data

    with pytest.raises(WarehouseProtocolError):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "requesting"
    assert order.warehouse_reservation_id is None
    assert order.warehouse_expires_at is None


@pytest.mark.parametrize("remote_status", ["confirmed", "released", "expired"])
def test_closed_remote_reservation_is_recorded(
    warehouse_client, order, reservation_data, remote_status
):
    warehouse_client.reserve.return_value = reservation_data
    reserve_order_stock(order.pk)

    data = deepcopy(reservation_data)
    data["status"] = remote_status

    if remote_status == "expired":
        data["expires_at"] = (timezone.now() - timedelta(minutes=1)).isoformat()

    warehouse_client.get_reservation.return_value = data

    with pytest.raises(OrderWarehouseConflict):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == remote_status
    assert order.warehouse_reservation_id == UUID(reservation_data["id"])
    assert order.status == "pending"


def test_past_deadline_is_saved_as_expired(warehouse_client, order, reservation_data):
    reservation_data["expires_at"] = (timezone.now() - timedelta(minutes=1)).isoformat()
    warehouse_client.reserve.return_value = reservation_data

    with pytest.raises(OrderWarehouseConflict):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "expired"
    assert order.warehouse_reservation_id == UUID(reservation_data["id"])
    assert order.warehouse_expires_at < timezone.now()


def test_known_reservation_id_cannot_be_replaced(
    warehouse_client, order, reservation_data
):
    warehouse_client.reserve.return_value = reservation_data
    reserve_order_stock(order.pk)

    changed_response = deepcopy(reservation_data)
    changed_response["id"] = str(uuid4())
    warehouse_client.get_reservation.return_value = changed_response

    with pytest.raises(WarehouseProtocolError):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_reservation_id == UUID(reservation_data["id"])
    assert order.warehouse_status == "pending"


def test_late_response_cannot_overwrite_changed_order_state(
    warehouse_client, order, reservation_data
):
    def warehouse_reply(**kwargs):
        Order.objects.filter(pk=order.pk).update(warehouse_status="releasing")
        return reservation_data

    warehouse_client.reserve.side_effect = warehouse_reply

    with pytest.raises(OrderWarehouseConflict):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "releasing"
    assert order.warehouse_reservation_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "paid"},
        {"status": "cancelled"},
        {"stripe_session_id": "cs_test_existing"},
        {"warehouse_status": "failed"},
        {"warehouse_status": "pending"},
        {"warehouse_reservation_id": uuid4()},
    ],
)
def test_ineligible_order_does_not_contact_warehouse(
    warehouse_client, order, order_item, changes
):
    Order.objects.filter(pk=order.pk).update(**changes)

    with pytest.raises(OrderWarehouseConflict):
        reserve_order_stock(order.pk)

    warehouse_client.reserve.assert_not_called()
    warehouse_client.get_reservation.assert_not_called()


def test_empty_order_remains_editable(warehouse_client, order):
    with pytest.raises(OrderWarehouseConflict):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "none"
    assert order.can_modify is True
    warehouse_client.reserve.assert_not_called()


@pytest.mark.parametrize("case", ["zero", "overflow"])
def test_invalid_quantities_are_rejected_before_request(
    warehouse_client, order, order_item, case
):
    if case == "zero":
        order_item.quantity = 0
        order_item.save(update_fields=["quantity"])
    else:
        OrderItemFactory(
            order=order,
            book=order_item.book,
            quantity=2147483647,
        )

    with pytest.raises(OrderWarehouseConflict):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "none"
    warehouse_client.reserve.assert_not_called()


def test_disabled_integration_does_not_change_order(
    settings, warehouse_client, order, order_item
):
    settings.WAREHOUSE_ENABLED = False

    with pytest.raises(WarehouseConfigurationError):
        reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "none"
    warehouse_client.reserve.assert_not_called()


def test_service_rejects_outer_transaction(warehouse_client, order, order_item):
    with transaction.atomic():
        with pytest.raises(WarehouseConfigurationError):
            reserve_order_stock(order.pk)

    order.refresh_from_db()

    assert order.warehouse_status == "none"
    warehouse_client.reserve.assert_not_called()
