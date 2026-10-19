from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils.translation import override
from pytest_django.asserts import assertContains, assertRedirects

from accounts.models import CustomUser
from catalog.models import Book

from .factories import BookFactory


pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db,
]


@pytest.fixture(autouse=True)
def ukrainian_language():
    with override('uk'):
        yield


@pytest.fixture
def editor(user):
    permissions = Permission.objects.filter(
        content_type__app_label='catalog',
        codename__in=['add_book', 'change_book', 'delete_book'],
    )
    user.user_permissions.set(permissions)
    return user


@pytest.fixture
def book_data(category):
    return {
        'title': 'Нова книга',
        'author': 'Тестовий автор',
        'price': '150.00',
        'description': 'Опис книги',
        'stock': '4',
        'category': str(category.pk),
    }


def test_registration_then_login(client):
    password = 'BookshopTest!42'

    response = client.post(
        '/uk/accounts/register/',
        {
            'username': 'new_reader',
            'email': 'new_reader@example.com',
            'password1': password,
            'password2': password,
        },
        follow=True,
    )

    assertRedirects(response, '/uk/accounts/login/')
    user = CustomUser.objects.get(username='new_reader')

    response = client.post(
        '/uk/accounts/login/',
        {'username': user.username, 'password': password},
        follow=True,
    )

    assertRedirects(response, '/uk/')
    assert client.session['_auth_user_id'] == str(user.pk)
    assertContains(response, user.username)


def test_login_with_wrong_password_then_correct_password(client, user):
    response = client.post(
        '/uk/accounts/login/',
        {'username': user.username, 'password': 'wrong-password'},
    )

    assert response.status_code == 200
    assert response.context['form'].non_field_errors()
    assert '_auth_user_id' not in client.session

    response = client.post(
        '/uk/accounts/login/',
        {'username': user.username, 'password': 'TestPass123!'},
        follow=True,
    )

    assertRedirects(response, '/uk/')
    assert client.session['_auth_user_id'] == str(user.pk)


def test_logout_removes_authentication(client, user):
    client.force_login(user)

    response = client.post('/uk/accounts/logout/', follow=True)

    assertRedirects(response, '/uk/')
    assert '_auth_user_id' not in client.session
    assert response.context['user'].is_anonymous

    response = client.get('/uk/book/create/')

    assertRedirects(
        response,
        '/uk/accounts/login/?next=/uk/book/create/',
    )


def test_user_without_permission_cannot_create_book(client, user, book_data):
    client.force_login(user)

    response = client.get('/uk/book/create/')
    assert response.status_code == 403

    response = client.post('/uk/book/create/', book_data)

    assert response.status_code == 403
    assert not Book.objects.exists()


def test_editor_creates_book_and_opens_details(client, editor, book_data):
    client.force_login(editor)

    response = client.post('/uk/book/create/', book_data)

    assertRedirects(response, '/uk/')

    book = Book.objects.get(title=book_data['title'])
    assert book.price == Decimal('150.00')

    response = client.get(f'/uk/book/{book.pk}/')

    assertContains(response, book_data['title'])
    assertContains(response, book_data['author'])


def test_editor_updates_book_and_sees_changes(
    client,
    editor,
    book,
    book_data,
):
    client.force_login(editor)
    book_data['title'] = 'Оновлена книга'
    book_data['price'] = '199.90'

    response = client.post(
        f'/uk/book/{book.pk}/update/',
        book_data,
    )

    assertRedirects(response, '/uk/')

    book.refresh_from_db()
    assert book.title == 'Оновлена книга'
    assert book.price == Decimal('199.90')

    response = client.get(f'/uk/book/{book.pk}/')

    assertContains(response, 'Оновлена книга')


def test_editor_confirms_and_deletes_book(client, editor, book):
    client.force_login(editor)
    book_id = book.pk

    response = client.get(f'/uk/book/{book_id}/delete/')

    assertContains(response, book.title)
    assert Book.objects.filter(pk=book_id).exists()

    response = client.post(f'/uk/book/{book_id}/delete/')

    assertRedirects(response, '/uk/')
    assert not Book.objects.filter(pk=book_id).exists()

    response = client.get(f'/uk/book/{book_id}/')
    assert response.status_code == 404


def test_category_filter_is_preserved_on_second_page(client, category):
    books = BookFactory.create_batch(7, category=category)
    BookFactory.create_batch(2)

    response = client.get('/uk/', {'category': category.slug})

    assert response.status_code == 200
    assert list(response.context['books']) == books[:6]
    assertContains(
        response,
        f'href="?page=2&amp;category={category.slug}"',
    )

    response = client.get(
        '/uk/',
        {'category': category.slug, 'page': 2},
    )

    assert response.status_code == 200
    assert list(response.context['books']) == books[6:]
    assert response.context['selected_category'] == category.slug


def test_language_switch_changes_page_and_remembers_choice(client):
    response = client.get('/uk/')
    assertContains(response, 'Каталог книг')

    response = client.post(
        reverse('set_language'),
        {'language': 'en', 'next': '/uk/'},
        follow=True,
    )

    assertRedirects(response, '/en/')
    assertContains(response, 'Book catalog')
    assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == 'en'

    response = client.get('/', follow=True)

    assertRedirects(response, '/en/')
    assertContains(response, 'Book catalog')