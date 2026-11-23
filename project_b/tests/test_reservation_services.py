from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.utils import timezone

from inventory.models import Reservation, ReservationItem, StockItem
from inventory.services import (
    InvalidReservation,
    ReservationConflict,
    StockUnavailable,
    reserve_stock,
)
from inventory.stock_cache import CACHE_VERSION_KEY

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def item(book_id, quantity):
    return {"external_book_id": book_id, "quantity": quantity}


@pytest.fixture
def stock_items():
    return [
        StockItem.objects.create(
            external_book_id=101,
            title="First book",
            quantity=10,
            reserved=2,
        ),
        StockItem.objects.create(
            external_book_id=102,
            title="Second book",
            quantity=5,
            reserved=1,
        ),
    ]


@pytest.fixture
def reserve(django_user_model):
    user = django_user_model.objects.create_user(username="reservation_service")

    def create(items, order_id=1001):
        return reserve_stock(
            created_by=user,
            external_order_id=order_id,
            items=items,
        )

    return create


def assert_no_reservation(stock_items):
    assert not Reservation.objects.exists()
    assert not ReservationItem.objects.exists()

    for stock_item in stock_items:
        stock_item.refresh_from_db()

    assert [
        (stock_item.quantity, stock_item.reserved) for stock_item in stock_items
    ] == [(10, 2), (5, 1)]


def test_reserves_entire_order(reserve, stock_items):
    started = timezone.now()
    reservation, created = reserve([item(101, 2), item(102, 3)])

    assert created is True
    assert reservation.status == Reservation.Status.PENDING
    assert (
        started + timedelta(hours=1)
        <= reservation.expires_at
        <= timezone.now() + timedelta(hours=1)
    )
    assert dict(
        reservation.items.values_list("stock_item__external_book_id", "quantity")
    ) == {101: 2, 102: 3}

    for stock_item in stock_items:
        stock_item.refresh_from_db()

    assert [
        (stock_item.quantity, stock_item.reserved) for stock_item in stock_items
    ] == [(10, 4), (5, 4)]


def test_repeat_does_not_double_reserve(reserve, stock_items):
    first, first_created = reserve([item(101, 2), item(102, 3)])
    second, second_created = reserve([item(102, 3), item(101, 2)])

    assert first_created is True
    assert second_created is False
    assert second.pk == first.pk
    assert second.expires_at == first.expires_at
    assert Reservation.objects.count() == 1
    assert ReservationItem.objects.count() == 2

    for stock_item in stock_items:
        stock_item.refresh_from_db()

    assert [stock.reserved for stock in stock_items] == [4, 4]


def test_changed_order_items_are_rejected(reserve, stock_items):
    reservation, _ = reserve([item(101, 2)])

    with pytest.raises(ReservationConflict):
        reserve([item(101, 3)])

    stock_items[0].refresh_from_db()
    assert stock_items[0].reserved == 4
    assert reservation.items.get().quantity == 2
    assert Reservation.objects.count() == 1


@pytest.mark.parametrize(
    "state",
    ["confirmed", "released", "expired", "past_due"],
)
def test_inactive_reservation_cannot_be_reused(reserve, stock_items, state):
    reservation, _ = reserve([item(101, 2)])
    queryset = Reservation.objects.filter(pk=reservation.pk)

    if state == "past_due":
        queryset.update(expires_at=timezone.now() - timedelta(seconds=1))
    else:
        queryset.update(status=state)

    with pytest.raises(ReservationConflict):
        reserve([item(101, 2)])

    stock_items[0].refresh_from_db()
    assert stock_items[0].reserved == 4
    assert Reservation.objects.count() == 1
    assert ReservationItem.objects.count() == 1


@pytest.mark.parametrize(
    "second_request",
    [item(102, 5), item(999, 1)],
    ids=["insufficient-stock", "unknown-book"],
)
def test_unavailable_book_rolls_back_entire_order(reserve, stock_items, second_request):
    with pytest.raises(StockUnavailable):
        reserve([item(101, 2), second_request])

    assert_no_reservation(stock_items)


def test_write_failure_rolls_back_saved_changes(reserve, stock_items):
    original_bulk_update = StockItem.objects.bulk_update

    def fail_after_update(*args, **kwargs):
        original_bulk_update(*args, **kwargs)
        raise DatabaseError("Simulated write failure")

    with patch(
        "inventory.services.StockItem.objects.bulk_update",
        side_effect=fail_after_update,
    ):
        with pytest.raises(DatabaseError, match="Simulated write failure"):
            reserve([item(101, 2), item(102, 3)])

    assert_no_reservation(stock_items)


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"external_book_id": 101}],
        [item(0, 1)],
        [item(101, 0)],
        [item(101, -1)],
        [item(101, True)],
        [item(101, 1), item(101, 2)],
    ],
    ids=[
        "empty-order",
        "missing-quantity",
        "invalid-book-id",
        "zero-quantity",
        "negative-quantity",
        "boolean-quantity",
        "duplicate-book",
    ],
)
def test_invalid_items_do_not_change_stock(reserve, stock_items, items):
    with pytest.raises(InvalidReservation):
        reserve(items)

    assert_no_reservation(stock_items)


@pytest.mark.parametrize("order_id", [0, True])
def test_invalid_order_id_does_not_change_stock(reserve, stock_items, order_id):
    with pytest.raises(InvalidReservation):
        reserve([item(101, 2)], order_id=order_id)

    assert_no_reservation(stock_items)


def test_cache_and_log_update_after_commit(
    reserve,
    stock_items,
    django_capture_on_commit_callbacks,
    caplog,
):
    cache.set(CACHE_VERSION_KEY, "before", timeout=None)
    caplog.set_level("INFO", logger="inventory.services")

    with django_capture_on_commit_callbacks(execute=True):
        reservation, _ = reserve([item(101, 2)])

        assert cache.get(CACHE_VERSION_KEY) == "before"
        assert str(reservation.pk) not in caplog.text

    assert cache.get(CACHE_VERSION_KEY) not in (None, "before")
    assert str(reservation.pk) in caplog.text


def test_outer_rollback_preserves_stock_and_cache(
    reserve,
    stock_items,
    django_capture_on_commit_callbacks,
):
    cache.set(CACHE_VERSION_KEY, "before", timeout=None)

    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError, match="Cancel outer transaction"):
            with transaction.atomic():
                reserve([item(101, 2)])
                raise RuntimeError("Cancel outer transaction")

    assert cache.get(CACHE_VERSION_KEY) == "before"
    assert_no_reservation(stock_items)
