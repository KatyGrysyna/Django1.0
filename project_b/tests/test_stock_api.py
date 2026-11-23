from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from inventory.models import StockItem

pytestmark = [pytest.mark.api, pytest.mark.django_db]


@pytest.fixture(autouse=True)
def warehouse_groups():
    call_command("setup_warehouse_groups", stdout=StringIO())


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="stock_api_user",
        password="Stock-test-password-123",
    )


@pytest.fixture
def auth_client(api_client, user):
    token = RefreshToken.for_user(user).access_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


@pytest.fixture
def viewer_client(auth_client, user):
    user.groups.add(Group.objects.get(name="warehouse_viewers"))
    return auth_client


@pytest.fixture
def stock_item():
    return StockItem.objects.create(
        external_book_id=101,
        title="First book",
        quantity=12,
        reserved=4,
    )


@pytest.fixture(params=["stock-list", "stock-detail"])
def stock_url(request, stock_item):
    if request.param == "stock-detail":
        return reverse("stock-detail", kwargs={"pk": stock_item.pk})
    return reverse("stock-list")


def test_stock_requires_token(api_client, stock_url):
    response = api_client.get(stock_url)

    assert response.status_code == 401


def test_stock_requires_view_permission(auth_client, stock_url):
    response = auth_client.get(stock_url)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "group_name",
    ["warehouse_viewers", "warehouse_managers"],
)
def test_group_can_read_stock(auth_client, user, stock_item, group_name):
    user.groups.add(Group.objects.get(name=group_name))

    response = auth_client.get(reverse("stock-list"))

    assert response.status_code == 200
    assert response.data["count"] == 1

    item = response.data["results"][0]

    assert item["id"] == stock_item.pk
    assert item["external_book_id"] == 101
    assert item["title"] == "First book"
    assert item["quantity"] == 12
    assert item["reserved"] == 4
    assert item["available"] == 8


def test_viewer_can_read_stock_detail(viewer_client, stock_item):
    response = viewer_client.get(reverse("stock-detail", kwargs={"pk": stock_item.pk}))

    assert response.status_code == 200
    assert response.data["id"] == stock_item.pk
    assert response.data["external_book_id"] == 101
    assert response.data["available"] == 8


def test_stock_filter_by_external_book_id(viewer_client, stock_item):
    StockItem.objects.create(
        external_book_id=202,
        title="Second book",
        quantity=5,
    )

    response = viewer_client.get(
        reverse("stock-list"),
        {"external_book_id": 202},
    )

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["external_book_id"] == 202


def test_missing_stock_returns_404(viewer_client, stock_item):
    response = viewer_client.get(
        reverse("stock-detail", kwargs={"pk": stock_item.pk + 1000})
    )

    assert response.status_code == 404


def test_removing_group_revokes_access(viewer_client, user, stock_item):
    url = reverse("stock-list")

    assert viewer_client.get(url).status_code == 200

    user.groups.clear()

    assert viewer_client.get(url).status_code == 403
