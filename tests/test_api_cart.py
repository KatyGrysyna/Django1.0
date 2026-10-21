from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Cart, CartItem
from .factories import BookFactory, UserFactory


pytestmark = pytest.mark.django_db


@pytest.fixture
def cart(user):
    return Cart.objects.create(user=user)


@pytest.mark.parametrize('method', ['get', 'post'])
def test_api_cart_requires_authentication(api_client, method):
    # Generated with AI, reviewed and modified
    response = getattr(api_client, method)(
        reverse('api:cart-list')
    )

    assert response.status_code == 401
    assert not Cart.objects.exists()


def test_api_user_can_create_empty_cart(auth_api_client, user):
    # Generated with AI, reviewed and modified
    response = auth_api_client.post(
        reverse('api:cart-list'),
        {},
        format='json',
    )

    assert response.status_code == 201
    assert response.data['user'] == user.pk
    assert response.data['items'] == []
    assert response.data['total'] == '0.00'
    assert Cart.objects.filter(user=user).count() == 1


def test_api_cart_creation_uses_current_user_and_database_prices(
    auth_api_client,
    user,
    book,
):
    # Generated with AI, reviewed and modified
    other_user = UserFactory()
    second_book = BookFactory(price=Decimal('12.45'))

    response = auth_api_client.post(
        reverse('api:cart-list'),
        {
            'user': other_user.pk,
            'total': '0.01',
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

    saved_cart = Cart.objects.get(pk=response.data['id'])
    quantities = dict(
        saved_cart.items.values_list('book_id', 'quantity')
    )

    assert saved_cart.user_id == user.pk
    assert quantities == {
        book.pk: 2,
        second_book.pk: 3,
    }
    assert saved_cart.get_total() == Decimal('237.35')
    assert response.data['total'] == '237.35'
    assert not Cart.objects.filter(user=other_user).exists()


def test_api_user_cannot_create_second_cart(
    auth_api_client,
    cart,
    book,
):
    # Generated with AI, reviewed and modified
    item = CartItem.objects.create(
        cart=cart,
        book=book,
        quantity=3,
    )

    response = auth_api_client.post(
        reverse('api:cart-list'),
        {
            'items': [
                {'book_id': book.pk, 'quantity': 7},
            ],
        },
        format='json',
    )

    assert response.status_code == 400
    assert Cart.objects.count() == 1
    assert Cart.objects.get().pk == cart.pk
    assert cart.items.count() == 1

    item.refresh_from_db()

    assert item.quantity == 3


def test_api_cart_list_contains_only_own_cart(
    auth_api_client,
    cart,
    book,
):
    # Generated with AI, reviewed and modified
    CartItem.objects.create(cart=cart, book=book, quantity=2)

    other_cart = Cart.objects.create(user=UserFactory())
    CartItem.objects.create(
        cart=other_cart,
        book=book,
        quantity=4,
    )

    response = auth_api_client.get(reverse('api:cart-list'))

    assert response.status_code == 200
    assert response.data['count'] == 1

    result = response.data['results'][0]

    assert result['id'] == cart.pk
    assert result['total'] == '200.00'
    assert len(result['items']) == 1
    assert result['items'][0]['quantity'] == 2
    assert result['items'][0]['subtotal'] == '200.00'
    assert result['items'][0]['book']['id'] == book.pk
    assert (
        result['items'][0]['book']['category']['id']
        == book.category_id
    )

    detail_response = auth_api_client.get(
        reverse('api:cart-detail', args=[cart.pk])
    )

    assert detail_response.status_code == 200
    assert detail_response.data == result


@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_api_user_cannot_access_another_cart(
    auth_api_client,
    book,
    method,
):
    # Generated with AI, reviewed and modified
    other_cart = Cart.objects.create(user=UserFactory())
    item = CartItem.objects.create(
        cart=other_cart,
        book=book,
        quantity=1,
    )
    url = reverse('api:cart-detail', args=[other_cart.pk])

    if method == 'patch':
        response = auth_api_client.patch(
            url,
            {
                'items': [
                    {'book_id': book.pk, 'quantity': 9},
                ],
            },
            format='json',
        )
    else:
        response = getattr(auth_api_client, method)(url)

    assert response.status_code == 404
    assert Cart.objects.filter(pk=other_cart.pk).exists()

    item.refresh_from_db()

    assert item.quantity == 1


@pytest.mark.parametrize('method', ['patch', 'put'])
def test_api_owner_can_replace_cart_items(
    auth_api_client,
    cart,
    book,
    method,
):
    # Generated with AI, reviewed and modified
    old_item = CartItem.objects.create(
        cart=cart,
        book=book,
        quantity=3,
    )
    new_book = BookFactory(price=Decimal('12.50'))

    response = getattr(auth_api_client, method)(
        reverse('api:cart-detail', args=[cart.pk]),
        {
            'items': [
                {'book_id': new_book.pk, 'quantity': 2},
            ],
        },
        format='json',
    )

    assert response.status_code == 200
    assert cart.items.count() == 1
    assert not CartItem.objects.filter(pk=old_item.pk).exists()

    saved_item = cart.items.get()

    assert saved_item.book_id == new_book.pk
    assert saved_item.quantity == 2
    assert response.data['total'] == '25.00'
    assert response.data['items'][0]['book']['id'] == new_book.pk


def test_api_owner_can_clear_cart(auth_api_client, cart, book):
    # Generated with AI, reviewed and modified
    CartItem.objects.create(cart=cart, book=book, quantity=2)

    response = auth_api_client.patch(
        reverse('api:cart-detail', args=[cart.pk]),
        {'items': []},
        format='json',
    )

    assert response.status_code == 200
    assert response.data['items'] == []
    assert response.data['total'] == '0.00'
    assert Cart.objects.filter(pk=cart.pk).exists()
    assert not cart.items.exists()


def test_api_cart_owner_cannot_be_changed(
    auth_api_client,
    cart,
    book,
    user,
):
    # Generated with AI, reviewed and modified
    item = CartItem.objects.create(
        cart=cart,
        book=book,
        quantity=2,
    )
    other_user = UserFactory()

    response = auth_api_client.patch(
        reverse('api:cart-detail', args=[cart.pk]),
        {'user': other_user.pk},
        format='json',
    )

    assert response.status_code == 200

    cart.refresh_from_db()
    item.refresh_from_db()

    assert cart.user_id == user.pk
    assert response.data['user'] == user.pk
    assert cart.items.count() == 1
    assert item.quantity == 2
    assert not Cart.objects.filter(user=other_user).exists()


@pytest.mark.parametrize(
    'case',
    [
        'zero_quantity',
        'negative_quantity',
        'duplicate_books',
        'missing_book_id',
    ],
)
def test_api_invalid_cart_update_preserves_items(
    auth_api_client,
    cart,
    book,
    case,
):
    # Generated with AI, reviewed and modified
    item = CartItem.objects.create(
        cart=cart,
        book=book,
        quantity=3,
    )

    invalid_items = {
        'zero_quantity': [
            {'book_id': book.pk, 'quantity': 0},
        ],
        'negative_quantity': [
            {'book_id': book.pk, 'quantity': -1},
        ],
        'duplicate_books': [
            {'book_id': book.pk, 'quantity': 1},
            {'book_id': book.pk, 'quantity': 2},
        ],
        'missing_book_id': [
            {'quantity': 2},
        ],
    }

    response = auth_api_client.patch(
        reverse('api:cart-detail', args=[cart.pk]),
        {'items': invalid_items[case]},
        format='json',
    )

    assert response.status_code == 400
    assert 'items' in response.data
    assert cart.items.count() == 1

    item.refresh_from_db()

    assert item.quantity == 3
    assert item.book_id == book.pk


def test_api_owner_can_delete_cart(auth_api_client, cart, book):
    # Generated with AI, reviewed and modified
    item = CartItem.objects.create(
        cart=cart,
        book=book,
        quantity=2,
    )

    response = auth_api_client.delete(
        reverse('api:cart-detail', args=[cart.pk])
    )

    assert response.status_code == 204
    assert not Cart.objects.filter(pk=cart.pk).exists()
    assert not CartItem.objects.filter(pk=item.pk).exists()


def test_api_cart_total_uses_current_book_price(
    auth_api_client,
    cart,
    book,
):
    # Generated with AI, reviewed and modified
    CartItem.objects.create(cart=cart, book=book, quantity=3)
    url = reverse('api:cart-detail', args=[cart.pk])

    first_response = auth_api_client.get(url)

    assert first_response.status_code == 200
    assert first_response.data['total'] == '300.00'

    book.price = Decimal('12.34')
    book.save(update_fields=['price'])

    second_response = auth_api_client.get(url)

    assert second_response.status_code == 200
    assert second_response.data['total'] == '37.02'
    assert second_response.data['items'][0]['subtotal'] == '37.02'
    assert second_response.data['items'][0]['book']['price'] == '12.34'