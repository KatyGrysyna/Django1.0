from datetime import timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.db import OperationalError
from django.utils import timezone

from inventory.models import Reservation, StockItem
from inventory.reservation_lifecycle import (
    ReservationNotFound,
    StockIntegrityError,
    confirm_reservation,
    expire_reservation,
    release_reservation,
)
from inventory.services import reserve_stock
from inventory.tasks import expire_overdue_reservations

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def stock():
    return StockItem.objects.create(
        external_book_id=101,
        title="Task test book",
        quantity=20,
    )


@pytest.fixture
def make_reservation(django_user_model, stock):
    owner = django_user_model.objects.create_user(username="task_owner")

    def create(order_id, *, overdue_minutes=None):
        reservation, _ = reserve_stock(
            created_by=owner,
            external_order_id=order_id,
            items=[{"external_book_id": 101, "quantity": 2}],
        )

        if overdue_minutes is not None:
            Reservation.objects.filter(pk=reservation.pk).update(
                expires_at=timezone.now() - timedelta(minutes=overdue_minutes)
            )
            reservation.refresh_from_db()

        return reservation

    return create


def test_task_processes_only_overdue_pending_reservations(make_reservation, stock):
    make_reservation(1, overdue_minutes=5)
    make_reservation(2)

    confirmed = make_reservation(3)
    confirm_reservation(
        reservation_id=confirmed.pk,
        created_by=confirmed.created_by,
    )

    released = make_reservation(4)
    release_reservation(
        reservation_id=released.pk,
        created_by=released.created_by,
    )

    Reservation.objects.filter(pk__in=[confirmed.pk, released.pk]).update(
        expires_at=timezone.now() - timedelta(minutes=10)
    )

    result = expire_overdue_reservations.run()

    assert result == {"checked": 1, "expired": 1, "skipped": 0}
    assert dict(Reservation.objects.values_list("external_order_id", "status")) == {
        1: "expired",
        2: "pending",
        3: "confirmed",
        4: "released",
    }

    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved) == (18, 2)


def test_repeated_task_does_not_release_stock_twice(make_reservation, stock):
    make_reservation(1, overdue_minutes=1)

    first = expire_overdue_reservations.run()
    second = expire_overdue_reservations.run()

    assert first == {"checked": 1, "expired": 1, "skipped": 0}
    assert second == {"checked": 0, "expired": 0, "skipped": 0}

    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved) == (20, 0)


def test_batch_limit_processes_oldest_reservation_first(make_reservation, stock):
    newer = make_reservation(1, overdue_minutes=1)
    older = make_reservation(2, overdue_minutes=10)

    first = expire_overdue_reservations.run(batch_size=1)

    assert first == {"checked": 1, "expired": 1, "skipped": 0}

    older.refresh_from_db()
    newer.refresh_from_db()
    assert older.status == "expired"
    assert newer.status == "pending"

    second = expire_overdue_reservations.run(batch_size=1)

    assert second == {"checked": 1, "expired": 1, "skipped": 0}
    newer.refresh_from_db()
    assert newer.status == "expired"

    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved) == (20, 0)


@pytest.mark.parametrize("batch_size", [0, 501, True, "10"])
def test_invalid_batch_size_does_not_change_reservations(
    make_reservation, stock, batch_size
):
    reservation = make_reservation(1, overdue_minutes=1)

    with pytest.raises(ValueError, match="batch_size"):
        expire_overdue_reservations.run(batch_size=batch_size)

    reservation.refresh_from_db()
    stock.refresh_from_db()
    assert reservation.status == "pending"
    assert (stock.quantity, stock.reserved) == (20, 2)


def test_task_rechecks_status_after_selecting_candidates(make_reservation, stock):
    reservation = make_reservation(1, overdue_minutes=1)

    def cancel_before_expiry(*, reservation_id):
        release_reservation(
            reservation_id=reservation_id,
            created_by=reservation.created_by,
        )
        return expire_reservation(reservation_id=reservation_id)

    with patch(
        "inventory.tasks.expire_reservation",
        side_effect=cancel_before_expiry,
    ):
        result = expire_overdue_reservations.run()

    assert result == {"checked": 1, "expired": 0, "skipped": 1}

    reservation.refresh_from_db()
    stock.refresh_from_db()
    assert reservation.status == "released"
    assert (stock.quantity, stock.reserved) == (20, 0)


def test_not_found_does_not_stop_remaining_reservations(
    make_reservation, stock, caplog
):
    missing = make_reservation(1, overdue_minutes=10)
    remaining = make_reservation(2, overdue_minutes=1)

    def expire_or_report_missing(*, reservation_id):
        if reservation_id == missing.pk:
            raise ReservationNotFound("Simulated missing reservation")
        return expire_reservation(reservation_id=reservation_id)

    with patch(
        "inventory.tasks.expire_reservation",
        side_effect=expire_or_report_missing,
    ):
        result = expire_overdue_reservations.run()

    assert result == {"checked": 2, "expired": 1, "skipped": 1}
    assert str(missing.pk) in caplog.text

    remaining.refresh_from_db()
    stock.refresh_from_db()
    assert remaining.status == "expired"
    assert (stock.quantity, stock.reserved) == (20, 2)


def test_retry_preserves_progress_and_next_run_finishes_remaining(
    make_reservation, stock
):
    older = make_reservation(1, overdue_minutes=10)
    newer = make_reservation(2, overdue_minutes=1)

    def fail_on_second_reservation(*, reservation_id):
        if reservation_id == newer.pk:
            raise OperationalError("Temporary database error")
        return expire_reservation(reservation_id=reservation_id)

    with patch(
        "inventory.tasks.expire_reservation",
        side_effect=fail_on_second_reservation,
    ):
        with patch.object(
            expire_overdue_reservations,
            "retry",
            side_effect=Retry(),
        ) as retry:
            with pytest.raises(Retry):
                expire_overdue_reservations.run()

    retry.assert_called_once()
    assert isinstance(retry.call_args.kwargs["exc"], OperationalError)

    older.refresh_from_db()
    newer.refresh_from_db()
    stock.refresh_from_db()

    assert older.status == "expired"
    assert newer.status == "pending"
    assert (stock.quantity, stock.reserved) == (20, 2)

    result = expire_overdue_reservations.run()

    assert result == {"checked": 1, "expired": 1, "skipped": 0}
    stock.refresh_from_db()
    assert (stock.quantity, stock.reserved) == (20, 0)


def test_integrity_failure_is_not_hidden_or_automatically_retried(
    make_reservation, stock
):
    reservation = make_reservation(1, overdue_minutes=1)
    StockItem.objects.filter(pk=stock.pk).update(reserved=0)

    with patch.object(expire_overdue_reservations, "retry") as retry:
        with pytest.raises(StockIntegrityError):
            expire_overdue_reservations.run()

    retry.assert_not_called()

    reservation.refresh_from_db()
    stock.refresh_from_db()
    assert reservation.status == "pending"
    assert (stock.quantity, stock.reserved) == (20, 0)
