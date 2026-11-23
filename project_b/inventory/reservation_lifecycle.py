import logging
from functools import partial

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Reservation, StockItem
from .services import ReservationConflict, ReservationError
from .stock_cache import invalidate_stock_cache

logger = logging.getLogger(__name__)


class ReservationNotFound(ReservationError):
    """The reservation does not exist or belongs to another caller."""


class StockIntegrityError(RuntimeError):
    """Stored stock counters are inconsistent with reservation items."""


def _locked_reservation(reservation_id, **filters):
    try:
        return Reservation.objects.select_for_update().get(
            pk=reservation_id,
            **filters,
        )
    except Reservation.DoesNotExist as exc:
        raise ReservationNotFound(_("Reservation not found.")) from exc


def _finish_reservation(reservation, target_status):
    """Complete a reservation whose row is already locked."""

    quantities = dict(reservation.items.values_list("stock_item_id", "quantity"))

    if not quantities:
        raise StockIntegrityError(f"Reservation {reservation.pk} has no items.")

    stock_items = list(
        StockItem.objects.select_for_update().filter(pk__in=quantities).order_by("pk")
    )

    if len(stock_items) != len(quantities):
        raise StockIntegrityError(
            f"Reservation {reservation.pk} references missing stock."
        )

    now = timezone.now()

    # Check the deadline after waiting for stock locks.
    if target_status == Reservation.Status.CONFIRMED and reservation.expires_at <= now:
        raise ReservationConflict(_("An expired reservation cannot be confirmed."))

    for stock_item in stock_items:
        if stock_item.reserved < quantities[stock_item.pk]:
            raise StockIntegrityError(
                f"Inconsistent reserved quantity for stock item " f"{stock_item.pk}."
            )

    for stock_item in stock_items:
        quantity = quantities[stock_item.pk]
        stock_item.reserved -= quantity

        if target_status == Reservation.Status.CONFIRMED:
            stock_item.quantity -= quantity

        stock_item.updated_at = now

    StockItem.objects.bulk_update(
        stock_items,
        fields=["quantity", "reserved", "updated_at"],
    )

    reservation.status = target_status
    reservation.save(update_fields=["status", "updated_at"])

    transaction.on_commit(invalidate_stock_cache)
    transaction.on_commit(
        partial(
            logger.info,
            "Reservation %s changed to %s",
            str(reservation.pk),
            target_status,
        )
    )


@transaction.atomic
def confirm_reservation(*, reservation_id, created_by):
    """Confirm once and return (reservation, changed)."""

    reservation = _locked_reservation(
        reservation_id,
        created_by=created_by,
    )

    if reservation.status == Reservation.Status.CONFIRMED:
        return reservation, False

    if reservation.status != Reservation.Status.PENDING:
        raise ReservationConflict(_("Only pending reservations can be confirmed."))

    _finish_reservation(reservation, Reservation.Status.CONFIRMED)
    return reservation, True


@transaction.atomic
def release_reservation(*, reservation_id, created_by):
    """Release once and return (reservation, changed)."""

    reservation = _locked_reservation(
        reservation_id,
        created_by=created_by,
    )

    if reservation.status in (
        Reservation.Status.RELEASED,
        Reservation.Status.EXPIRED,
    ):
        return reservation, False

    if reservation.status != Reservation.Status.PENDING:
        raise ReservationConflict(_("Only pending reservations can be released."))

    _finish_reservation(reservation, Reservation.Status.RELEASED)
    return reservation, True


@transaction.atomic
def expire_reservation(*, reservation_id):
    """Expire an overdue reservation; intended for background tasks."""

    reservation = _locked_reservation(reservation_id)

    if (
        reservation.status != Reservation.Status.PENDING
        or reservation.expires_at > timezone.now()
    ):
        return reservation, False

    _finish_reservation(reservation, Reservation.Status.EXPIRED)
    return reservation, True
