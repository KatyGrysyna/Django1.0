from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
import stripe
from django.utils import timezone

from catalog.checkout_reconciliation import (
    PaymentVerificationError,
    reconcile_warehouse_order,
)
from catalog.models import Order
from catalog.tasks import reconcile_warehouse_orders
from catalog.warehouse_client import WarehouseAPIError, WarehouseUnavailable

from .factories import OrderFactory, OrderItemFactory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
]


def reservation_response(order, status):
    return {
        "id": str(order.warehouse_reservation_id or uuid4()),
        "external_order_id": order.pk,
        "status": status,
        "expires_at": (
            order.warehouse_expires_at or timezone.now() + timedelta(hours=1)
        ).isoformat(),
        "items": [
            {
                "external_book_id": item.book_id,
                "quantity": item.quantity,
            }
            for item in order.items.order_by("book_id")
        ],
    }


def payment_response(order, **changes):
    data = {
        "id": order.stripe_session_id,
        "mode": "payment",
        "client_reference_id": str(order.pk),
        "status": "complete",
        "payment_status": "paid",
        "currency": "uah",
        "amount_total": int(order.get_total() * 100),
    }
    data.update(changes)
    return SimpleNamespace(**data)


@pytest.fixture(autouse=True)
def warehouse(settings):
    settings.WAREHOUSE_ENABLED = True
    settings.EMAIL_ENABLED = False

    with (
        patch(
            "catalog.warehouse_services.WarehouseClient",
            autospec=True,
        ) as reserve_factory,
        patch(
            "catalog.warehouse_lifecycle.WarehouseClient",
            autospec=True,
        ) as lifecycle_factory,
    ):
        client = reserve_factory.return_value
        lifecycle_factory.return_value = client
        client.__enter__.return_value = client
        client.__exit__.return_value = False

        def reserve_reply(external_order_id, items):
            order = Order.objects.get(pk=external_order_id)
            response = reservation_response(order, "pending")
            assert items == response["items"]
            return response

        def action_reply(reservation_id, status):
            order = Order.objects.get(warehouse_reservation_id=reservation_id)
            return reservation_response(order, status)

        client.reserve.side_effect = reserve_reply
        client.confirm.side_effect = lambda reservation_id: action_reply(
            reservation_id, "confirmed"
        )
        client.release.side_effect = lambda reservation_id: action_reply(
            reservation_id, "released"
        )

        yield client


@pytest.fixture(autouse=True)
def payments():
    with (
        patch("stripe.checkout.Session.create") as create,
        patch("stripe.checkout.Session.retrieve") as retrieve,
        patch("stripe.checkout.Session.expire") as expire,
        patch("catalog.tasks.send_order_confirmation.delay") as email,
    ):

        def create_reply(**kwargs):
            order = Order.objects.get(pk=kwargs["client_reference_id"])
            assert order.warehouse_status == "pending"
            assert order.warehouse_reservation_id is not None

            return SimpleNamespace(
                id=f"cs_test_{order.pk}",
                url="https://checkout.stripe.com/test",
            )

        def retrieve_reply(session_id, **kwargs):
            order = Order.objects.get(stripe_session_id=session_id)
            return payment_response(order)

        create.side_effect = create_reply
        retrieve.side_effect = retrieve_reply

        yield SimpleNamespace(
            create=create,
            retrieve=retrieve,
            expire=expire,
            email=email,
        )


@pytest.fixture
def shop_client(client, user, book):
    client.force_login(user)
    client.get(f"/uk/cart/add/{book.pk}/")
    client.get(f"/uk/cart/add/{book.pk}/")
    return client


@pytest.fixture
def reserved_order(order):
    order.warehouse_reservation_id = uuid4()
    order.warehouse_status = "pending"
    order.warehouse_expires_at = timezone.now() + timedelta(hours=1)
    order.stripe_session_id = f"cs_test_{order.pk}"
    order.save()
    OrderItemFactory(order=order, quantity=2)
    return order


def test_checkout_reserves_then_confirms_paid_order(shop_client, warehouse, payments):
    response = shop_client.post("/uk/checkout/")

    assert response.status_code == 303
    order = Order.objects.get()
    assert order.status == "pending"
    assert order.warehouse_status == "pending"

    options = payments.create.call_args.kwargs
    assert options["allowed_payment_method_types"] == ["card"]
    assert options["expires_at"] == int(
        (order.warehouse_expires_at - timedelta(minutes=10)).timestamp()
    )
    warehouse.reserve.assert_called_once()

    response = shop_client.get(
        "/uk/checkout/success/",
        {"order_id": order.pk},
    )

    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == "paid"
    assert order.warehouse_status == "confirmed"
    assert shop_client.session["cart"] == {}
    warehouse.confirm.assert_called_once_with(order.warehouse_reservation_id)


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (WarehouseUnavailable("Test timeout"), 503),
        (WarehouseAPIError(409), 409),
    ],
)
def test_reservation_failure_prevents_payment(
    error, expected_status, shop_client, warehouse, payments
):
    warehouse.reserve.side_effect = error

    response = shop_client.post("/uk/checkout/")

    assert response.status_code == expected_status
    assert shop_client.session["cart"]
    payments.create.assert_not_called()


def test_paid_order_recovers_after_warehouse_timeout(shop_client, warehouse, payments):
    shop_client.post("/uk/checkout/")
    order = Order.objects.get()
    warehouse.confirm.side_effect = WarehouseUnavailable("Test timeout")

    response = shop_client.get(
        "/uk/checkout/success/",
        {"order_id": order.pk},
    )

    assert response.status_code == 200
    assert response.context["warehouse_pending"] is True
    order.refresh_from_db()
    assert order.status == "paid"
    assert order.warehouse_status == "pending"

    warehouse.confirm.side_effect = None
    warehouse.confirm.return_value = reservation_response(order, "confirmed")

    result = reconcile_warehouse_orders.run()

    order.refresh_from_db()
    assert result["paid"] == 1
    assert result["failed"] == 0
    assert order.warehouse_status == "confirmed"
    assert payments.retrieve.call_count == 1

    assert reconcile_warehouse_orders.run()["checked"] == 0


def test_short_reservation_stops_payment(shop_client, warehouse, payments):
    def short_reservation(external_order_id, items):
        order = Order.objects.get(pk=external_order_id)
        response = reservation_response(order, "pending")
        response["expires_at"] = (timezone.now() + timedelta(minutes=35)).isoformat()
        return response

    warehouse.reserve.side_effect = short_reservation

    response = shop_client.post("/uk/checkout/")

    assert response.status_code == 409
    order = Order.objects.get()
    assert order.status == "cancelled"
    assert order.warehouse_status == "released"
    payments.create.assert_not_called()


@pytest.mark.parametrize(
    ("session_status", "expected_order", "expected_stock"),
    [
        ("open", "pending", "pending"),
        ("complete", "pending", "pending"),
        ("expired", "cancelled", "released"),
    ],
)
def test_unpaid_session_is_released_only_after_expiration(
    session_status,
    expected_order,
    expected_stock,
    reserved_order,
    payments,
    warehouse,
):
    payments.retrieve.side_effect = None
    payments.retrieve.return_value = payment_response(
        reserved_order,
        status=session_status,
        payment_status="unpaid",
    )

    reconcile_warehouse_order(reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.status == expected_order
    assert reserved_order.warehouse_status == expected_stock
    warehouse.confirm.assert_not_called()
    assert warehouse.release.call_count == (1 if session_status == "expired" else 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "usd"},
        {"amount_total": 1},
        {"client_reference_id": "another-order"},
    ],
)
def test_mismatched_payment_does_not_change_order(
    changes, reserved_order, payments, warehouse
):
    payments.retrieve.side_effect = None
    payments.retrieve.return_value = payment_response(reserved_order, **changes)

    with pytest.raises(PaymentVerificationError):
        reconcile_warehouse_order(reserved_order.pk)

    reserved_order.refresh_from_db()
    assert reserved_order.status == "pending"
    assert reserved_order.warehouse_status == "pending"
    warehouse.confirm.assert_not_called()
    warehouse.release.assert_not_called()


def test_background_payment_confirmation_sends_email_once(
    reserved_order, payments, settings, warehouse
):
    settings.EMAIL_ENABLED = True

    assert reconcile_warehouse_order(reserved_order.pk) == "paid"
    assert reconcile_warehouse_order(reserved_order.pk) == "paid"

    reserved_order.refresh_from_db()
    assert reserved_order.warehouse_status == "confirmed"
    warehouse.confirm.assert_called_once()
    payments.retrieve.assert_called_once()
    payments.email.assert_called_once_with(reserved_order.pk, settings.LANGUAGE_CODE)


def test_expired_reservation_without_payment_session_is_released(
    reserved_order, payments, warehouse
):
    reserved_order.stripe_session_id = ""
    reserved_order.warehouse_expires_at = timezone.now() - timedelta(minutes=1)
    reserved_order.save()

    assert reconcile_warehouse_order(reserved_order.pk) == "cancelled"

    reserved_order.refresh_from_db()
    assert reserved_order.warehouse_status == "released"
    warehouse.release.assert_called_once()
    payments.retrieve.assert_not_called()


def test_batch_continues_after_one_payment_connection_error(reserved_order, payments):
    another = OrderFactory(
        warehouse_reservation_id=uuid4(),
        warehouse_status="pending",
        warehouse_expires_at=timezone.now() + timedelta(hours=1),
        stripe_session_id="cs_test_another",
    )
    OrderItemFactory(order=another)

    payments.retrieve.side_effect = [
        stripe.APIConnectionError("Test connection failure"),
        payment_response(another),
    ]

    result = reconcile_warehouse_orders.run()

    assert result["checked"] == 2
    assert result["failed"] == 1
    assert result["paid"] == 1

    reserved_order.refresh_from_db()
    another.refresh_from_db()
    assert reserved_order.status == "pending"
    assert another.status == "paid"
    assert another.warehouse_status == "confirmed"


def test_disabled_background_task_makes_no_external_requests(
    reserved_order, settings, payments, warehouse
):
    settings.WAREHOUSE_ENABLED = False

    result = reconcile_warehouse_orders.run()

    assert result["checked"] == 0
    payments.retrieve.assert_not_called()
    warehouse.confirm.assert_not_called()
    warehouse.release.assert_not_called()
