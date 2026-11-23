from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

from inventory.models import Reservation, StockItem
from inventory.reservation_lifecycle import (
    ReservationNotFound,
    StockIntegrityError,
    confirm_reservation,
    expire_reservation,
    release_reservation,
)
from inventory.services import ReservationConflict, reserve_stock
from inventory.stock_cache import CACHE_VERSION_KEY

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def reserved_order(django_user_model):
    owner = django_user_model.objects.create_user(username="lifecycle_owner")
    stocks = [
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
    reservation, _ = reserve_stock(
        created_by=owner,
        external_order_id=1001,
        items=[
            {"external_book_id": 101, "quantity": 2},
            {"external_book_id": 102, "quantity": 3},
        ],
    )
    return owner, reservation, stocks


def finish(action, owner, reservation_id):
    if action == "expire":
        return expire_reservation(reservation_id=reservation_id)

    operation = {
        "confirm": confirm_reservation,
        "release": release_reservation,
    }[action]
    return operation(
        reservation_id=reservation_id,
        created_by=owner,
    )


def make_overdue(reservation):
    Reservation.objects.filter(pk=reservation.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )


def stock_state(stocks):
    for stock in stocks:
        stock.refresh_from_db()
    return [(stock.quantity, stock.reserved) for stock in stocks]


def assert_pending(reservation, stocks):
    reservation.refresh_from_db()
    assert reservation.status == Reservation.Status.PENDING
    assert stock_state(stocks) == [(10, 4), (5, 4)]
    assert reservation.items.count() == 2


@pytest.mark.parametrize(
    ("action", "expected_status", "expected_stock"),
    [
        ("confirm", "confirmed", [(8, 2), (2, 1)]),
        ("release", "released", [(10, 2), (5, 1)]),
        ("expire", "expired", [(10, 2), (5, 1)]),
    ],
)
def test_operation_changes_stock_only_once(
    reserved_order, action, expected_status, expected_stock
):
    owner, reservation, stocks = reserved_order

    if action == "expire":
        make_overdue(reservation)

    first, first_changed = finish(action, owner, reservation.pk)
    second, second_changed = finish(action, owner, reservation.pk)

    assert first_changed is True
    assert second_changed is False
    assert first.pk == second.pk == reservation.pk

    reservation.refresh_from_db()
    assert reservation.status == expected_status
    assert reservation.items.count() == 2
    assert stock_state(stocks) == expected_stock


@pytest.mark.parametrize("action", ["confirm", "release"])
def test_other_user_cannot_modify_reservation(
    reserved_order, django_user_model, action
):
    _, reservation, stocks = reserved_order
    other_user = django_user_model.objects.create_user(username="other_lifecycle_user")

    with pytest.raises(ReservationNotFound):
        finish(action, other_user, reservation.pk)

    assert_pending(reservation, stocks)


@pytest.mark.parametrize("action", ["confirm", "release", "expire"])
def test_unknown_reservation_is_rejected(reserved_order, action):
    owner, reservation, stocks = reserved_order

    with pytest.raises(ReservationNotFound):
        finish(action, owner, uuid4())

    assert_pending(reservation, stocks)


def test_active_reservation_is_not_expired(reserved_order):
    owner, reservation, stocks = reserved_order

    result, changed = finish("expire", owner, reservation.pk)

    assert changed is False
    assert result.pk == reservation.pk
    assert_pending(reservation, stocks)


def test_confirmation_after_deadline_is_rejected(reserved_order):
    owner, reservation, stocks = reserved_order
    make_overdue(reservation)

    with pytest.raises(ReservationConflict):
        finish("confirm", owner, reservation.pk)

    assert_pending(reservation, stocks)


@pytest.mark.parametrize(
    ("initial_action", "forbidden_action"),
    [
        ("release", "confirm"),
        ("expire", "confirm"),
        ("confirm", "release"),
    ],
)
def test_invalid_transition_preserves_completed_reservation(
    reserved_order, initial_action, forbidden_action
):
    owner, reservation, stocks = reserved_order

    if initial_action == "expire":
        make_overdue(reservation)

    completed, _ = finish(initial_action, owner, reservation.pk)
    before = stock_state(stocks)

    with pytest.raises(ReservationConflict):
        finish(forbidden_action, owner, reservation.pk)

    reservation.refresh_from_db()
    assert reservation.status == completed.status
    assert stock_state(stocks) == before


@pytest.mark.parametrize(
    ("initial_action", "cleanup_action"),
    [
        ("confirm", "expire"),
        ("release", "expire"),
        ("expire", "release"),
    ],
)
def test_cleanup_does_not_change_completed_reservation(
    reserved_order, initial_action, cleanup_action
):
    owner, reservation, stocks = reserved_order

    if initial_action == "expire":
        make_overdue(reservation)

    completed, _ = finish(initial_action, owner, reservation.pk)
    before = stock_state(stocks)
    make_overdue(reservation)

    result, changed = finish(cleanup_action, owner, reservation.pk)

    assert changed is False
    assert result.status == completed.status
    assert stock_state(stocks) == before


@pytest.mark.parametrize("action", ["confirm", "release", "expire"])
def test_inconsistent_counter_prevents_partial_changes(reserved_order, action):
    owner, reservation, stocks = reserved_order

    if action == "expire":
        make_overdue(reservation)

    StockItem.objects.filter(pk=stocks[1].pk).update(reserved=2)

    with pytest.raises(StockIntegrityError):
        finish(action, owner, reservation.pk)

    reservation.refresh_from_db()
    assert reservation.status == Reservation.Status.PENDING
    assert stock_state(stocks) == [(10, 4), (5, 2)]


@pytest.mark.parametrize("action", ["confirm", "release", "expire"])
def test_status_write_failure_rolls_back_stock_and_status(reserved_order, action):
    owner, reservation, stocks = reserved_order

    if action == "expire":
        make_overdue(reservation)

    original_save = Reservation.save

    def fail_after_save(instance, *args, **kwargs):
        original_save(instance, *args, **kwargs)
        raise DatabaseError("Simulated status write failure")

    with patch(
        "inventory.reservation_lifecycle.Reservation.save",
        new=fail_after_save,
    ):
        with pytest.raises(DatabaseError, match="Simulated status write failure"):
            finish(action, owner, reservation.pk)

    assert_pending(reservation, stocks)


@pytest.mark.parametrize("action", ["confirm", "release", "expire"])
def test_cache_and_log_change_after_commit(
    reserved_order,
    action,
    django_capture_on_commit_callbacks,
    caplog,
):
    owner, reservation, _ = reserved_order

    if action == "expire":
        make_overdue(reservation)

    cache.set(CACHE_VERSION_KEY, "before", timeout=None)
    caplog.set_level("INFO", logger="inventory.reservation_lifecycle")

    with django_capture_on_commit_callbacks(execute=True):
        finish(action, owner, reservation.pk)

        assert cache.get(CACHE_VERSION_KEY) == "before"
        assert str(reservation.pk) not in caplog.text

    assert cache.get(CACHE_VERSION_KEY) not in (None, "before")
    assert str(reservation.pk) in caplog.text
