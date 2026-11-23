import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils.translation import override
from rest_framework.test import APIClient

from inventory.models import StockItem

pytestmark = [pytest.mark.api, pytest.mark.django_db]

EN_DUPLICATE = "Each book must appear only once in a reservation."
UK_DUPLICATE = "Кожна книга має бути вказана в резервуванні лише один раз."


@pytest.fixture
def api_client(django_user_model):
    user = django_user_model.objects.create_user(
        username="warehouse_i18n_user",
        password="I18n-test-password-123",
    )
    permission = Permission.objects.get(
        content_type__app_label="inventory",
        codename="add_reservation",
    )
    user.user_permissions.add(permission)

    client = APIClient()
    client.force_authenticate(user=user)

    with override("en"):
        yield client


@pytest.mark.parametrize(
    ("language", "expected_language", "message"),
    [
        ("uk", "uk", UK_DUPLICATE),
        ("en", "en", EN_DUPLICATE),
        ("de", "en", EN_DUPLICATE),
    ],
)
def test_api_validation_language(api_client, language, expected_language, message):
    response = api_client.post(
        reverse("reservation-list"),
        {
            "external_order_id": 501,
            "items": [
                {"external_book_id": 101, "quantity": 1},
                {"external_book_id": 101, "quantity": 1},
            ],
        },
        format="json",
        HTTP_ACCEPT_LANGUAGE=language,
    )

    assert response.status_code == 400
    assert response.headers["Content-Language"] == expected_language
    assert str(response.data["items"][0]) == message


def test_ukrainian_response_preserves_api_status_code(api_client):
    stock = StockItem.objects.create(
        external_book_id=101,
        title="Тестова книга",
        quantity=3,
    )

    response = api_client.post(
        reverse("reservation-list"),
        {
            "external_order_id": 502,
            "items": [
                {"external_book_id": 101, "quantity": 1},
            ],
        },
        format="json",
        HTTP_ACCEPT_LANGUAGE="uk",
    )

    assert response.status_code == 201
    assert response.headers["Content-Language"] == "uk"
    assert response.data["status"] == "pending"
    assert response.data["items"][0]["external_book_id"] == 101

    stock.refresh_from_db()
    assert stock.reserved == 1
