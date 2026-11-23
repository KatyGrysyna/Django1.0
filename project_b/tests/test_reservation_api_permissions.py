from io import StringIO

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from inventory.models import Reservation, StockItem
from inventory.services import reserve_stock

pytestmark = [pytest.mark.api, pytest.mark.django_db]

OPERATIONS = ["list", "retrieve", "create", "confirm", "release"]


@pytest.fixture(autouse=True)
def warehouse_groups():
    call_command("setup_warehouse_groups", stdout=StringIO())


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="reservation_api_user",
        password="Reservation-test-password-123",
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        username="other_reservation_user",
        password="Other-test-password-123",
    )


@pytest.fixture
def stock_item():
    return StockItem.objects.create(
        external_book_id=101,
        title="Reservation API book",
        quantity=10,
    )


@pytest.fixture
def reservation(user, stock_item):
    reservation, _ = reserve_stock(
        created_by=user,
        external_order_id=901,
        items=[{"external_book_id": 101, "quantity": 2}],
    )
    return reservation


@pytest.fixture
def auth_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def warehouse_client(auth_client, user):
    user.groups.add(Group.objects.get(name="warehouse_clients"))
    return auth_client


def send_request(client, operation, reservation):
    if operation == "list":
        return client.get(reverse("reservation-list"))

    if operation == "retrieve":
        return client.get(reverse("reservation-detail", kwargs={"pk": reservation.pk}))

    if operation == "create":
        return client.post(
            reverse("reservation-list"),
            {
                "external_order_id": 902,
                "items": [{"external_book_id": 101, "quantity": 1}],
            },
            format="json",
        )

    return client.post(
        reverse(f"reservation-{operation}", kwargs={"pk": reservation.pk}),
        {},
        format="json",
    )


def assert_unchanged(stock_item, reservation, reserved=2, count=1):
    stock_item.refresh_from_db()
    reservation.refresh_from_db()

    assert stock_item.quantity == 10
    assert stock_item.reserved == reserved
    assert reservation.status == Reservation.Status.PENDING
    assert Reservation.objects.count() == count


@pytest.mark.parametrize("operation", OPERATIONS)
def test_anonymous_requests_are_rejected(operation, reservation, stock_item):
    response = send_request(APIClient(), operation, reservation)

    assert response.status_code == 401
    assert response["Cache-Control"] == "private, no-store"
    assert_unchanged(stock_item, reservation)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_user_without_permissions_is_rejected(
    auth_client, operation, reservation, stock_item
):
    response = send_request(auth_client, operation, reservation)

    assert response.status_code == 403
    assert_unchanged(stock_item, reservation)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_view_permission_allows_only_reading(
    auth_client, user, operation, reservation, stock_item
):
    permission = Permission.objects.get(
        content_type__app_label="inventory",
        codename="view_reservation",
    )
    user.user_permissions.add(permission)

    response = send_request(auth_client, operation, reservation)

    expected_status = 200 if operation in ("list", "retrieve") else 403
    assert response.status_code == expected_status
    assert_unchanged(stock_item, reservation)


@pytest.mark.parametrize("operation", ["confirm", "release"])
def test_add_permission_does_not_allow_lifecycle_changes(
    auth_client, user, operation, reservation, stock_item
):
    permission = Permission.objects.get(
        content_type__app_label="inventory",
        codename="add_reservation",
    )
    user.user_permissions.add(permission)

    response = send_request(auth_client, operation, reservation)

    assert response.status_code == 403
    assert_unchanged(stock_item, reservation)


@pytest.mark.parametrize("operation", ["retrieve", "confirm", "release"])
def test_other_users_reservation_is_hidden(
    warehouse_client, other_user, operation, reservation, stock_item
):
    foreign_reservation, _ = reserve_stock(
        created_by=other_user,
        external_order_id=903,
        items=[{"external_book_id": 101, "quantity": 3}],
    )

    response = send_request(warehouse_client, operation, foreign_reservation)

    assert response.status_code == 404
    assert_unchanged(stock_item, reservation, reserved=5, count=2)

    foreign_reservation.refresh_from_db()
    assert foreign_reservation.status == Reservation.Status.PENDING


def test_list_contains_only_own_reservations(
    warehouse_client, other_user, reservation, stock_item
):
    reserve_stock(
        created_by=other_user,
        external_order_id=903,
        items=[{"external_book_id": 101, "quantity": 3}],
    )

    response = warehouse_client.get(reverse("reservation-list"))

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == str(reservation.pk)
    assert response["Cache-Control"] == "private, no-store"


def test_client_can_read_own_reservation(warehouse_client, reservation):
    response = send_request(warehouse_client, "retrieve", reservation)

    assert response.status_code == 200
    assert response.data["id"] == str(reservation.pk)
    assert response.data["external_order_id"] == 901
    assert response.data["status"] == Reservation.Status.PENDING
    assert response.data["items"][0]["external_book_id"] == 101
    assert response.data["items"][0]["quantity"] == 2
    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("operation", OPERATIONS)
def test_removing_group_revokes_access_with_same_token(
    warehouse_client, user, operation, reservation, stock_item
):
    assert warehouse_client.get(reverse("reservation-list")).status_code == 200

    user.groups.clear()

    response = send_request(warehouse_client, operation, reservation)

    assert response.status_code == 403
    assert_unchanged(stock_item, reservation)
