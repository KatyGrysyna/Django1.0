from decimal import Decimal

import factory

from accounts.models import CustomUser
from catalog.models import Book, Category, Order, OrderItem


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomUser

    username = factory.Sequence(lambda n: f'test_user_{n}')
    email = factory.LazyAttribute(
        lambda user: f'{user.username}@example.com'
    )
    password = factory.django.Password('TestPass123!')


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f'Категорія {n}')
    slug = factory.Sequence(lambda n: f'category-{n}')


class BookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Book

    title = factory.Sequence(lambda n: f'Книга {n}')
    author = 'Тестовий автор'
    price = Decimal('100.00')
    description = 'Опис тестової книги'
    stock = 10
    category = factory.SubFactory(CategoryFactory)


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    user = factory.SubFactory(UserFactory)


class OrderItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    book = factory.SubFactory(BookFactory)
    quantity = 1
    price = factory.LazyAttribute(lambda item: item.book.price)