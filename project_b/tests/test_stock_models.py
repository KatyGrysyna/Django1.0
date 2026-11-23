import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from inventory.models import StockItem


@pytest.fixture
def stock_data():
    return {
        "external_book_id": 1,
        "title": "Test book",
        "quantity": 10,
        "reserved": 3,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("quantity", "reserved", "expected"),
    [
        (0, 0, 0),
        (10, 0, 10),
        (10, 3, 7),
        (10, 10, 0),
    ],
)
def test_available_quantity(stock_data, quantity, reserved, expected):
    stock_data.update(quantity=quantity, reserved=reserved)
    item = StockItem(**stock_data)

    assert item.available == expected


@pytest.mark.unit
def test_clean_rejects_quantity_below_reserved(stock_data):
    stock_data["quantity"] = 2
    item = StockItem(**stock_data)

    with pytest.raises(ValidationError) as exc:
        item.clean()

    assert "quantity" in exc.value.message_dict


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize("quantity", [0, 10])
def test_database_accepts_fully_reserved_stock(stock_data, quantity):
    stock_data.update(quantity=quantity, reserved=quantity)
    item = StockItem.objects.create(**stock_data)
    item.refresh_from_db()

    assert (item.quantity, item.reserved) == (quantity, quantity)


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_values",
    [
        {"external_book_id": 0},
        {"external_book_id": -1},
        {"quantity": -1, "reserved": 0},
        {"reserved": -1},
        {"reserved": 11},
    ],
)
def test_database_rejects_invalid_stock(stock_data, invalid_values):
    stock_data.update(invalid_values)

    with pytest.raises(IntegrityError), transaction.atomic():
        StockItem.objects.create(**stock_data)

    assert StockItem.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_database_rejects_duplicate_book(stock_data):
    StockItem.objects.create(**stock_data)

    with pytest.raises(IntegrityError), transaction.atomic():
        StockItem.objects.create(**stock_data)

    assert StockItem.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": 2},
        {"reserved": 11},
    ],
)
def test_invalid_update_preserves_previous_stock(stock_data, changes):
    item = StockItem.objects.create(**stock_data)

    with pytest.raises(IntegrityError), transaction.atomic():
        StockItem.objects.filter(pk=item.pk).update(**changes)

    item.refresh_from_db()

    assert (item.quantity, item.reserved) == (10, 3)