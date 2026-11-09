import pytest
from django.core.cache import cache

from .factories import BookFactory, CategoryFactory


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clear_test_cache():
    cache.clear()
    yield
    cache.clear()


def get_categories(client, language='uk'):
    response = client.get(f'/{language}/api/categories/')
    assert response.status_code == 200
    return {item['id']: item for item in response.json()['categories']}


def test_second_category_request_uses_cached_response(
    client, category, django_assert_num_queries
):
    # Generated with AI, reviewed and modified
    with django_assert_num_queries(1):
        first = get_categories(client)

    assert first[category.pk]['book_count'] == 0

    with django_assert_num_queries(0):
        second = get_categories(client)

    assert second == first


def test_book_changes_refresh_counts_in_both_languages(client, category):
    # Generated with AI, reviewed and modified
    for language in ('uk', 'en'):
        assert get_categories(client, language)[category.pk]['book_count'] == 0

    book = BookFactory(category=category)

    for language in ('uk', 'en'):
        assert get_categories(client, language)[category.pk]['book_count'] == 1

    book.delete()

    for language in ('uk', 'en'):
        assert get_categories(client, language)[category.pk]['book_count'] == 0


def test_category_creation_rename_and_deletion_refresh_cached_list(client):
    # Generated with AI, reviewed and modified
    before = get_categories(client)

    category = CategoryFactory()
    pk = category.pk
    assert pk not in before
    assert get_categories(client)[pk]['name'] == category.name

    category.name = 'Нова назва'
    category.save(update_fields=['name'])
    assert get_categories(client)[pk]['name'] == 'Нова назва'

    category.delete()
    assert pk not in get_categories(client)