from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from catalog.models import Order
from catalog.warehouse_client import (
    WarehouseAPIError,
    WarehouseConfigurationError,
    WarehouseProtocolError,
    WarehouseUnavailable,
)
from catalog.warehouse_lifecycle import (
    confirm_order_stock,
    release_order_stock,
)
from catalog.warehouse_services import OrderWarehouseConflict

from .factories import OrderItemFactory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
]

ACTIONS = {
    "confirm": confirm_order_stock,
    "release": release_order_stock,
}

FINISHED = {
    "confirm": "confirmed",
    "release": "released",
}


@pytest.fixture(autouse=True)
def warehouse_client(settings):
    settings.WAREHOUSE_ENABLED = True

    with patch(
        "catalog.warehouse_lifecycle.WarehouseClient",
        autospec=True,
    ) as factory:
        client = factory.return_value
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        yield client


@pytest.fixture
def reserved_order(order):
    order.warehouse_reservation_id = uuid4()
    order.warehouse_status = "pending"
    order.warehouse_expires_at = timezone.now() + timedelta(hours=1)
    order.save()
    OrderItemFactory(order=order, quantity=2)
    return order


@pytest.fixture
def reservation_data(reserved_order):
    item = reserved_order.items.get()
    return {
        "id": str(reserved_order.warehouse_reservation_id),
        "external_order_id": reserved_order.pk,
        "status": "pending",
        "expires_at": reserved_order.warehouse_expires_at.isoformat(),
        "items": [
            {
                "external_book_id": item.book_id,
                "quantity": item.quantity,
            }
        ],
    }


@pytest.fixture(params=["confirm", "release"])
def operation(request, reserved_order):
    if request.param == "confirm":
        reserved_order.status = "paid"
        reserved_order.save(update_fields=["status"])
    return request.param


def test_action_runs_outside_transaction_and_is_idempotent(
    operation, warehouse_client, reserved_order, reservation_data
):
    method = getattr(warehouse_client, operation)
    reservation_id = reserved_order.warehouse_reservation_id

    def reply(received_id):
        assert received_id == reservation_id
        assert transaction.get_autocommit() is True

        saved = Order.objects.get(pk=reserved_order.pk)
        if operation == "confirm":
            assert saved.status == "paid"
            assert saved.warehouse_status == "pending"
        else:
            assert saved.status == "cancelled"
            assert saved.warehouse_status == "releasing"

        return dict(reservation_data, status=FINISHED[operation])

    method.side_effect = reply

    first = ACTIONS[operation](reserved_order.pk)
    second = ACTIONS[operation](reserved_order.pk)

    reserved_order.refresh_from_db()
    assert first.pk == second.pk == reserved_order.pk
    assert reserved_order.warehouse_status == FINISHED[operation]
    assert reserved_order.warehouse_reservation_id == reservation_id
    assert reserved_order.status == ("paid" if operation == "confirm" else "cancelled")
    method.assert_called_once_with(reservation_id)
    warehouse_client.get_reservation.assert_not_called()


def test_timeout_preserves_state_and_allows_retry(
    operation, warehouse_client, reserved_order, reservation_data
):
    method = getattr(warehouse_client, operation)
    reservation_id = reserved_order.warehouse_reservation_id
    method.side_effect = [
        WarehouseUnavailable("Connection timed out"),
        dict(reservation_data, status=FINISHED[operation]),
    ]

    with pytest.raises(WarehouseUnavailable):
        ACTIONS[operation](reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.warehouse_reservation_id == reservation_id
    assert reserved_order.warehouse_status == (
        "pending" if operation == "confirm" else "releasing"
    )
    assert reserved_order.status == ("paid" if operation == "confirm" else "cancelled")

    result = ACTIONS[operation](reserved_order.pk)

    assert result.warehouse_status == FINISHED[operation]
    assert method.call_count == 2
    for recorded_call in method.call_args_list:
        assert recorded_call.args == (reservation_id,)


def test_conflict_fetches_reservation_and_recognizes_completed_action(
    operation, warehouse_client, reserved_order, reservation_data
):
    method = getattr(warehouse_client, operation)
    method.side_effect = WarehouseAPIError(409)
    warehouse_client.get_reservation.return_value = dict(
        reservation_data, status=FINISHED[operation]
    )

    result = ACTIONS[operation](reserved_order.pk)

    assert result.warehouse_status == FINISHED[operation]
    warehouse_client.get_reservation.assert_called_once_with(
        reserved_order.warehouse_reservation_id
    )


@pytest.mark.parametrize("overdue", [False, True])
def test_conflict_with_pending_reservation_does_not_claim_success(
    operation, overdue, warehouse_client, reserved_order, reservation_data
):
    getattr(warehouse_client, operation).side_effect = WarehouseAPIError(409)
    if overdue:
        reservation_data["expires_at"] = (
            timezone.now() - timedelta(minutes=1)
        ).isoformat()
    warehouse_client.get_reservation.return_value = reservation_data

    expired_confirmation = operation == "confirm" and overdue
    error = OrderWarehouseConflict if expired_confirmation else WarehouseUnavailable

    with pytest.raises(error):
        ACTIONS[operation](reserved_order.pk)

    reserved_order.refresh_from_db()
    if operation == "release":
        assert reserved_order.warehouse_status == "releasing"
        assert reserved_order.status == "cancelled"
    else:
        assert reserved_order.warehouse_status == ("expired" if overdue else "pending")
        assert reserved_order.status == "paid"


@pytest.mark.parametrize("remote_status", ["released", "expired"])
def test_confirm_records_closed_reservation_without_changing_payment(
    remote_status, warehouse_client, reserved_order, reservation_data
):
    reserved_order.status = "paid"
    reserved_order.save(update_fields=["status"])
    warehouse_client.confirm.side_effect = WarehouseAPIError(409)
    warehouse_client.get_reservation.return_value = dict(
        reservation_data, status=remote_status
    )

    with pytest.raises(OrderWarehouseConflict):
        confirm_order_stock(reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.warehouse_status == remote_status
    assert reserved_order.status == "paid"


def test_remote_confirmation_does_not_mark_cancelled_order_paid(
    warehouse_client, reserved_order, reservation_data
):
    warehouse_client.release.side_effect = WarehouseAPIError(409)
    warehouse_client.get_reservation.return_value = dict(
        reservation_data, status="confirmed"
    )

    with pytest.raises(OrderWarehouseConflict):
        release_order_stock(reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.status == "cancelled"
    assert reserved_order.warehouse_status == "confirmed"


def test_other_api_errors_propagate_without_reconciliation(
    operation, warehouse_client, reserved_order
):
    getattr(warehouse_client, operation).side_effect = WarehouseAPIError(400)

    with pytest.raises(WarehouseAPIError) as caught:
        ACTIONS[operation](reserved_order.pk)

    assert caught.value.status_code == 400
    warehouse_client.get_reservation.assert_not_called()
    reserved_order.refresh_from_db()
    assert reserved_order.warehouse_status == (
        "pending" if operation == "confirm" else "releasing"
    )


def test_response_cannot_replace_reservation_id(
    operation, warehouse_client, reserved_order, reservation_data
):
    original_id = reserved_order.warehouse_reservation_id
    getattr(warehouse_client, operation).return_value = dict(
        reservation_data,
        id=str(uuid4()),
        status=FINISHED[operation],
    )

    with pytest.raises(WarehouseProtocolError):
        ACTIONS[operation](reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.warehouse_reservation_id == original_id
    assert reserved_order.warehouse_status == (
        "pending" if operation == "confirm" else "releasing"
    )


def test_stale_response_cannot_overwrite_completed_operation(
    operation, warehouse_client, reserved_order, reservation_data
):
    def reply(reservation_id):
        Order.objects.filter(pk=reserved_order.pk).update(
            warehouse_status=FINISHED[operation]
        )
        return reservation_data

    getattr(warehouse_client, operation).side_effect = reply

    with pytest.raises(OrderWarehouseConflict):
        ACTIONS[operation](reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.warehouse_status == FINISHED[operation]


@pytest.mark.parametrize(
    ("payment_status", "warehouse_status"),
    [
        ("pending", "pending"),
        ("cancelled", "pending"),
        ("paid", "released"),
        ("paid", "expired"),
    ],
)
def test_ineligible_order_cannot_be_confirmed(
    payment_status, warehouse_status, warehouse_client, reserved_order
):
    reserved_order.status = payment_status
    reserved_order.warehouse_status = warehouse_status
    reserved_order.save()

    with pytest.raises(OrderWarehouseConflict):
        confirm_order_stock(reserved_order.pk)

    warehouse_client.confirm.assert_not_called()
    warehouse_client.get_reservation.assert_not_called()


@pytest.mark.parametrize(
    ("payment_status", "session_id"),
    [
        ("paid", ""),
        ("pending", "cs_test_open"),
    ],
)
def test_release_rejects_paid_order_or_unresolved_payment_session(
    payment_status, session_id, warehouse_client, reserved_order
):
    reserved_order.status = payment_status
    reserved_order.stripe_session_id = session_id
    reserved_order.save()

    with pytest.raises(OrderWarehouseConflict):
        release_order_stock(reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.status == payment_status
    assert reserved_order.warehouse_status == "pending"
    warehouse_client.release.assert_not_called()


def test_cancelled_order_with_session_can_release_stock(
    warehouse_client, reserved_order, reservation_data
):
    reserved_order.status = "cancelled"
    reserved_order.stripe_session_id = "cs_test_closed"
    reserved_order.save()
    warehouse_client.release.return_value = dict(reservation_data, status="released")

    result = release_order_stock(reserved_order.pk)

    assert result.status == "cancelled"
    assert result.warehouse_status == "released"
    warehouse_client.release.assert_called_once()


def test_local_expiry_still_requires_warehouse_request(
    warehouse_client, reserved_order, reservation_data
):
    reserved_order.warehouse_status = "expired"
    reserved_order.warehouse_expires_at = timezone.now() - timedelta(minutes=1)
    reserved_order.save()
    warehouse_client.release.return_value = dict(
        reservation_data,
        status="expired",
        expires_at=reserved_order.warehouse_expires_at.isoformat(),
    )

    result = release_order_stock(reserved_order.pk)

    assert result.status == "cancelled"
    assert result.warehouse_status == "expired"
    warehouse_client.release.assert_called_once_with(
        reserved_order.warehouse_reservation_id
    )


def test_action_requires_reservation_id(operation, warehouse_client, reserved_order):
    reserved_order.warehouse_reservation_id = None
    reserved_order.save(update_fields=["warehouse_reservation_id"])

    with pytest.raises(OrderWarehouseConflict):
        ACTIONS[operation](reserved_order.pk)

    getattr(warehouse_client, operation).assert_not_called()


def test_disabled_integration_rejects_action(
    operation, settings, warehouse_client, reserved_order
):
    settings.WAREHOUSE_ENABLED = False

    with pytest.raises(WarehouseConfigurationError):
        ACTIONS[operation](reserved_order.pk)

    getattr(warehouse_client, operation).assert_not_called()


def test_outer_transaction_rejects_action(operation, warehouse_client, reserved_order):
    with transaction.atomic():
        with pytest.raises(WarehouseConfigurationError):
            ACTIONS[operation](reserved_order.pk)

    getattr(warehouse_client, operation).assert_not_called()
