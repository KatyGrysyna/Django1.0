from decimal import Decimal

import pytest

from accounts.forms import CustomUserCreationForm
from catalog.forms import BookForm

from .factories import UserFactory


pytestmark = [
    pytest.mark.unit,
    pytest.mark.django_db,
]


@pytest.fixture
def book_form_data(category):
    return {
        'title': 'Тестова книга',
        'author': 'Тестовий автор',
        'price': '123.45',
        'description': '',
        'stock': '3',
        'category': str(category.pk),
    }


@pytest.fixture
def registration_data():
    return {
        'username': 'new_reader',
        'email': 'new_reader@example.com',
        'password1': 'BookshopTest!42',
        'password2': 'BookshopTest!42',
    }


def test_book_form_saves_valid_data(book_form_data, category):
    form = BookForm(data=book_form_data)

    assert form.is_valid(), form.errors

    book = form.save()
    book.refresh_from_db()

    assert book.title == 'Тестова книга'
    assert book.price == Decimal('123.45')
    assert book.stock == 3
    assert book.category_id == category.pk
    assert book.description == ''


def test_book_form_requires_title(book_form_data):
    book_form_data['title'] = ''
    form = BookForm(data=book_form_data)

    assert not form.is_valid()
    assert form.has_error('title', 'required')


def test_book_form_rejects_non_numeric_price(book_form_data):
    book_form_data['price'] = 'abc'
    form = BookForm(data=book_form_data)

    assert not form.is_valid()
    assert form.has_error('price', 'invalid')


def test_book_form_rejects_negative_stock(book_form_data):
    book_form_data['stock'] = '-1'
    form = BookForm(data=book_form_data)

    assert not form.is_valid()
    assert form.has_error('stock', 'min_value')


def test_book_form_rejects_nonexistent_category(book_form_data):
    book_form_data['category'] = '-1'
    form = BookForm(data=book_form_data)

    assert not form.is_valid()
    assert form.has_error('category', 'invalid_choice')


def test_book_form_rejects_too_many_decimal_places(book_form_data):
    book_form_data['price'] = '123.456'
    form = BookForm(data=book_form_data)

    assert not form.is_valid()
    assert form.has_error('price', 'max_decimal_places')


def test_registration_saves_user_with_hashed_password(registration_data):
    form = CustomUserCreationForm(data=registration_data)

    assert form.is_valid(), form.errors

    user = form.save()
    user.refresh_from_db()

    assert user.username == 'new_reader'
    assert user.email == 'new_reader@example.com'
    assert user.check_password(registration_data['password1'])
    assert user.password != registration_data['password1']


def test_registration_rejects_mismatched_passwords(registration_data):
    registration_data['password2'] = 'DifferentPassword!42'
    form = CustomUserCreationForm(data=registration_data)

    assert not form.is_valid()
    assert form.has_error('password2', 'password_mismatch')


def test_registration_rejects_username_with_different_case(
    registration_data,
):
    UserFactory(username='Reader')
    registration_data['username'] = 'reader'
    form = CustomUserCreationForm(data=registration_data)

    assert not form.is_valid()
    assert form.has_error('username', 'unique')


def test_registration_rejects_invalid_email(registration_data):
    registration_data['email'] = 'not-an-email'
    form = CustomUserCreationForm(data=registration_data)

    assert not form.is_valid()
    assert form.has_error('email', 'invalid')