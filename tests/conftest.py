import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .factories import (
    BookFactory,
    CategoryFactory,
    OrderFactory,
    UserFactory,
)


@pytest.fixture
def category(db):
    return CategoryFactory()


@pytest.fixture
def book(db, category):
    return BookFactory(category=category)


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def order(db, user):
    return OrderFactory(user=user)


@pytest.fixture
def staff_user(db):
    return UserFactory(is_staff=True)


@pytest.fixture
def api_client():
    cache.clear()
    yield APIClient()
    cache.clear()


@pytest.fixture
def auth_api_client(api_client, user):
    token = RefreshToken.for_user(user).access_token
    api_client.credentials(
        HTTP_AUTHORIZATION=f'Bearer {token}'
    )
    return api_client


@pytest.fixture
def staff_api_client(api_client, staff_user):
    token = RefreshToken.for_user(staff_user).access_token
    api_client.credentials(
        HTTP_AUTHORIZATION=f'Bearer {token}'
    )
    return api_client