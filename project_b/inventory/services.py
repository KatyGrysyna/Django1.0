import logging
from datetime import timedelta
from functools import partial

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Reservation, ReservationItem, StockItem
from .stock_cache import invalidate_stock_cache

logger = logging.getLogger(__name__)

RESERVATION_TTL = timedelta(hours=1)
MAX_ITEMS = 100
MAX_EXTERNAL_ID = 2**63 - 1
MAX_QUANTITY = 2**31 - 1


class ReservationError(Exception):
    """Base error for reservation operations."""


class InvalidReservation(ReservationError):
    """The request contains invalid data."""


class ReservationConflict(ReservationError):
    """The order already has an incompatible or closed reservation."""


class StockUnavailable(ReservationError):
    """A book is missing or has insufficient available stock."""


def _positive_integer(value, maximum):
    return (
        isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum
    )


def _normalize_items(items):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise InvalidReservation(
            _("A reservation must contain between 1 and 100 items.")
        )

    requested = {}

    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "external_book_id",
            "quantity",
        }:
            raise InvalidReservation(
                _("Each item must contain external_book_id and quantity.")
            )

        book_id = item["external_book_id"]
        quantity = item["quantity"]

        if not _positive_integer(book_id, MAX_EXTERNAL_ID):
            raise InvalidReservation(_("Invalid book ID."))

        if not _positive_integer(quantity, MAX_QUANTITY):
            raise InvalidReservation(_("Invalid book quantity."))

        if book_id in requested:
            raise InvalidReservation(
                _("Each book must appear only once in a reservation.")
            )

        requested[book_id] = quantity

    return requested


@transaction.atomic
def reserve_stock(*, created_by, external_order_id, items):
    """Reserve an entire order and return (reservation, created)."""

    if not _positive_integer(external_order_id, MAX_EXTERNAL_ID):
        raise InvalidReservation(_("Invalid order ID."))

    requested = _normalize_items(items)

    reservation, created = Reservation.objects.select_for_update().get_or_create(
        created_by=created_by,
        external_order_id=external_order_id,
        defaults={"expires_at": timezone.now() + RESERVATION_TTL},
    )

    if not created:
        existing_items = dict(
            reservation.items.values_list(
                "stock_item__external_book_id",
                "quantity",
            )
        )

        if existing_items != requested:
            raise ReservationConflict(
                _("This order already has a reservation with different items.")
            )

        if (
            reservation.status != Reservation.Status.PENDING
            or reservation.expires_at <= timezone.now()
        ):
            raise ReservationConflict(_("This reservation is no longer active."))

        return reservation, False

    stock_items = list(
        StockItem.objects.select_for_update()
        .filter(external_book_id__in=requested)
        .order_by("pk")
    )

    found_ids = {item.external_book_id for item in stock_items}
    missing_ids = set(requested) - found_ids

    if missing_ids:
        raise StockUnavailable(
            _("Book %(book_id)s is not registered in the warehouse.")
            % {"book_id": min(missing_ids)}
        )

    for stock_item in stock_items:
        required = requested[stock_item.external_book_id]

        if stock_item.available < required:
            raise StockUnavailable(
                _("Not enough stock for book %(book_id)s.")
                % {"book_id": stock_item.external_book_id}
            )

    now = timezone.now()
    reservation_items = []

    for stock_item in stock_items:
        quantity = requested[stock_item.external_book_id]
        stock_item.reserved += quantity
        stock_item.updated_at = now

        reservation_items.append(
            ReservationItem(
                reservation=reservation,
                stock_item=stock_item,
                quantity=quantity,
            )
        )

    ReservationItem.objects.bulk_create(reservation_items)
    StockItem.objects.bulk_update(
        stock_items,
        fields=["reserved", "updated_at"],
    )

    transaction.on_commit(invalidate_stock_cache)
    transaction.on_commit(
        partial(
            logger.info,
            "Reservation %s created for order %s",
            str(reservation.pk),
            external_order_id,
        )
    )

    return reservation, True
