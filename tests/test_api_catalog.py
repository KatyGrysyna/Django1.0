from decimal import Decimal

import pytest
from django.urls import reverse

from catalog.models import Book, Category
from .factories import BookFactory


pytestmark = pytest.mark.django_db


@pytest.fixture
def book_payload(category):
    return {
        'title': 'API book',
        'author': 'Test author',
        'price': '125.50',
        'description': 'A book created through the API.',
        'stock': 5,
        'category_id': category.pk,
    }


def test_api_book_list_contains_nested_category(api_client, book):
    # Generated with AI, reviewed and modified
    response = api_client.get(reverse('api:book-list'))

    assert response.status_code == 200
    assert response.data['count'] == 1

    result = response.data['results'][0]

    assert result['id'] == book.pk
    assert result['title'] == book.title
    assert result['category'] == {
        'id': book.category.pk,
        'name': book.category.name,
        'slug': book.category.slug,
    }


def test_api_book_detail_is_public(api_client, book):
    # Generated with AI, reviewed and modified
    response = api_client.get(
        reverse('api:book-detail', args=[book.pk])
    )

    assert response.status_code == 200
    assert response.data['id'] == book.pk
    assert response.data['price'] == str(book.price)


def test_api_missing_book_returns_404(api_client, book):
    # Generated with AI, reviewed and modified
    response = api_client.get(
        reverse('api:book-detail', args=[book.pk + 1])
    )

    assert response.status_code == 404


def test_api_books_are_paginated_by_twenty(api_client, category):
    # Generated with AI, reviewed and modified
    books = BookFactory.create_batch(21, category=category)

    response = api_client.get(reverse('api:book-list'))

    assert response.status_code == 200
    assert response.data['count'] == 21
    assert len(response.data['results']) == 20
    assert response.data['previous'] is None
    assert response.data['next'] is not None
    assert [
        item['id'] for item in response.data['results']
    ] == [book.pk for book in books[:20]]

    second_page = api_client.get(response.data['next'])

    assert second_page.status_code == 200
    assert [
        item['id'] for item in second_page.data['results']
    ] == [books[20].pk]
    assert second_page.data['next'] is None
    assert second_page.data['previous'] is not None


@pytest.mark.parametrize('parameter', ['category', 'category_slug'])
def test_api_books_filter_by_category(api_client, book, parameter):
    # Generated with AI, reviewed and modified
    BookFactory()

    value = (
        book.category_id
        if parameter == 'category'
        else book.category.slug
    )

    response = api_client.get(
        reverse('api:book-list'),
        {parameter: value},
    )

    assert response.status_code == 200
    assert response.data['count'] == 1
    assert [
        item['id'] for item in response.data['results']
    ] == [book.pk]


@pytest.mark.parametrize(
    ('parameter', 'value'),
    [
        ('title', 'PYTHON'),
        ('author', 'aLiCe'),
    ],
)
def test_api_books_filter_by_text(api_client, parameter, value):
    # Generated with AI, reviewed and modified
    matching_book = BookFactory(
        title='Python Basics',
        author='Alice Smith',
    )
    BookFactory(
        title='Django Patterns',
        author='Bob Jones',
    )

    response = api_client.get(
        reverse('api:book-list'),
        {parameter: value},
    )

    assert response.status_code == 200
    assert response.data['count'] == 1
    assert [
        item['id'] for item in response.data['results']
    ] == [matching_book.pk]


def test_api_books_filter_by_price_range(api_client):
    # Generated with AI, reviewed and modified
    books = [
        BookFactory(price=Decimal(price))
        for price in ['99.99', '100.00', '200.00', '200.01']
    ]

    response = api_client.get(
        reverse('api:book-list'),
        {'min_price': '100.00', 'max_price': '200.00'},
    )

    assert response.status_code == 200
    assert response.data['count'] == 2
    assert [
        item['id'] for item in response.data['results']
    ] == [books[1].pk, books[2].pk]


def test_api_anonymous_user_cannot_create_book(api_client, book_payload):
    # Generated with AI, reviewed and modified
    response = api_client.post(
        reverse('api:book-list'),
        book_payload,
        format='json',
    )

    assert response.status_code == 401
    assert Book.objects.count() == 0


def test_api_regular_user_cannot_create_book(
    auth_api_client,
    book_payload,
):
    # Generated with AI, reviewed and modified
    response = auth_api_client.post(
        reverse('api:book-list'),
        book_payload,
        format='json',
    )

    assert response.status_code == 403
    assert Book.objects.count() == 0


def test_api_staff_can_create_book(staff_api_client, book_payload):
    # Generated with AI, reviewed and modified
    response = staff_api_client.post(
        reverse('api:book-list'),
        book_payload,
        format='json',
    )

    assert response.status_code == 201
    assert Book.objects.count() == 1

    saved_book = Book.objects.get(pk=response.data['id'])

    assert saved_book.title == book_payload['title']
    assert saved_book.price == Decimal('125.50')
    assert saved_book.stock == 5
    assert saved_book.category_id == book_payload['category_id']
    assert response.data['category']['id'] == saved_book.category_id
    assert 'category_id' not in response.data


def test_api_staff_can_update_book(staff_api_client, book):
    # Generated with AI, reviewed and modified
    response = staff_api_client.patch(
        reverse('api:book-detail', args=[book.pk]),
        {'title': 'Updated title', 'price': '175.50'},
        format='json',
    )

    assert response.status_code == 200

    book.refresh_from_db()

    assert book.title == 'Updated title'
    assert book.price == Decimal('175.50')


def test_api_staff_can_delete_book(staff_api_client, book):
    # Generated with AI, reviewed and modified
    response = staff_api_client.delete(
        reverse('api:book-detail', args=[book.pk])
    )

    assert response.status_code == 204
    assert not Book.objects.filter(pk=book.pk).exists()


@pytest.mark.parametrize('method', ['patch', 'delete'])
def test_api_regular_user_cannot_change_book(
    auth_api_client,
    book,
    method,
):
    # Generated with AI, reviewed and modified
    original_title = book.title

    response = getattr(auth_api_client, method)(
        reverse('api:book-detail', args=[book.pk]),
        {'title': 'Changed without permission'},
        format='json',
    )

    assert response.status_code == 403
    assert Book.objects.filter(pk=book.pk).exists()

    book.refresh_from_db()

    assert book.title == original_title


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('price', '-0.01'),
        ('price', '1.234'),
        ('stock', -1),
        ('category_id', 2147483647),
    ],
)
def test_api_book_rejects_invalid_data(
    staff_api_client,
    book_payload,
    field,
    value,
):
    # Generated with AI, reviewed and modified
    book_payload[field] = value

    response = staff_api_client.post(
        reverse('api:book-list'),
        book_payload,
        format='json',
    )

    assert response.status_code == 400
    assert field in response.data
    assert Book.objects.count() == 0


def test_api_categories_are_public(api_client, category):
    # Generated with AI, reviewed and modified
    expected = {
        'id': category.pk,
        'name': category.name,
        'slug': category.slug,
    }

    list_response = api_client.get(reverse('api:category-list'))

    assert list_response.status_code == 200
    assert list_response.data['count'] == 1
    assert list_response.data['results'] == [expected]

    detail_response = api_client.get(
        reverse('api:category-detail', args=[category.pk])
    )

    assert detail_response.status_code == 200
    assert detail_response.data == expected


def test_api_regular_user_cannot_create_category(auth_api_client):
    # Generated with AI, reviewed and modified
    response = auth_api_client.post(
        reverse('api:category-list'),
        {'name': 'Fiction', 'slug': 'fiction'},
        format='json',
    )

    assert response.status_code == 403
    assert Category.objects.count() == 0


def test_api_staff_can_manage_category(staff_api_client):
    # Generated with AI, reviewed and modified
    create_response = staff_api_client.post(
        reverse('api:category-list'),
        {'name': 'Fiction', 'slug': 'fiction'},
        format='json',
    )

    assert create_response.status_code == 201

    category_id = create_response.data['id']
    category = Category.objects.get(pk=category_id)

    assert category.name == 'Fiction'
    assert category.slug == 'fiction'

    detail_url = reverse('api:category-detail', args=[category_id])

    update_response = staff_api_client.patch(
        detail_url,
        {'name': 'Modern fiction'},
        format='json',
    )

    assert update_response.status_code == 200

    category.refresh_from_db()

    assert category.name == 'Modern fiction'

    delete_response = staff_api_client.delete(detail_url)

    assert delete_response.status_code == 204
    assert not Category.objects.filter(pk=category_id).exists()


def test_api_category_rejects_duplicate_slug(
    staff_api_client,
    category,
):
    # Generated with AI, reviewed and modified
    response = staff_api_client.post(
        reverse('api:category-list'),
        {'name': 'Another category', 'slug': category.slug},
        format='json',
    )

    assert response.status_code == 400
    assert 'slug' in response.data
    assert Category.objects.count() == 1