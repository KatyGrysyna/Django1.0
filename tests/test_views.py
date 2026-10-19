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
    first = BookFactory()
    second = BookFactory()

    request = rf.get('/uk/')
    view = views.BookListView()
    view.setup(request)

    result_ids = set(view.get_queryset().values_list('pk', flat=True))

    assert result_ids == {first.pk, second.pk}


def test_book_list_filters_by_category(rf, book):
    BookFactory()

    request = rf.get('/uk/', {'category': book.category.slug})
    view = views.BookListView()
    view.setup(request)

    assert list(view.get_queryset()) == [book]


def test_book_detail_returns_requested_book(rf, book):
    request = rf.get(f'/uk/book/{book.pk}/')

    response = views.BookDetailView.as_view()(request, pk=book.pk)

    assert response.status_code == 200
    assert response.context_data['book'] == book
    assert 'catalog/book_detail.html' in response.template_name


def test_book_detail_raises_404_for_missing_book(rf):
    request = rf.get('/uk/book/999999/')

    with pytest.raises(Http404):
        views.BookDetailView.as_view()(request, pk=999999)


def test_book_create_redirects_anonymous_user_to_login(rf):
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
    request = rf.get('/uk/book/create/')
    request.user = user

    with pytest.raises(PermissionDenied):
        views.BookCreateView.as_view()(request)


def test_async_book_list_filters_by_category(rf, book):
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
    request = rf.get('/uk/api/books/999999/')

    with pytest.raises(Http404):
        async_to_sync(async_views.book_detail)(request, pk=999999)