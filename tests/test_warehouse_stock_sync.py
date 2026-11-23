from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key

from catalog.warehouse_client import (
    WarehouseProtocolError,
    WarehouseUnavailable,
)
from catalog.warehouse_stock_sync import sync_stock_from_warehouse

from .factories import BookFactory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
]


def stock_item(book, quantity=10, reserved=2):
    return {
        "external_book_id": book.pk,
        "quantity": quantity,
        "reserved": reserved,
        "available": quantity - reserved,
    }


def stock_page(*items, count=None, next_page=None):
    return {
        "count": len(items) if count is None else count,
        "results": list(items),
        "next": next_page,
    }


@pytest.fixture(autouse=True)
def warehouse(settings):
    settings.WAREHOUSE_ENABLED = True
    cache.clear()

    with patch(
        "catalog.warehouse_stock_sync.WarehouseClient",
        autospec=True,
    ) as factory:
        client = factory.return_value
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        yield client

    cache.clear()


def test_available_stock_updates_book_and_clears_cached_cards(warehouse, settings):
    book = BookFactory(stock=0)
    keys = [f"catalog:book-detail:{book.pk}"]

    for language, _ in settings.LANGUAGES:
        keys.append(make_template_fragment_key("book_card", [book.pk, language]))

    for key in keys:
        cache.set(key, "old cached content")

    warehouse.list_stock.return_value = stock_page(stock_item(book))

    result = sync_stock_from_warehouse()

    book.refresh_from_db()
    assert book.stock == 8
    assert result == {"received": 1, "updated": 1, "missing": 0}
    assert cache.get_many(keys) == {}


def test_sync_reads_every_page(warehouse):
    first = BookFactory(stock=0)
    second = BookFactory(stock=0)
    warehouse.list_stock.side_effect = [
        stock_page(
            stock_item(first, quantity=8, reserved=0),
            count=2,
            next_page="http://warehouse:8000/api/stock/?page=2",
        ),
        stock_page(
            stock_item(second, quantity=9, reserved=0),
            count=2,
        ),
    ]

    result = sync_stock_from_warehouse()

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.stock, second.stock) == (8, 9)
    assert result["updated"] == 2
    assert warehouse.list_stock.call_args_list[0].kwargs == {"page": 1}
    assert warehouse.list_stock.call_args_list[1].kwargs == {"page": 2}


def test_second_page_failure_preserves_all_previous_stock(warehouse):
    first = BookFactory(stock=3)
    second = BookFactory(stock=4)
    warehouse.list_stock.side_effect = [
        stock_page(
            stock_item(first),
            count=2,
            next_page="http://warehouse:8000/api/stock/?page=2",
        ),
        WarehouseUnavailable("Test connection failure"),
    ]

    with pytest.raises(WarehouseUnavailable):
        sync_stock_from_warehouse()

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.stock, second.stock) == (3, 4)


@pytest.mark.parametrize(
    "changes",
    [
        {"available": 9},
        {"reserved": 11},
        {"quantity": True},
    ],
)
def test_invalid_stock_does_not_overwrite_catalogue(warehouse, changes):
    book = BookFactory(stock=3)
    item = stock_item(book)
    item.update(changes)
    warehouse.list_stock.return_value = stock_page(item)

    with pytest.raises(WarehouseProtocolError):
        sync_stock_from_warehouse()

    book.refresh_from_db()
    assert book.stock == 3


def test_duplicate_items_across_pages_are_rejected(warehouse):
    book = BookFactory(stock=3)
    item = stock_item(book)
    warehouse.list_stock.side_effect = [
        stock_page(
            item,
            count=2,
            next_page="http://warehouse:8000/api/stock/?page=2",
        ),
        stock_page(item, count=2),
    ]

    with pytest.raises(WarehouseProtocolError):
        sync_stock_from_warehouse()

    book.refresh_from_db()
    assert book.stock == 3


def test_book_missing_from_complete_warehouse_list_becomes_unavailable(
    warehouse,
):
    book = BookFactory(stock=5)
    warehouse.list_stock.return_value = stock_page()

    result = sync_stock_from_warehouse()

    book.refresh_from_db()
    assert book.stock == 0
    assert result == {"received": 0, "updated": 1, "missing": 1}


def test_disabled_sync_preserves_local_stock(settings, warehouse):
    book = BookFactory(stock=6)
    settings.WAREHOUSE_ENABLED = False

    result = sync_stock_from_warehouse()

    book.refresh_from_db()
    assert book.stock == 6
    assert result["updated"] == 0
    warehouse.list_stock.assert_not_called()
