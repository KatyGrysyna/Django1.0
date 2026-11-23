import pytest
from django.contrib import admin
from django.urls import reverse

from inventory.models import StockItem

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def stock_item():
    return StockItem.objects.create(
        external_book_id=101,
        title="Original book",
        quantity=10,
        reserved=2,
    )


@pytest.fixture
def admin_form_class(rf, admin_user, stock_item):
    request = rf.post("/")
    request.user = admin_user
    model_admin = admin.site._registry[StockItem]
    return model_admin.get_form(request, obj=stock_item)


def test_admin_preserves_reservation_changed_after_loading(
    stock_item, admin_form_class
):
    StockItem.objects.filter(pk=stock_item.pk).update(reserved=5)

    form = admin_form_class(
        data={
            "title": "Updated title",
            "quantity": 12,
            "reserved": 0,
            "external_book_id": 999,
        },
        instance=stock_item,
    )

    assert form.is_valid(), form.errors
    form.save()

    stock_item.refresh_from_db()
    assert stock_item.title == "Updated title"
    assert stock_item.quantity == 12
    assert stock_item.reserved == 5
    assert stock_item.external_book_id == 101


def test_admin_rejects_quantity_below_current_reservation(stock_item, admin_form_class):
    StockItem.objects.filter(pk=stock_item.pk).update(reserved=5)

    form = admin_form_class(
        data={"title": stock_item.title, "quantity": 3},
        instance=stock_item,
    )

    assert not form.is_valid()
    assert "quantity" in form.errors

    stock_item.refresh_from_db()
    assert stock_item.quantity == 10
    assert stock_item.reserved == 5


def test_admin_rejects_item_deleted_after_loading(stock_item, admin_form_class):
    original_pk = stock_item.pk
    StockItem.objects.filter(pk=original_pk).delete()

    form = admin_form_class(
        data={"title": stock_item.title, "quantity": 10},
        instance=stock_item,
    )

    assert not form.is_valid()
    assert form.non_field_errors()
    assert not StockItem.objects.filter(pk=original_pk).exists()


def test_admin_can_create_stock(admin_client):
    response = admin_client.post(
        reverse("admin:inventory_stockitem_add"),
        {
            "external_book_id": 202,
            "title": "New book",
            "quantity": 4,
            "_save": "Save",
        },
    )

    assert response.status_code == 302

    item = StockItem.objects.get(external_book_id=202)
    assert item.quantity == 4
    assert item.reserved == 0


@pytest.mark.django_db(transaction=True)
def test_admin_change_holds_transaction_until_save(admin_client, stock_item):
    response = admin_client.post(
        reverse("admin:inventory_stockitem_change", args=[stock_item.pk]),
        {
            "title": "Changed through admin",
            "quantity": 12,
            "_save": "Save",
        },
    )

    assert response.status_code == 302

    stock_item.refresh_from_db()
    assert stock_item.title == "Changed through admin"
    assert stock_item.quantity == 12
    assert stock_item.reserved == 2
