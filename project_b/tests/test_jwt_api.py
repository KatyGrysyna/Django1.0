from datetime import timedelta

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


pytestmark = [pytest.mark.api, pytest.mark.django_db]

TEST_PASSWORD = "Warehouse-test-password-123"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="warehouse_test_user",
        password=TEST_PASSWORD,
    )


def test_login_returns_tokens_for_user(api_client, user):
    response = api_client.post(
        reverse("token_obtain_pair"),
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
    )

    assert response.status_code == 200

    access = AccessToken(response.data["access"])
    refresh = RefreshToken(response.data["refresh"])

    assert str(access["user_id"]) == str(user.pk)
    assert str(refresh["user_id"]) == str(user.pk)


def test_login_rejects_wrong_password(api_client, user):
    response = api_client.post(
        reverse("token_obtain_pair"),
        {"username": user.username, "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == 401
    assert "access" not in response.data
    assert "refresh" not in response.data


def test_login_rejects_inactive_user(api_client, user):
    user.is_active = False
    user.save(update_fields=["is_active"])

    response = api_client.post(
        reverse("token_obtain_pair"),
        {"username": user.username, "password": TEST_PASSWORD},
        format="json",
    )

    assert response.status_code == 401
    assert "access" not in response.data
    assert "refresh" not in response.data


def test_refresh_returns_access_token(api_client, user):
    refresh = RefreshToken.for_user(user)

    response = api_client.post(
        reverse("token_refresh"),
        {"refresh": str(refresh)},
        format="json",
    )

    assert response.status_code == 200

    access = AccessToken(response.data["access"])

    assert str(access["user_id"]) == str(user.pk)


def test_refresh_rejects_malformed_token(api_client):
    response = api_client.post(
        reverse("token_refresh"),
        {"refresh": "not-a-valid-token"},
        format="json",
    )

    assert response.status_code == 401
    assert "access" not in response.data


def test_refresh_rejects_expired_token(api_client, user):
    refresh = RefreshToken.for_user(user)
    refresh.set_exp(lifetime=timedelta(seconds=-60))

    response = api_client.post(
        reverse("token_refresh"),
        {"refresh": str(refresh)},
        format="json",
    )

    assert response.status_code == 401
    assert "access" not in response.data


def test_refresh_rejects_access_token(api_client, user):
    access = RefreshToken.for_user(user).access_token

    response = api_client.post(
        reverse("token_refresh"),
        {"refresh": str(access)},
        format="json",
    )

    assert response.status_code == 401
    assert "access" not in response.data