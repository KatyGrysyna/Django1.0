from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Order, OrderItem
from .factories import (
    BookFactory,
    OrderFactory,
    OrderItemFactory,
    UserFactory,
)


pytestmark = pytest.mark.django_db


def test_api_orders_require_authentication(api_client):
    # Generated with AI, reviewed and modified
    response = api_client.get(reverse('api:order-list'))

    assert response.status_code == 401


def test_api_orders_show_only_own_orders_with_nested_items(
    auth_api_client,
    order,
):
    # Generated with AI, reviewed and modified
    item = OrderItemFactory(
        order=order,
        quantity=2,
        price=Decimal('12.50'),
    )
    OrderFactory()

    response = auth_api_client.get(reverse('api:order-list'))

    assert response.status_code == 200
    assert response.data['count'] == 1

    result = response.data['results'][0]

    assert result['id'] == order.pk
    assert result['user'] == order.user_id
    assert result['total'] == '25.00'
    assert len(result['items']) == 1
    assert result['items'][0]['price'] == '12.50'
    assert result['items'][0]['subtotal'] == '25.00'
    assert result['items'][0]['book']['id'] == item.book_id
    assert (
        result['items'][0]['book']['category']['id']
        == item.book.category_id
    )
    assert 'stripe_session_id' not in result

    detail_response = auth_api_client.get(
        reverse('api:order-detail', args=[order.pk])
    )

    assert detail_response.status_code == 200
    assert detail_response.data == result


@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_api_user_cannot_access_another_users_order(
    auth_api_client,
    method,
):
    # Generated with AI, reviewed and modified
    other_order = OrderFactory()
    item = OrderItemFactory(order=other_order, quantity=1)
    url = reverse('api:order-detail', args=[other_order.pk])

    if method == 'patch':
        response = auth_api_client.patch(
            url,
            {
                'items': [
                    {'book_id': item.book_id, 'quantity': 9},
                ],
            },
            format='json',
        )
    else:
        response = getattr(auth_api_client, method)(url)

    assert response.status_code == 404
    assert Order.objects.filter(pk=other_order.pk).exists()

    item.refresh_from_db()

    assert item.quantity == 1


def test_api_order_creation_uses_current_user_and_database_prices(
    auth_api_client,
    user,
    book,
):
    # Generated with AI, reviewed and modified
    other_user = UserFactory()
    second_book = BookFactory(price=Decimal('27.35'))

    response = auth_api_client.post(
        reverse('api:order-list'),
        {
            'user': other_user.pk,
            'status': 'paid',
            'stripe_session_id': 'forged-session',
            'items': [
                {
                    'book_id': book.pk,
                    'quantity': 2,
                    'price': '0.01',
                },
                {
                    'book_id': second_book.pk,
                    'quantity': 3,
                    'price': '0.01',
                },
            ],
        },
        format='json',
    )

    assert response.status_code == 201
    assert Order.objects.count() == 1

    saved_order = Order.objects.get(pk=response.data['id'])
    saved_items = {
        item.book_id: item
        for item in saved_order.items.all()
    }

    assert saved_order.user_id == user.pk
    assert saved_order.status == 'pending'
    assert saved_order.stripe_session_id == ''
    assert len(saved_items) == 2
    assert saved_items[book.pk].price == book.price
    assert saved_items[book.pk].quantity == 2
    assert saved_items[second_book.pk].price == Decimal('27.35')
    assert saved_items[second_book.pk].quantity == 3
    assert saved_order.get_total() == Decimal('282.05')
    assert response.data['total'] == '282.05'


def test_api_order_rejects_empty_items(auth_api_client):
    # Generated with AI, reviewed and modified
    response = auth_api_client.post(
        reverse('api:order-list'),
        {'items': []},
        format='json',
    )

    assert response.status_code == 400
    assert 'items' in response.data
    assert not Order.objects.exists()


@pytest.mark.parametrize('quantity', [0, -1])
def test_api_order_rejects_non_positive_quantity(
    auth_api_client,
    book,
    quantity,
):
    # Generated with AI, reviewed and modified
    response = auth_api_client.post(
        reverse('api:order-list'),
        {
            'items': [
                {'book_id': book.pk, 'quantity': quantity},
            ],
        },
        format='json',
    )

    assert response.status_code == 400
    assert 'items' in response.data
    assert not Order.objects.exists()


def test_api_order_rejects_duplicate_books(auth_api_client, book):
    # Generated with AI, reviewed and modified
    response = auth_api_client.post(
        reverse('api:order-list'),
        {
            'items': [
                {'book_id': book.pk, 'quantity': 1},
                {'book_id': book.pk, 'quantity': 2},
            ],
        },
        format='json',
    )

    assert response.status_code == 400
    assert 'items' in response.data
    assert not Order.objects.exists()


def test_api_owner_can_replace_pending_order_items(
    auth_api_client,
    order,
):
    # Generated with AI, reviewed and modified
    old_item = OrderItemFactory(order=order, quantity=3)
    new_book = BookFactory(price=Decimal('37.25'))

    response = auth_api_client.patch(
        reverse('api:order-detail', args=[order.pk]),
        {
            'items': [
                {'book_id': new_book.pk},
            ],
        },
        format='json',
    )

    assert response.status_code == 200
    assert order.items.count() == 1
    assert not OrderItem.objects.filter(pk=old_item.pk).exists()

    saved_item = order.items.get()

    assert saved_item.book_id == new_book.pk
    assert saved_item.quantity == 1
    assert saved_item.price == Decimal('37.25')
    assert response.data['total'] == '37.25'
    assert response.data['items'][0]['book']['id'] == new_book.pk


def test_api_invalid_order_update_preserves_existing_items(
    auth_api_client,
    order,
):
    # Generated with AI, reviewed and modified
    item = OrderItemFactory(
        order=order,
        quantity=3,
        price=Decimal('20.00'),
    )

    response = auth_api_client.patch(
        reverse('api:order-detail', args=[order.pk]),
        {'items': [{'quantity': 2}]},
        format='json',
    )

    assert response.status_code == 400
    assert 'items' in response.data
    assert order.items.count() == 1

    item.refresh_from_db()

    assert item.quantity == 3
    assert item.price == Decimal('20.00')


@pytest.mark.parametrize('method', ['patch', 'delete'])
@pytest.mark.parametrize(
    ('order_status', 'session_id'),
    [
        ('paid', ''),
        ('cancelled', ''),
        ('pending', 'cs_test_locked'),
    ],
)
def test_api_protected_order_cannot_be_changed(
    auth_api_client,
    order,
    method,
    order_status,
    session_id,
):
    # Generated with AI, reviewed and modified
    order.status = order_status
    order.stripe_session_id = session_id
    order.save(update_fields=['status', 'stripe_session_id'])

    item = OrderItemFactory(order=order, quantity=1)
    url = reverse('api:order-detail', args=[order.pk])

    if method == 'patch':
        response = auth_api_client.patch(
            url,
            {
                'items': [
                    {'book_id': item.book_id, 'quantity': 9},
                ],
            },
            format='json',
        )
    else:
        response = auth_api_client.delete(url)

    assert response.status_code == 400

    order.refresh_from_db()
    item.refresh_from_db()

    assert order.status == order_status
    assert order.stripe_session_id == session_id
    assert order.items.count() == 1
    assert item.quantity == 1


def test_api_owner_can_delete_pending_order(auth_api_client, order):
    # Generated with AI, reviewed and modified
    item = OrderItemFactory(order=order)

    response = auth_api_client.delete(
        reverse('api:order-detail', args=[order.pk])
    )

    assert response.status_code == 204
    assert not Order.objects.filter(pk=order.pk).exists()
    assert not OrderItem.objects.filter(pk=item.pk).exists()


def test_api_orders_filter_by_status(auth_api_client, user):
    # Generated with AI, reviewed and modified
    paid_order = OrderFactory(user=user, status='paid')
    OrderFactory(user=user, status='pending')
    OrderFactory(status='paid')

    response = auth_api_client.get(
        reverse('api:order-list'),
        {'status': 'paid'},
    )

    assert response.status_code == 200
    assert response.data['count'] == 1
    assert [
        item['id'] for item in response.data['results']
    ] == [paid_order.pk]


def test_api_orders_filter_by_creation_dates(auth_api_client, user):
    # Generated with AI, reviewed and modified
    orders = [OrderFactory(user=user) for _ in range(3)]

    for order, day in zip(orders, [9, 10, 11]):
        Order.objects.filter(pk=order.pk).update(
            created_at=datetime(
                2026, 1, day, 12, 0, tzinfo=timezone.utc
            )
        )

    response = auth_api_client.get(
        reverse('api:order-list'),
        {
            'created_after': '2026-01-10T00:00:00Z',
            'created_before': '2026-01-10T23:59:59Z',
        },
    )

    assert response.status_code == 200
    assert response.data['count'] == 1
    assert [
        item['id'] for item in response.data['results']
    ] == [orders[1].pk]