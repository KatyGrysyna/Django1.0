from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils.translation import override

from .factories import BookFactory, OrderItemFactory


pytestmark = [
    pytest.mark.unit,
    pytest.mark.django_db,
]


def test_book_round_trip_preserves_price_and_display_name(category):
    # Generated with AI, reviewed and modified
    book = BookFactory.build(
        category=category,
        title='Кобзар',
        price=Decimal('999999.99'),
    )

    book.full_clean()
    book.save()
    book.refresh_from_db()

    assert book.price == Decimal('999999.99')
    assert str(book) == 'Кобзар'


@pytest.mark.parametrize(
    'field, value',
    [
        pytest.param('title', 'x' * 201, id='long-title'),
        pytest.param('author', 'x' * 151, id='long-author'),
        pytest.param('price', Decimal('12.345'), id='decimal-places'),
        pytest.param('price', Decimal('1000000.00'), id='max-digits'),
    ],
)
def test_book_rejects_invalid_field_values(category, field, value):
    # Generated with AI, reviewed and modified
    book = BookFactory.build(
        category=category,
        **{field: value},
    )

    with pytest.raises(ValidationError) as error:
        book.full_clean()

    assert field in error.value.message_dict


def test_order_rejects_unknown_status(order):
    # Generated with AI, reviewed and modified
    order.status = 'unknown'

    with pytest.raises(ValidationError) as error:
        order.full_clean()

    assert 'status' in error.value.message_dict


def test_order_string_representation_in_ukrainian(order):
    # Generated with AI, reviewed and modified
    expected = f'Замовлення №{order.pk} ({order.user.username})'

    with override('uk'):
        assert str(order) == expected


def test_order_total_does_not_include_other_orders(order):
    # Generated with AI, reviewed and modified
    OrderItemFactory(
        order=order,
        quantity=2,
        price=Decimal('45.50'),
    )
    other_item = OrderItemFactory(
        quantity=3,
        price=Decimal('1000.00'),
    )

    assert other_item.order_id != order.pk
    assert order.get_total() == Decimal('91.00')


def test_order_item_rejects_negative_quantity(order, book):
    # Generated with AI, reviewed and modified
    item = OrderItemFactory.build(
        order=order,
        book=book,
        quantity=-1,
    )

    with pytest.raises(ValidationError) as error:
        item.full_clean()

    assert 'quantity' in error.value.message_dict


def test_order_item_displays_book_and_calculates_subtotal(book):
    # Generated with AI, reviewed and modified
    item = OrderItemFactory.build(
        book=book,
        quantity=3,
        price=Decimal('19.90'),
    )

    assert str(item) == f'{book.title} x3'
    assert item.get_subtotal() == Decimal('59.70')