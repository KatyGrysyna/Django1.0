import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Order
from .warehouse_client import WarehouseConfigurationError, WarehouseError
from .warehouse_lifecycle import confirm_order_stock, release_order_stock


class PaymentVerificationError(WarehouseError):
    """Stripe data does not match the stored order."""


@transaction.atomic
def _apply_payment_session(order_id, session_id, session):
    order = Order.objects.select_for_update().get(pk=order_id)

    if (
        order.stripe_session_id != session_id
        or getattr(session, "id", None) != session_id
        or getattr(session, "mode", None) != "payment"
        or getattr(session, "client_reference_id", None) != str(order.pk)
    ):
        raise PaymentVerificationError("The payment session does not match the order.")

    if order.status != "pending":
        return False

    payment_status = getattr(session, "payment_status", None)

    if payment_status == "paid":
        if getattr(session, "currency", None) != "uah" or getattr(
            session, "amount_total", None
        ) != int(order.get_total() * 100):
            raise PaymentVerificationError(
                "The payment currency or amount does not match the order."
            )

        order.status = "paid"

    elif getattr(session, "status", None) == "expired" and payment_status == "unpaid":
        order.status = "cancelled"

    else:
        return False

    order.save(update_fields=["status"])
    return order.status == "paid"


def reconcile_warehouse_order(order_id):
    """Check payment and finish the corresponding warehouse operation."""
    if not settings.WAREHOUSE_ENABLED:
        return "skipped"

    if not transaction.get_autocommit():
        raise WarehouseConfigurationError(
            "Payment reconciliation must run outside an atomic transaction."
        )

    order = Order.objects.select_related("user").get(pk=order_id)

    if order.warehouse_reservation_id is None:
        return "skipped"

    if order.status == "pending" and order.stripe_session_id:
        session = stripe.checkout.Session.retrieve(
            order.stripe_session_id,
            api_key=settings.STRIPE_SECRET_KEY,
        )

        newly_paid = _apply_payment_session(
            order.pk,
            order.stripe_session_id,
            session,
        )
        order.refresh_from_db()

        if newly_paid and getattr(settings, "EMAIL_ENABLED", True) and order.user.email:
            from .tasks import send_order_confirmation

            transaction.on_commit(
                lambda: send_order_confirmation.delay(
                    order.pk,
                    settings.LANGUAGE_CODE,
                ),
                robust=True,
            )

    if order.status == "paid":
        return confirm_order_stock(order.pk).status

    if order.status == "cancelled":
        return release_order_stock(order.pk).status

    if (
        order.status == "pending"
        and not order.stripe_session_id
        and order.warehouse_expires_at is not None
        and order.warehouse_expires_at <= timezone.now()
    ):
        return release_order_stock(order.pk).status

    return "pending"
