from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

import pytest
from django.db import connection, connections, transaction

from inventory.models import Reservation, ReservationItem, StockItem
from inventory.reservation_lifecycle import (
    confirm_reservation,
    release_reservation,
)
from inventory.services import (
    ReservationConflict,
    ReservationError,
    StockUnavailable,
    reserve_stock,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(username="concurrent_owner")


@pytest.fixture
def stock_item():
    return StockItem.objects.create(
        external_book_id=101,
        title="Last available book",
        quantity=1,
    )


def configure_connection():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("SET LOCAL statement_timeout = '15s'")
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


def run_overlapping(first_operation, second_operation):
    assert connection.vendor == "postgresql"

    second_started = Queue()

    def run_second():
        connections.close_all()

        try:
            with transaction.atomic():
                second_started.put(configure_connection())
                return second_operation()
        except ReservationError as exc:
            return exc
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            first_pid = configure_connection()
            first_result = first_operation()

            future = executor.submit(run_second)
            second_pid = second_started.get(timeout=10)

            assert first_pid != second_pid

            deadline = monotonic() + 5

            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_blocking_pids(%s)",
                        [second_pid],
                    )
                    blocking_pids = cursor.fetchone()[0]

                if first_pid in blocking_pids:
                    break

                if future.done():
                    future.result()
                    pytest.fail(
                        "The second operation finished without waiting "
                        "for the first transaction."
                    )

                sleep(0.02)
            else:
                pytest.fail(
                    "The second operation did not wait "
                    "for the first transaction's lock."
                )

        # The first transaction has committed and released its locks.
        return first_result, future.result(timeout=15)


def reserve_one(owner, order_id):
    return reserve_stock(
        created_by=owner,
        external_order_id=order_id,
        items=[{"external_book_id": 101, "quantity": 1}],
    )


def test_two_orders_cannot_reserve_the_last_book(owner, stock_item):
    first, second = run_overlapping(
        lambda: reserve_one(owner, 1001),
        lambda: reserve_one(owner, 1002),
    )

    reservation, created = first

    assert created is True
    assert isinstance(second, StockUnavailable)

    stock_item.refresh_from_db()
    reservation.refresh_from_db()

    assert stock_item.quantity == 1
    assert stock_item.reserved == 1
    assert stock_item.available == 0
    assert reservation.status == Reservation.Status.PENDING
    assert Reservation.objects.count() == 1
    assert ReservationItem.objects.count() == 1
    assert not Reservation.objects.filter(external_order_id=1002).exists()


def test_concurrent_duplicate_order_creates_one_reservation(owner, stock_item):
    first, second = run_overlapping(
        lambda: reserve_one(owner, 1001),
        lambda: reserve_one(owner, 1001),
    )

    first_reservation, first_created = first

    assert isinstance(second, tuple)
    second_reservation, second_created = second

    assert first_created is True
    assert second_created is False
    assert first_reservation.pk == second_reservation.pk
    assert first_reservation.expires_at == second_reservation.expires_at
    assert Reservation.objects.count() == 1
    assert ReservationItem.objects.count() == 1

    stock_item.refresh_from_db()

    assert stock_item.quantity == 1
    assert stock_item.reserved == 1


@pytest.mark.parametrize(
    ("first_action", "second_action", "expected_status", "expected_quantity"),
    [
        ("confirm", "release", "confirmed", 0),
        ("release", "confirm", "released", 1),
    ],
)
def test_confirm_and_release_cannot_both_succeed(
    owner,
    stock_item,
    first_action,
    second_action,
    expected_status,
    expected_quantity,
):
    reservation, _ = reserve_one(owner, 1001)

    operations = {
        "confirm": confirm_reservation,
        "release": release_reservation,
    }

    first, second = run_overlapping(
        lambda: operations[first_action](
            reservation_id=reservation.pk,
            created_by=owner,
        ),
        lambda: operations[second_action](
            reservation_id=reservation.pk,
            created_by=owner,
        ),
    )

    _, changed = first

    assert changed is True
    assert isinstance(second, ReservationConflict)

    reservation.refresh_from_db()
    stock_item.refresh_from_db()

    assert reservation.status == expected_status
    assert stock_item.quantity == expected_quantity
    assert stock_item.reserved == 0
    assert Reservation.objects.count() == 1
    assert ReservationItem.objects.count() == 1
