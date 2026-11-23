import logging
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Order
from .warehouse_client import (
    WarehouseAPIError,
    WarehouseClient,
    WarehouseConfigurationError,
    WarehouseError,
    WarehouseProtocolError,
)

logger = logging.getLogger(__name__)

MAX_ITEMS = 100
MAX_QUANTITY = 2**31 - 1

WarehouseStatus = Order.WarehouseStatus

REMOTE_STATES = (
    WarehouseStatus.PENDING,
    WarehouseStatus.CONFIRMED,
    WarehouseStatus.RELEASED,
    WarehouseStatus.EXPIRED,
)


class OrderWarehouseConflict(WarehouseError):
    """The order cannot perform the requested warehouse operation."""


def _locked_order(order_id):
    try:
        return Order.objects.select_for_update().get(pk=order_id)
    except Order.DoesNotExist:
        raise OrderWarehouseConflict("The order no longer exists.") from None


def _order_items(order):
    quantities = {}

    for book_id, quantity in order.items.values_list("book_id", "quantity"):
        if not 1 <= quantity <= MAX_QUANTITY:
            raise OrderWarehouseConflict("The order contains an invalid quantity.")

        quantities[book_id] = quantities.get(book_id, 0) + quantity

        if quantities[book_id] > MAX_QUANTITY:
            raise OrderWarehouseConflict("The requested quantity is too large.")

    if not 1 <= len(quantities) <= MAX_ITEMS:
        raise OrderWarehouseConflict(
            "The order must contain between 1 and 100 different books."
        )

    return [
        {"external_book_id": book_id, "quantity": quantity}
        for book_id, quantity in sorted(quantities.items())
    ]


@transaction.atomic
def _prepare_order(order_id):
    order = _locked_order(order_id)

    if order.status != "pending" or order.stripe_session_id:
        raise OrderWarehouseConflict(
            "Stock can only be reserved before payment processing starts."
        )

    if order.warehouse_status not in (
        WarehouseStatus.NONE,
        WarehouseStatus.REQUESTING,
        WarehouseStatus.PENDING,
    ):
        raise OrderWarehouseConflict(
            "Warehouse processing for this order cannot be restarted."
        )

    if order.warehouse_status == WarehouseStatus.NONE and not order.can_modify:
        raise OrderWarehouseConflict("The order already has warehouse metadata.")

    if (
        order.warehouse_status == WarehouseStatus.PENDING
        and order.warehouse_reservation_id is None
    ):
        raise OrderWarehouseConflict("The order is missing its reservation ID.")

    items = _order_items(order)

    if order.warehouse_status == WarehouseStatus.NONE:
        order.warehouse_status = WarehouseStatus.REQUESTING
        order.save(update_fields=["warehouse_status"])

    return order.pk, items, order.warehouse_reservation_id


def _parse_reservation(data, order_id, requested_items):
    try:
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise ValueError

        reservation_id = UUID(data["id"])

        if (
            type(data.get("external_order_id")) is not int
            or data["external_order_id"] != order_id
        ):
            raise ValueError

        remote_status = data["status"]

        if remote_status not in REMOTE_STATES:
            raise ValueError

        expires_at = parse_datetime(data["expires_at"])

        if expires_at is None or not timezone.is_aware(expires_at):
            raise ValueError

        remote_items = data["items"]

        if not isinstance(remote_items, list):
            raise ValueError

        received_quantities = {}

        for item in remote_items:
            book_id = item["external_book_id"]
            quantity = item["quantity"]

            if (
                type(book_id) is not int
                or type(quantity) is not int
                or book_id < 1
                or quantity < 1
                or book_id in received_quantities
            ):
                raise ValueError

            received_quantities[book_id] = quantity

        expected_quantities = {
            item["external_book_id"]: item["quantity"] for item in requested_items
        }

        if received_quantities != expected_quantities:
            raise ValueError

    except (KeyError, TypeError, ValueError, OverflowError):
        raise WarehouseProtocolError(
            "Warehouse returned an invalid or mismatched reservation."
        ) from None

    return {
        "id": reservation_id,
        "status": remote_status,
        "expires_at": expires_at,
    }


@transaction.atomic
def _save_reservation(order_id, reservation):
    order = _locked_order(order_id)

    if (
        order.status != "pending"
        or order.stripe_session_id
        or order.warehouse_status
        not in (WarehouseStatus.REQUESTING, WarehouseStatus.PENDING)
    ):
        raise OrderWarehouseConflict(
            "The order changed while the warehouse request was running."
        )

    if (
        order.warehouse_reservation_id is not None
        and order.warehouse_reservation_id != reservation["id"]
    ):
        raise WarehouseProtocolError(
            "Warehouse returned a different reservation ID for this order."
        )

    remote_status = reservation["status"]

    if (
        remote_status == WarehouseStatus.PENDING
        and reservation["expires_at"] <= timezone.now()
    ):
        remote_status = WarehouseStatus.EXPIRED

    order.warehouse_reservation_id = reservation["id"]
    order.warehouse_status = remote_status
    order.warehouse_expires_at = reservation["expires_at"]

    order.save(
        update_fields=[
            "warehouse_reservation_id",
            "warehouse_status",
            "warehouse_expires_at",
        ]
    )

    return order


def reserve_order_stock(order_id):
    """Reserve order items through ProjectB and return the updated order."""
    if not settings.WAREHOUSE_ENABLED:
        raise WarehouseConfigurationError("Warehouse integration is disabled.")

    if not transaction.get_autocommit():
        raise WarehouseConfigurationError(
            "Call the warehouse service outside an atomic transaction."
        )

    try:
        with WarehouseClient() as client:
            order_id, items, reservation_id = _prepare_order(order_id)

            try:
                if reservation_id is None:
                    response = client.reserve(
                        external_order_id=order_id,
                        items=items,
                    )
                else:
                    response = client.get_reservation(reservation_id)

            except WarehouseAPIError as exc:
                if reservation_id is None and exc.status_code in (400, 409):
                    Order.objects.filter(
                        pk=order_id,
                        status="pending",
                        stripe_session_id="",
                        warehouse_status=WarehouseStatus.REQUESTING,
                        warehouse_reservation_id__isnull=True,
                    ).update(warehouse_status=WarehouseStatus.FAILED)
                raise

            reservation = _parse_reservation(response, order_id, items)
            order = _save_reservation(order_id, reservation)

        logger.info(
            "Warehouse reservation synchronized: order=%s status=%s",
            order.pk,
            order.warehouse_status,
        )

        if order.warehouse_status != WarehouseStatus.PENDING:
            raise OrderWarehouseConflict("This reservation is no longer active.")

        return order

    except WarehouseError as exc:
        logger.warning(
            "Warehouse reservation failed: order=%s error=%s",
            order_id,
            type(exc).__name__,
        )
        raise
