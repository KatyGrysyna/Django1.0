import pytest
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils.translation import override
from pytest_django.asserts import assertContains

from catalog.models import Book, Category, Order

from .factories import OrderItemFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def ordered_item(order, book):
    return OrderItemFactory(order=order, book=book, quantity=2)


def assert_order_preserved(item):
    item.refresh_from_db()

    assert item.quantity == 2
    assert Book.objects.filter(pk=item.book_id).exists()
    assert Category.objects.filter(pk=item.book.category_id).exists()
    assert Order.objects.filter(pk=item.order_id).exists()
    assert item.order.items.count() == 1


@pytest.mark.parametrize("target", ["book", "category"])
def test_model_deletion_preserves_order_items(ordered_item, target):
    instance = ordered_item.book if target == "book" else ordered_item.book.category

    with pytest.raises(ProtectedError):
        instance.delete()

    assert_order_preserved(ordered_item)


@pytest.mark.parametrize("target", ["book", "category"])
def test_api_returns_conflict_for_catalog_items_used_in_orders(
    staff_api_client, ordered_item, target
):
    instance = ordered_item.book if target == "book" else ordered_item.book.category

    response = staff_api_client.delete(
        reverse(f"api:{target}-detail", args=[instance.pk])
    )

    assert response.status_code == 409
    assert "detail" in response.data
    assert_order_preserved(ordered_item)


def test_book_delete_page_explains_why_deletion_is_blocked(
    client, admin_user, ordered_item
):
    client.force_login(admin_user)

    with override("uk"):
        response = client.post(
            reverse("catalog:book_delete", args=[ordered_item.book_id])
        )

    assertContains(
        response,
        "вже є в замовленні",
        status_code=409,
    )
    assert_order_preserved(ordered_item)


def test_unused_book_can_still_be_deleted_from_site(client, admin_user, book):
    client.force_login(admin_user)
    book_id = book.pk

    with override("uk"):
        response = client.post(reverse("catalog:book_delete", args=[book_id]))
        expected_url = reverse("catalog:book_list")

    assert response.status_code == 302
    assert response.url == expected_url
    assert not Book.objects.filter(pk=book_id).exists()
