import json
from urllib.parse import parse_qs, urlsplit

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.urls import reverse
from django.utils.translation import override

from catalog import async_views, views

from .factories import BookFactory, CategoryFactory


pytestmark = [
    pytest.mark.unit,
    pytest.mark.django_db,
]


def test_book_list_returns_all_books_without_filter(rf):
    # Generated with AI, reviewed and modified
    first = BookFactory()
    second = BookFactory()

    request = rf.get('/uk/')
    view = views.BookListView()
    view.setup(request)

    result_ids = set(view.get_queryset().values_list('pk', flat=True))

    assert result_ids == {first.pk, second.pk}


def test_book_list_filters_by_category(rf, book):
    # Generated with AI, reviewed and modified
    BookFactory()

    request = rf.get('/uk/', {'category': book.category.slug})
    view = views.BookListView()
    view.setup(request)

    assert list(view.get_queryset()) == [book]


def test_book_detail_returns_requested_book(rf, book):
    # Generated with AI, reviewed and modified
    request = rf.get(f'/uk/book/{book.pk}/')

    response = views.BookDetailView.as_view()(request, pk=book.pk)

    assert response.status_code == 200
    assert response.context_data['book'] == book
    assert 'catalog/book_detail.html' in response.template_name


def test_book_detail_raises_404_for_missing_book(rf):
    # Generated with AI, reviewed and modified
    request = rf.get('/uk/book/999999/')

    with pytest.raises(Http404):
        views.BookDetailView.as_view()(request, pk=999999)


def test_book_create_redirects_anonymous_user_to_login(rf):
    # Generated with AI, reviewed and modified
    with override('uk'):
        request = rf.get(reverse('catalog:book_create'))
        request.user = AnonymousUser()

        response = views.BookCreateView.as_view()(request)
        login_url = reverse('accounts:login')

    assert response.status_code == 302

    destination = urlsplit(response.url)

    assert destination.path == login_url
    assert parse_qs(destination.query)['next'] == [request.path]


def test_book_create_denies_user_without_permission(rf, user):
    # Generated with AI, reviewed and modified
    request = rf.get('/uk/book/create/')
    request.user = user

    with pytest.raises(PermissionDenied):
        views.BookCreateView.as_view()(request)


def test_async_book_list_filters_by_category(rf, book):
    # Generated with AI, reviewed and modified
    BookFactory()

    request = rf.get(
        '/uk/api/books/',
        {'category': book.category.slug},
    )

    response = async_to_sync(async_views.book_list)(request)
    data = json.loads(response.content)

    assert response.status_code == 200
    assert [item['id'] for item in data['books']] == [book.pk]
    assert data['books'][0]['price'] == str(book.price)


def test_async_book_detail_returns_book_and_category(rf, book):
    # Generated with AI, reviewed and modified
    request = rf.get(f'/uk/api/books/{book.pk}/')

    response = async_to_sync(async_views.book_detail)(
        request,
        pk=book.pk,
    )
    data = json.loads(response.content)

    assert response.status_code == 200
    assert data['id'] == book.pk
    assert data['title'] == book.title
    assert data['price'] == str(book.price)
    assert data['category_name'] == book.category.name


def test_async_category_list_counts_books_and_includes_empty_category(
    rf,
    category,
):
    # Generated with AI, reviewed and modified
    BookFactory.create_batch(2, category=category)
    empty_category = CategoryFactory()

    request = rf.get('/uk/api/categories/')

    response = async_to_sync(async_views.category_list)(request)
    data = json.loads(response.content)

    counts = {
        item['id']: item['book_count']
        for item in data['categories']
    }

    assert response.status_code == 200
    assert counts == {
        category.pk: 2,
        empty_category.pk: 0,
    }


def test_async_book_detail_raises_404_for_missing_book(rf):
    # Generated with AI, reviewed and modified
    request = rf.get('/uk/api/books/999999/')

    with pytest.raises(Http404):
        async_to_sync(async_views.book_detail)(request, pk=999999)


@pytest.mark.parametrize(
    'page, positions, has_previous, has_next',
    [
        (1, [0, 1], False, True),
        (2, [2, 3], True, True),
        (3, [4], True, False),
    ],
)
def test_async_book_list_paginates_filtered_books(
    rf,
    category,
    page,
    positions,
    has_previous,
    has_next,
):
    # Generated with AI, reviewed and modified
    books = BookFactory.create_batch(5, category=category)
    BookFactory.create_batch(2)

    request = rf.get(
        '/uk/api/books/',
        {
            'category': category.slug,
            'page': page,
            'page_size': 2,
        },
    )

    response = async_to_sync(async_views.book_list)(request)
    data = json.loads(response.content)

    assert response.status_code == 200
    assert [item['id'] for item in data['books']] == [
        books[position].pk for position in positions
    ]
    assert data['pagination'] == {
        'page': page,
        'page_size': 2,
        'total': 5,
        'total_pages': 3,
        'has_next': has_next,
        'has_previous': has_previous,
    }


def test_async_book_list_handles_empty_catalog(rf):
    # Generated with AI, reviewed and modified
    request = rf.get('/uk/api/books/')

    response = async_to_sync(async_views.book_list)(request)
    data = json.loads(response.content)

    assert response.status_code == 200
    assert data == {
        'books': [],
        'pagination': {
            'page': 1,
            'page_size': 20,
            'total': 0,
            'total_pages': 1,
            'has_next': False,
            'has_previous': False,
        },
    }


@pytest.mark.parametrize(
    'parameter, value',
    [
        ('page', 'abc'),
        ('page', 0),
        ('page', -1),
        ('page_size', 'abc'),
        ('page_size', 0),
        ('page_size', 101),
    ],
)
def test_async_book_list_rejects_invalid_pagination(
    rf,
    parameter,
    value,
):
    # Generated with AI, reviewed and modified
    request = rf.get('/uk/api/books/', {parameter: value})

    response = async_to_sync(async_views.book_list)(request)
    data = json.loads(response.content)

    assert response.status_code == 400
    assert data.get('error')


def test_async_book_list_rejects_missing_page(rf, book):
    # Generated with AI, reviewed and modified
    request = rf.get(
        '/uk/api/books/',
        {
            'category': book.category.slug,
            'page': 2,
            'page_size': 1,
        },
    )

    response = async_to_sync(async_views.book_list)(request)
    data = json.loads(response.content)

    assert response.status_code == 404
    assert data.get('error')


@pytest.mark.parametrize(
    'parameters, expected_count, expected_page_size',
    [
        ({}, 20, 20),
        ({'page_size': 100}, 21, 100),
    ],
)
def test_async_book_list_respects_page_size(
    rf,
    category,
    parameters,
    expected_count,
    expected_page_size,
):
    # Generated with AI, reviewed and modified
    books = BookFactory.create_batch(21, category=category)

    request = rf.get('/uk/api/books/', parameters)

    response = async_to_sync(async_views.book_list)(request)
    data = json.loads(response.content)

    assert response.status_code == 200
    assert [item['id'] for item in data['books']] == [
        book.pk for book in books[:expected_count]
    ]
    assert data['pagination']['page_size'] == expected_page_size
    assert data['pagination']['total'] == 21