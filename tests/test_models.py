from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from .factories import (
    BookFactory,
    CategoryFactory,
    OrderItemFactory,
    UserFactory,
)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.django_db,
]


def test_category_string_representation():
    category = CategoryFactory.build(name='Фантастика')

    assert str(category) == 'Фантастика'


def test_book_string_representation():
    book = BookFactory.build(title='Кобзар')

    assert str(book) == 'Кобзар'


def test_category_rejects_duplicate_slug():
    CategoryFactory(slug='fiction')
    duplicate = CategoryFactory.build(slug='fiction')

    with pytest.raises(ValidationError) as error:
        duplicate.full_clean()

    assert 'slug' in error.value.message_dict


def test_book_rejects_negative_stock(category):
    book = BookFactory.build(category=category, stock=-1)

    with pytest.raises(ValidationError) as error:
        book.full_clean()

    assert 'stock' in error.value.message_dict


def test_new_order_is_pending(order):
    order.refresh_from_db()

    assert order.status == 'pending'
    assert order.stripe_session_id == ''


def test_empty_order_total_is_zero(order):
    assert order.get_total() == Decimal('0.00')


def test_order_total_includes_all_items_and_quantities(order):
    OrderItemFactory(
        order=order,
        price=Decimal('120.50'),
        quantity=2,
    )
    OrderItemFactory(
        order=order,
        price=Decimal('75.25'),
        quantity=3,
    )

    assert order.get_total() == Decimal('466.75')


def test_order_item_subtotal_preserves_decimal_precision():
    item = OrderItemFactory.build(
        price=Decimal('0.10'),
        quantity=3,
    )

    assert item.get_subtotal() == Decimal('0.30')


def test_order_total_keeps_purchase_price_when_book_price_changes(order):
    item = OrderItemFactory(
        order=order,
        price=Decimal('100.00'),
        quantity=2,
    )

    item.book.price = Decimal('250.00')
    item.book.save(update_fields=['price'])
    item.refresh_from_db()

    assert item.price == Decimal('100.00')
    assert order.get_total() == Decimal('200.00')


def test_user_rejects_phone_longer_than_twenty_characters():
    user = UserFactory.build(phone='1' * 21)

    with pytest.raises(ValidationError) as error:
        user.full_clean()

    assert 'phone' in error.value.message_dict