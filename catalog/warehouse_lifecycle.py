import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .warehouse_client import (
    WarehouseAPIError,
    WarehouseClient,
    WarehouseConfigurationError,
    WarehouseError,
    WarehouseProtocolError,
    WarehouseUnavailable,
)
from .warehouse_services import (
    OrderWarehouseConflict,
    WarehouseStatus,
    _locked_order,
    _order_items,
    _parse_reservation,
)

logger = logging.getLogger(__name__)

DONE_STATES = {
    "confirm": (WarehouseStatus.CONFIRMED,),
    "release": (
        WarehouseStatus.RELEASED,
        WarehouseStatus.EXPIRED,
    ),
}


@transaction.atomic
def _prepare_action(order_id, action):
    order = _locked_order(order_id)

    if order.warehouse_reservation_id is None:
        raise OrderWarehouseConflict("The order has no warehouse reservation ID.")

    if action == "confirm":
        if order.status != "paid":
            raise OrderWarehouseConflict(
                "Stock can only be confirmed for a paid order."
            )

        if order.warehouse_status == WarehouseStatus.CONFIRMED:
            return order, [], False

        if order.warehouse_status != WarehouseStatus.PENDING:
            raise OrderWarehouseConflict(
                "The order has no pending reservation to confirm."
            )

    else:
        if order.status not in ("pending", "cancelled"):
            raise OrderWarehouseConflict("Stock cannot be released for a paid order.")

        if order.status == "pending" and order.stripe_session_id:
            raise OrderWarehouseConflict(
                "Resolve the payment session before releasing stock."
            )

        if order.warehouse_status == WarehouseStatus.RELEASED:
            if order.status != "cancelled":
                order.status = "cancelled"
                order.save(update_fields=["status"])
            return order, [], False

        if order.warehouse_status not in (
            WarehouseStatus.PENDING,
            WarehouseStatus.RELEASING,
            WarehouseStatus.EXPIRED,
        ):
            raise OrderWarehouseConflict(
                "The warehouse reservation cannot be released."
            )

    items = _order_items(order)

    if action == "release":
        # A local expiry does not prove that the warehouse has freed stock.
        order.status = "cancelled"
        order.warehouse_status = WarehouseStatus.RELEASING
        order.save(update_fields=["status", "warehouse_status"])

    return order, items, True


@transaction.atomic
def _save_action(order_id, action, reservation):
    order = _locked_order(order_id)

    if action == "confirm":
        expected_order_status = "paid"
        allowed_states = (
            WarehouseStatus.PENDING,
            WarehouseStatus.CONFIRMED,
        )
    else:
        expected_order_status = "cancelled"
        allowed_states = (
            WarehouseStatus.RELEASING,
            WarehouseStatus.RELEASED,
            WarehouseStatus.EXPIRED,
        )

    if (
        order.status != expected_order_status
        or order.warehouse_status not in allowed_states
    ):
        raise OrderWarehouseConflict(
            "The order changed while the warehouse request was running."
        )

    if order.warehouse_reservation_id != reservation["id"]:
        raise WarehouseProtocolError("Warehouse returned a different reservation ID.")

    remote_status = reservation["status"]

    if action == "release" and remote_status == WarehouseStatus.PENDING:
        remote_status = WarehouseStatus.RELEASING
    elif (
        remote_status == WarehouseStatus.PENDING
        and reservation["expires_at"] <= timezone.now()
    ):
        remote_status = WarehouseStatus.EXPIRED

    if (
        order.warehouse_status in DONE_STATES[action]
        and remote_status not in DONE_STATES[action]
    ):
        raise OrderWarehouseConflict(
            "A completed operation cannot be overwritten by a stale response."
        )

    order.warehouse_status = remote_status
    order.warehouse_expires_at = reservation["expires_at"]
    order.save(
        update_fields=[
            "warehouse_status",
            "warehouse_expires_at",
        ]
    )

    return order


def _run_action(order_id, action):
    if not settings.WAREHOUSE_ENABLED:
        raise WarehouseConfigurationError("Warehouse integration is disabled.")

    if not transaction.get_autocommit():
        raise WarehouseConfigurationError(
            "Call the warehouse service outside an atomic transaction."
        )

    try:
        with WarehouseClient() as client:
            order, items, needs_request = _prepare_action(order_id, action)
            order_id = order.pk

            if not needs_request:
                return order

            try:
                response = getattr(client, action)(order.warehouse_reservation_id)
            except WarehouseAPIError as exc:
                if exc.status_code != 409:
                    raise

                response = client.get_reservation(order.warehouse_reservation_id)

            reservation = _parse_reservation(response, order_id, items)
            order = _save_action(order_id, action, reservation)

        logger.info(
            "Warehouse operation synchronized: order=%s action=%s status=%s",
            order.pk,
            action,
            order.warehouse_status,
        )

        if order.warehouse_status in DONE_STATES[action]:
            return order

        if order.warehouse_status in (
            WarehouseStatus.PENDING,
            WarehouseStatus.RELEASING,
        ):
            raise WarehouseUnavailable("The warehouse operation has not completed yet.")

        raise OrderWarehouseConflict(
            "The reservation is in a state that prevents this operation."
        )

    except WarehouseError as exc:
        logger.warning(
            "Warehouse operation failed: order=%s action=%s error=%s",
            order_id,
            action,
            type(exc).__name__,
        )
        raise


def confirm_order_stock(order_id):
    """Confirm warehouse stock after the order has been marked paid."""
    return _run_action(order_id, "confirm")


def release_order_stock(order_id):
    """Release a known reservation when cancellation is safe."""
    return _run_action(order_id, "release")
