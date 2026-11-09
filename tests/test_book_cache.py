from decimal import Decimal
from django.core.cache.utils import make_template_fragment_key

import pytest
from django.core.cache import cache
from django.db import transaction
from django.http import Http404

from catalog.views import BookDetailView
from .factories import BookFactory


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def read_book(rf):
    cache.clear()
    view = BookDetailView.as_view()

    def read(pk):
        request = rf.get(f'/uk/book/{pk}/')
        response = view(request, pk=pk)
        return response.context_data['book']

    yield read
    cache.clear()


def test_second_book_read_needs_no_database_queries(
    book, category, read_book, django_assert_num_queries
):
    # Generated with AI, reviewed and modified
    with django_assert_num_queries(1):
        first = read_book(book.pk)
        assert first.title == book.title
        assert first.category.name == category.name

    with django_assert_num_queries(0):
        second = read_book(book.pk)
        assert second.title == book.title
        assert second.category.name == category.name


def test_new_price_is_visible_after_commit(book, read_book):
    # Generated with AI, reviewed and modified
    old_price = read_book(book.pk).price
    new_price = old_price + Decimal('10.00')

    with transaction.atomic():
        book.price = new_price
        book.save(update_fields=['price'])
        assert read_book(book.pk).price == old_price

    assert read_book(book.pk).price == new_price


def test_category_rename_refreshes_all_its_cached_books(
    book, category, read_book
):
    # Generated with AI, reviewed and modified
    second_book = BookFactory(category=category)
    book_ids = [book.pk, second_book.pk]

    for pk in book_ids:
        assert read_book(pk).category.name == category.name

    category.name = 'Оновлена категорія'
    category.save(update_fields=['name'])

    for pk in book_ids:
        assert read_book(pk).category.name == 'Оновлена категорія'


def test_deleted_book_is_no_longer_served_from_cache(book, read_book):
    # Generated with AI, reviewed and modified
    pk = book.pk
    assert read_book(pk).pk == pk

    book.delete()

    with pytest.raises(Http404):
        read_book(pk)
@pytest.mark.parametrize('action', ['change_price', 'delete'])
def test_book_change_clears_both_language_cards(client, book, action):
    # Generated with AI, reviewed and modified
    keys = []

    for language in ('uk', 'en'):
        response = client.get(f'/{language}/')
        assert response.status_code == 200

        key = make_template_fragment_key('book_card', [book.pk, language])
        assert book.title in cache.get(key, '')
        keys.append(key)

    if action == 'change_price':
        book.price += Decimal('10.00')
        book.save(update_fields=['price'])
    else:
        book.delete()

    assert cache.get_many(keys) == {}
