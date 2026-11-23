import logging

from celery import shared_task
from django.db import OperationalError
from django.utils import timezone

from .models import Reservation
from .reservation_lifecycle import (
    ReservationNotFound,
    expire_reservation,
)

logger = logging.getLogger(__name__)


@shared_task(
    name="inventory.expire_overdue_reservations",
    autoretry_for=(OperationalError,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=5,
    retry_backoff_max=60,
    retry_jitter=True,
    acks_late=True,
    soft_time_limit=45,
    time_limit=60,
)
def expire_overdue_reservations(batch_size=100):
    """Process a bounded batch of overdue reservations."""

    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= 500
    ):
        raise ValueError("batch_size must be an integer between 1 and 500.")

    reservation_ids = list(
        Reservation.objects.filter(
            status=Reservation.Status.PENDING,
            expires_at__lte=timezone.now(),
        )
        .order_by("expires_at", "id")
        .values_list("id", flat=True)[:batch_size]
    )

    expired_count = 0
    skipped_count = 0

    for reservation_id in reservation_ids:
        try:
            _, changed = expire_reservation(reservation_id=reservation_id)
        except ReservationNotFound:
            skipped_count += 1
            logger.warning(
                "Reservation %s disappeared before expiry processing",
                reservation_id,
            )
            continue

        if changed:
            expired_count += 1
        else:
            skipped_count += 1

    result = {
        "checked": len(reservation_ids),
        "expired": expired_count,
        "skipped": skipped_count,
    }

    logger.info(
        "Reservation expiry batch: checked=%s expired=%s skipped=%s",
        result["checked"],
        result["expired"],
        result["skipped"],
    )

    return result
