from datetime import timedelta
from uuid import UUID

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from inventory.models import Reservation, ReservationItem, StockItem

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def reservation_data(django_user_model):
    user = django_user_model.objects.create_user(username="bookshop_service")
    return {
        "external_order_id": 1001,
        "created_by": user,
        "expires_at": timezone.now() + timedelta(minutes=15),
    }


@pytest.fixture
def reservation(reservation_data):
    return Reservation.objects.create(**reservation_data)


@pytest.fixture
def stock_item():
    return StockItem.objects.create(
        external_book_id=101,
        title="First book",
        quantity=10,
    )


def test_reservation_can_contain_multiple_books(reservation, stock_item):
    second_book = StockItem.objects.create(
        external_book_id=102,
        title="Second book",
        quantity=5,
    )
    ReservationItem.objects.bulk_create(
        [
            ReservationItem(
                reservation=reservation,
                stock_item=stock_item,
                quantity=2,
            ),
            ReservationItem(
                reservation=reservation,
                stock_item=second_book,
                quantity=1,
            ),
        ]
    )

    reservation.refresh_from_db()

    assert isinstance(reservation.pk, UUID)
    assert reservation.status == Reservation.Status.PENDING
    assert dict(
        reservation.items.values_list("stock_item__external_book_id", "quantity")
    ) == {101: 2, 102: 1}


def test_order_cannot_be_reserved_twice_for_same_user(reservation, reservation_data):
    with pytest.raises(IntegrityError), transaction.atomic():
        Reservation.objects.create(**reservation_data)

    assert Reservation.objects.count() == 1
    assert Reservation.objects.filter(pk=reservation.pk).exists()


def test_same_order_number_allowed_for_other_user(
    reservation, reservation_data, django_user_model
):
    other_user = django_user_model.objects.create_user(username="other_service")
    second = Reservation.objects.create(
        **{**reservation_data, "created_by": other_user}
    )

    assert second.pk != reservation.pk
    assert second.external_order_id == reservation.external_order_id
    assert Reservation.objects.count() == 2


@pytest.mark.parametrize(
    "invalid_values",
    [
        {"external_order_id": 0},
        {"external_order_id": -1},
        {"status": "unknown"},
    ],
)
def test_database_rejects_invalid_reservation(reservation_data, invalid_values):
    reservation_data.update(invalid_values)

    with pytest.raises(IntegrityError), transaction.atomic():
        Reservation.objects.create(**reservation_data)

    assert Reservation.objects.count() == 0


def test_same_stock_item_cannot_repeat(reservation, stock_item):
    item = ReservationItem.objects.create(
        reservation=reservation,
        stock_item=stock_item,
        quantity=2,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ReservationItem.objects.create(
            reservation=reservation,
            stock_item=stock_item,
            quantity=1,
        )

    assert reservation.items.count() == 1
    item.refresh_from_db()
    assert item.quantity == 2


@pytest.mark.parametrize("quantity", [0, -1])
def test_database_rejects_invalid_item_quantity(reservation, stock_item, quantity):
    with pytest.raises(IntegrityError), transaction.atomic():
        ReservationItem.objects.create(
            reservation=reservation,
            stock_item=stock_item,
            quantity=quantity,
        )

    assert reservation.items.count() == 0


def test_invalid_quantity_update_preserves_item(reservation, stock_item):
    item = ReservationItem.objects.create(
        reservation=reservation,
        stock_item=stock_item,
        quantity=2,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ReservationItem.objects.filter(pk=item.pk).update(quantity=0)

    item.refresh_from_db()
    assert item.quantity == 2


@pytest.mark.parametrize("target", ["reservation", "stock_item", "created_by"])
def test_reservation_history_is_protected(reservation, stock_item, target):
    item = ReservationItem.objects.create(
        reservation=reservation,
        stock_item=stock_item,
        quantity=2,
    )
    protected_object = {
        "reservation": reservation,
        "stock_item": stock_item,
        "created_by": reservation.created_by,
    }[target]

    with pytest.raises(ProtectedError):
        protected_object.delete()

    assert Reservation.objects.filter(pk=reservation.pk).exists()
    assert ReservationItem.objects.filter(pk=item.pk).exists()
    assert StockItem.objects.filter(pk=stock_item.pk).exists()
