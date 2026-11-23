from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from inventory.models import Reservation, ReservationItem, StockItem

pytestmark = [pytest.mark.api, pytest.mark.django_db]


@pytest.fixture
def user(django_user_model):
    call_command("setup_warehouse_groups", stdout=StringIO())

    user = django_user_model.objects.create_user(
        username="reservation_workflow_user",
        password="Workflow-test-password-123",
    )
    user.groups.add(Group.objects.get(name="warehouse_clients"))
    return user


@pytest.fixture
def api_client(user):
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def stock_item():
    return StockItem.objects.create(
        external_book_id=101,
        title="API workflow book",
        quantity=10,
    )


@pytest.fixture
def payload():
    return {
        "external_order_id": 1001,
        "items": [{"external_book_id": 101, "quantity": 3}],
    }


@pytest.fixture
def reservation(api_client, stock_item, payload):
    response = api_client.post(
        reverse("reservation-list"),
        payload,
        format="json",
    )
    assert response.status_code == 201
    return Reservation.objects.get(pk=response.data["id"])


def assert_stock(stock_item, quantity, reserved):
    stock_item.refresh_from_db()

    assert stock_item.quantity == quantity
    assert stock_item.reserved == reserved
    assert stock_item.available == quantity - reserved


def test_create_reservation(api_client, user, stock_item, payload):
    response = api_client.post(
        reverse("reservation-list"),
        payload,
        format="json",
    )

    assert response.status_code == 201
    assert response["Cache-Control"] == "private, no-store"
    assert response.data["external_order_id"] == 1001
    assert response.data["status"] == "pending"
    assert response.data["items"] == [
        {
            "external_book_id": 101,
            "title": "API workflow book",
            "quantity": 3,
        }
    ]

    reservation = Reservation.objects.get(pk=response.data["id"])

    assert reservation.created_by_id == user.pk
    assert reservation.expires_at > timezone.now()
    assert Reservation.objects.count() == 1
    assert ReservationItem.objects.count() == 1
    assert_stock(stock_item, quantity=10, reserved=3)


def test_repeated_creation_does_not_reserve_twice(
    api_client, reservation, stock_item, payload
):
    original_expiry = reservation.expires_at

    response = api_client.post(
        reverse("reservation-list"),
        payload,
        format="json",
    )

    assert response.status_code == 200
    assert response.data["id"] == str(reservation.pk)

    reservation.refresh_from_db()

    assert reservation.expires_at == original_expiry
    assert Reservation.objects.count() == 1
    assert ReservationItem.objects.count() == 1
    assert_stock(stock_item, quantity=10, reserved=3)


def test_same_order_with_different_items_returns_conflict(
    api_client, reservation, stock_item, payload
):
    payload["items"][0]["quantity"] = 4

    response = api_client.post(
        reverse("reservation-list"),
        payload,
        format="json",
    )

    assert response.status_code == 409
    assert "detail" in response.data
    assert Reservation.objects.count() == 1
    assert reservation.items.get().quantity == 3
    assert_stock(stock_item, quantity=10, reserved=3)


@pytest.mark.parametrize(
    "changes",
    [
        {"external_order_id": 0},
        {"items": []},
        {"items": [{"external_book_id": 101, "quantity": 0}]},
        {"items": [{"external_book_id": 101}]},
        {"items": [{"external_book_id": 101, "quantity": 1}] * 2},
    ],
    ids=[
        "invalid-order",
        "empty-items",
        "zero-quantity",
        "missing-quantity",
        "duplicate",
    ],
)
def test_invalid_payload_returns_400(api_client, stock_item, payload, changes):
    payload.update(changes)

    response = api_client.post(
        reverse("reservation-list"),
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert not Reservation.objects.exists()
    assert not ReservationItem.objects.exists()
    assert_stock(stock_item, quantity=10, reserved=0)


@pytest.mark.parametrize(
    ("book_id", "quantity"),
    [(999, 1), (101, 11)],
    ids=["unknown-book", "insufficient-stock"],
)
def test_unavailable_stock_returns_409_and_is_logged(
    api_client, stock_item, payload, book_id, quantity, caplog
):
    payload["items"] = [{"external_book_id": book_id, "quantity": quantity}]

    response = api_client.post(
        reverse("reservation-list"),
        payload,
        format="json",
    )

    assert response.status_code == 409
    assert "detail" in response.data
    assert not Reservation.objects.exists()
    assert not ReservationItem.objects.exists()
    assert_stock(stock_item, quantity=10, reserved=0)

    assert any(
        record.name == "inventory.reservation_views" and record.levelname == "WARNING"
        for record in caplog.records
    )


@pytest.mark.parametrize(
    ("action", "expected_status", "expected_quantity"),
    [
        ("confirm", "confirmed", 7),
        ("release", "released", 10),
    ],
)
def test_lifecycle_action_is_idempotent(
    api_client,
    reservation,
    stock_item,
    action,
    expected_status,
    expected_quantity,
):
    url = reverse(f"reservation-{action}", kwargs={"pk": reservation.pk})

    for _ in range(2):
        response = api_client.post(url, {}, format="json")

        assert response.status_code == 200
        assert response.data["id"] == str(reservation.pk)
        assert response.data["status"] == expected_status
        assert response["Cache-Control"] == "private, no-store"
        assert_stock(stock_item, quantity=expected_quantity, reserved=0)

    reservation.refresh_from_db()
    assert reservation.status == expected_status


@pytest.mark.parametrize(
    ("first_action", "second_action", "expected_status", "expected_quantity"),
    [
        ("confirm", "release", "confirmed", 7),
        ("release", "confirm", "released", 10),
    ],
)
def test_conflicting_transition_returns_409(
    api_client,
    reservation,
    stock_item,
    first_action,
    second_action,
    expected_status,
    expected_quantity,
):
    first_url = reverse(
        f"reservation-{first_action}",
        kwargs={"pk": reservation.pk},
    )
    second_url = reverse(
        f"reservation-{second_action}",
        kwargs={"pk": reservation.pk},
    )

    assert api_client.post(first_url, {}, format="json").status_code == 200

    response = api_client.post(second_url, {}, format="json")

    assert response.status_code == 409
    reservation.refresh_from_db()
    assert reservation.status == expected_status
    assert_stock(stock_item, quantity=expected_quantity, reserved=0)


def test_overdue_reservation_cannot_be_confirmed(api_client, reservation, stock_item):
    reservation.expires_at = timezone.now() - timedelta(seconds=1)
    reservation.save(update_fields=["expires_at"])

    response = api_client.post(
        reverse("reservation-confirm", kwargs={"pk": reservation.pk}),
        {},
        format="json",
    )

    assert response.status_code == 409
    reservation.refresh_from_db()
    assert reservation.status == Reservation.Status.PENDING
    assert_stock(stock_item, quantity=10, reserved=3)


def test_request_cannot_override_owner_or_status(
    api_client, user, django_user_model, stock_item, payload
):
    other_user = django_user_model.objects.create_user(
        username="spoofed_reservation_owner",
        password="Other-test-password-123",
    )
    payload["created_by"] = other_user.pk
    payload["status"] = "confirmed"

    response = api_client.post(
        reverse("reservation-list"),
        payload,
        format="json",
    )

    assert response.status_code == 201

    reservation = Reservation.objects.get(pk=response.data["id"])

    assert reservation.created_by_id == user.pk
    assert reservation.status == Reservation.Status.PENDING
    assert_stock(stock_item, quantity=10, reserved=3)
