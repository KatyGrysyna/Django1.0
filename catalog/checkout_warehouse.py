import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Order
from .warehouse_client import WarehouseError
from .warehouse_lifecycle import confirm_order_stock, release_order_stock
from .warehouse_services import OrderWarehouseConflict, reserve_order_stock

logger = logging.getLogger(__name__)

PAYMENT_MARGIN = timedelta(minutes=10)


def prepare_warehouse_checkout(order_id):
    """Reserve stock and prepare Stripe options for this reservation."""
    if not settings.WAREHOUSE_ENABLED:
        return {}

    order = reserve_order_stock(order_id)
    payment_deadline = order.warehouse_expires_at - PAYMENT_MARGIN

    # Stripe requires at least 30 minutes; allow a little extra time.
    if payment_deadline <= timezone.now() + timedelta(minutes=31):
        release_order_stock(order.pk)
        raise OrderWarehouseConflict(
            "The reservation has too little time left for payment."
        )

    return {
        "expires_at": int(payment_deadline.timestamp()),
        "allowed_payment_method_types": ["card"],
        "client_reference_id": str(order.pk),
        "idempotency_key": (f"warehouse-checkout-{order.warehouse_reservation_id}"),
    }


@transaction.atomic
def save_checkout_session(order_id, session_id):
    """Attach a payment session only while the order is still eligible."""
    try:
        order = Order.objects.select_for_update().get(pk=order_id)
    except Order.DoesNotExist:
        raise OrderWarehouseConflict("The order no longer exists.") from None

    if order.status != "pending":
        raise OrderWarehouseConflict("The order is no longer pending.")

    if order.stripe_session_id not in ("", session_id):
        raise OrderWarehouseConflict(
            "The order already has a different payment session."
        )

    if settings.WAREHOUSE_ENABLED or order.warehouse_reservation_id:
        if (
            order.warehouse_reservation_id is None
            or order.warehouse_status != Order.WarehouseStatus.PENDING
            or order.warehouse_expires_at is None
            or order.warehouse_expires_at <= timezone.now() + PAYMENT_MARGIN
        ):
            raise OrderWarehouseConflict(
                "The warehouse reservation is no longer ready for payment."
            )

    order.stripe_session_id = session_id
    order.save(update_fields=["stripe_session_id"])
    return order


def confirm_checkout_stock(order_id):
    """Attempt fulfillment without undoing an already verified payment."""
    if not settings.WAREHOUSE_ENABLED:
        return True

    order = Order.objects.get(pk=order_id)

    if order.warehouse_reservation_id is None:
        return True

    if order.warehouse_status == Order.WarehouseStatus.CONFIRMED:
        return True

    try:
        confirm_order_stock(order.pk)
    except WarehouseError as exc:
        logger.error(
            "Paid order stock confirmation failed: order=%s error=%s",
            order.pk,
            type(exc).__name__,
        )
        return False

    return True
