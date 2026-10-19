from decimal import Decimal
from smtplib import SMTPException
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe
from django.utils.translation import override
from pytest_django.asserts import assertContains, assertRedirects

from catalog.models import Order

from .factories import BookFactory, UserFactory


pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db,
]


@pytest.fixture(autouse=True)
def services():
    with (
        override('uk'),
        patch('catalog.views.stripe.checkout.Session.create') as create,
        patch('catalog.views.stripe.checkout.Session.retrieve') as retrieve,
        patch('catalog.views.send_mail') as email,
    ):
        create.return_value = SimpleNamespace(
            id='cs_test_checkout',
            url='https://checkout.stripe.com/c/pay/cs_test_checkout',
        )
        retrieve.return_value = SimpleNamespace(
            payment_status='paid',
            currency='uah',
            amount_total=20000,
        )
        email.return_value = 1

        yield SimpleNamespace(
            create=create,
            retrieve=retrieve,
            email=email,
        )


@pytest.fixture
def checkout_order(client, user, book, services):
    client.force_login(user)

    for _ in range(2):
        response = client.get(f'/uk/cart/add/{book.pk}/')
        assert response.status_code == 302

    response = client.get('/uk/checkout/')

    assert response.status_code == 303
    assert response.url == services.create.return_value.url

    return Order.objects.get(user=user)


def test_cart_add_twice_then_remove(client, book, settings):
    settings.SESSION_SAVE_EVERY_REQUEST = True

    client.get(f'/uk/cart/add/{book.pk}/', follow=True)
    response = client.get(
        f'/uk/cart/add/{book.pk}/',
        follow=True,
    )

    assertContains(response, book.title)
    assert client.session['cart'][str(book.pk)]['quantity'] == 2
    assert client.session['cart'][str(book.pk)]['price'] == '100.00'
    assert response.context['cart'].get_total_price() == Decimal('200.00')

    response = client.get(
        f'/uk/cart/remove/{book.pk}/',
        follow=True,
    )

    assertContains(response, 'Кошик порожній.')
    assert client.session['cart'] == {}


def test_cart_clear_removes_all_books(client, book):
    second_book = BookFactory()

    client.get(f'/uk/cart/add/{book.pk}/')
    client.get(f'/uk/cart/add/{second_book.pk}/')

    assert len(client.session['cart']) == 2

    response = client.get('/uk/cart/clear/', follow=True)

    assertContains(response, 'Кошик порожній.')
    assert client.session['cart'] == {}
    assert len(response.context['cart']) == 0


def test_empty_cart_does_not_create_order(client, user, services):
    client.force_login(user)

    response = client.get('/uk/checkout/')

    assertRedirects(response, '/uk/cart/')
    assert not Order.objects.exists()
    services.create.assert_not_called()
    services.email.assert_not_called()


def test_checkout_creates_order_and_correct_stripe_request(
    checkout_order,
    book,
    services,
):
    assert checkout_order.status == 'pending'
    assert checkout_order.stripe_session_id == 'cs_test_checkout'
    assert checkout_order.get_total() == Decimal('200.00')

    item = checkout_order.items.get()

    assert item.book_id == book.pk
    assert item.quantity == 2
    assert item.price == Decimal('100.00')

    services.create.assert_called_once()
    arguments = services.create.call_args.kwargs

    assert arguments['mode'] == 'payment'
    assert arguments['line_items'] == [
        {
            'price_data': {
                'currency': 'uah',
                'product_data': {'name': book.title},
                'unit_amount': 10000,
            },
            'quantity': 2,
        }
    ]
    assert arguments['success_url'] == (
        'http://testserver/uk/checkout/success/'
        f'?order_id={checkout_order.pk}'
    )
    assert arguments['cancel_url'] == (
        'http://testserver/uk/checkout/cancel/'
    )

    services.retrieve.assert_not_called()
    services.email.assert_not_called()


def test_paid_order_sends_email_once_and_preserves_new_cart(
    client,
    checkout_order,
    user,
    book,
    services,
):
    response = client.get(
        '/uk/checkout/success/',
        {'order_id': checkout_order.pk},
    )

    assertContains(response, 'Оплата успішна!')

    checkout_order.refresh_from_db()
    assert checkout_order.status == 'paid'
    assert client.session['cart'] == {}

    services.email.assert_called_once_with(
        subject='Дякуємо за замовлення',
        message=(
            f'Замовлення #{checkout_order.pk} оплачено.\n'
            'Сума: 200.00 грн'
        ),
        from_email=None,
        recipient_list=[user.email],
    )

    client.get(f'/uk/cart/add/{book.pk}/')

    response = client.get(
        '/uk/checkout/success/',
        {'order_id': checkout_order.pk},
    )

    assertContains(response, 'Оплата успішна!')
    assert client.session['cart'][str(book.pk)]['quantity'] == 1

    services.retrieve.assert_called_once_with('cs_test_checkout')
    services.email.assert_called_once()


def test_unpaid_session_keeps_order_pending_and_cart_unchanged(
    client,
    checkout_order,
    book,
    services,
):
    services.retrieve.return_value.payment_status = 'unpaid'

    response = client.get(
        '/uk/checkout/success/',
        {'order_id': checkout_order.pk},
    )

    assertRedirects(response, '/uk/cart/')

    checkout_order.refresh_from_db()
    assert checkout_order.status == 'pending'
    assert client.session['cart'][str(book.pk)]['quantity'] == 2

    services.retrieve.assert_called_once_with('cs_test_checkout')
    services.email.assert_not_called()


@pytest.mark.parametrize(
    'currency, amount_total',
    [
        ('usd', 20000),
        ('uah', 1),
    ],
)
def test_payment_with_wrong_currency_or_amount_is_rejected(
    client,
    checkout_order,
    book,
    services,
    currency,
    amount_total,
):
    services.retrieve.return_value.currency = currency
    services.retrieve.return_value.amount_total = amount_total

    response = client.get(
        '/uk/checkout/success/',
        {'order_id': checkout_order.pk},
    )

    assert response.status_code == 403

    checkout_order.refresh_from_db()
    assert checkout_order.status == 'pending'
    assert client.session['cart'][str(book.pk)]['quantity'] == 2

    services.email.assert_not_called()


def test_user_cannot_confirm_another_users_order(
    client,
    checkout_order,
    services,
):
    another_user = UserFactory()
    client.force_login(another_user)

    response = client.get(
        '/uk/checkout/success/',
        {'order_id': checkout_order.pk},
    )

    assert response.status_code == 404

    checkout_order.refresh_from_db()
    assert checkout_order.status == 'pending'

    services.retrieve.assert_not_called()
    services.email.assert_not_called()


def test_stripe_connection_error_keeps_order_pending(
    client,
    checkout_order,
    book,
    services,
):
    services.retrieve.side_effect = stripe.APIConnectionError(
        'Test connection failure',
    )

    response = client.get(
        '/uk/checkout/success/',
        {'order_id': checkout_order.pk},
    )

    assertRedirects(response, '/uk/cart/')

    checkout_order.refresh_from_db()
    assert checkout_order.status == 'pending'
    assert client.session['cart'][str(book.pk)]['quantity'] == 2

    services.email.assert_not_called()


def test_email_failure_does_not_undo_confirmed_payment(
    client,
    checkout_order,
    services,
):
    services.email.side_effect = SMTPException('Test email failure')

    response = client.get(
        '/uk/checkout/success/',
        {'order_id': checkout_order.pk},
    )

    assertContains(response, 'Оплата успішна!')

    checkout_order.refresh_from_db()
    assert checkout_order.status == 'paid'
    assert client.session['cart'] == {}

    services.email.assert_called_once()