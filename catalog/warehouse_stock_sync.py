import logging

from django.conf import settings
from django.db import transaction

from .models import Book
from .warehouse_client import (
    WarehouseClient,
    WarehouseConfigurationError,
    WarehouseProtocolError,
)

logger = logging.getLogger(__name__)


def _load_available_stock():
    stocks = {}
    expected_count = None

    with WarehouseClient() as client:
        for page_number in range(1, 101):
            data = client.list_stock(page=page_number)

            if expected_count is None:
                expected_count = data["count"]

            if data["count"] != expected_count:
                raise WarehouseProtocolError(
                    "The warehouse stock list changed during synchronization."
                )

            for item in data["results"]:
                try:
                    book_id = item["external_book_id"]
                    quantity = item["quantity"]
                    reserved = item["reserved"]
                    available = item["available"]
                except (KeyError, TypeError):
                    raise WarehouseProtocolError(
                        "Warehouse returned an incomplete stock item."
                    ) from None

                values = (book_id, quantity, reserved, available)

                if (
                    any(type(value) is not int for value in values)
                    or book_id < 1
                    or not 0 <= quantity <= 2**31 - 1
                    or not 0 <= reserved <= quantity
                    or available != quantity - reserved
                    or book_id in stocks
                ):
                    raise WarehouseProtocolError(
                        "Warehouse returned invalid or duplicate stock data."
                    )

                stocks[book_id] = available

            if len(stocks) > expected_count:
                raise WarehouseProtocolError(
                    "Warehouse returned an inconsistent stock count."
                )

            if data.get("next") is None:
                if len(stocks) != expected_count:
                    raise WarehouseProtocolError(
                        "Warehouse returned an incomplete stock list."
                    )
                return stocks

            if not data["results"]:
                raise WarehouseProtocolError(
                    "Warehouse returned an empty intermediate page."
                )

    raise WarehouseProtocolError(
        "Warehouse stock synchronization exceeded the page limit."
    )


def sync_stock_from_warehouse():
    """Update the catalogue projection after loading all warehouse pages."""
    results = {"received": 0, "updated": 0, "missing": 0}

    if not settings.WAREHOUSE_ENABLED:
        return results

    if not transaction.get_autocommit():
        raise WarehouseConfigurationError(
            "Stock synchronization must run outside an atomic transaction."
        )

    stocks = _load_available_stock()
    results["received"] = len(stocks)

    with transaction.atomic():
        books = Book.objects.select_for_update().order_by("pk")

        for book in books:
            if book.pk not in stocks:
                results["missing"] += 1

            available = stocks.get(book.pk, 0)

            if book.stock != available:
                book.stock = available
                book.save(update_fields=["stock"])
                results["updated"] += 1

    logger.info(
        "Warehouse stock synchronized: received=%s updated=%s missing=%s",
        results["received"],
        results["updated"],
        results["missing"],
    )
    return results
