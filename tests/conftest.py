import pytest

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