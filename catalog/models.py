from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy


class Category(models.Model):
    name = models.CharField(
        verbose_name=_('Назва'),
        max_length=100,
    )
    slug = models.SlugField(
        verbose_name=_('URL-ідентифікатор'),
        unique=True,
    )

    class Meta:
        verbose_name = _('Категорія')
        verbose_name_plural = _('Категорії')

    def __str__(self):
        return self.name


class Book(models.Model):
    title = models.CharField(
        verbose_name=_('Назва'),
        max_length=200,
    )
    author = models.CharField(
        verbose_name=_('Автор'),
        max_length=150,
    )
    price = models.DecimalField(
        verbose_name=_('Ціна'),
        max_digits=8,
        decimal_places=2,
    )
    description = models.TextField(
        verbose_name=_('Опис'),
        blank=True,
    )
    stock = models.PositiveIntegerField(
        verbose_name=_('Кількість на складі'),
        default=0,
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='books',
        verbose_name=_('Категорія'),
    )

    class Meta:
        verbose_name = _('Книга')
        verbose_name_plural = _('Книги')

    def __str__(self):
        return self.title


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', _('Очікує оплати')),
        ('paid', _('Оплачено')),
        ('cancelled', _('Скасовано')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name=_('Користувач'),
    )
    created_at = models.DateTimeField(
        verbose_name=_('Дата створення'),
        auto_now_add=True,
    )
    status = models.CharField(
        verbose_name=_('Статус'),
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )
    stripe_session_id = models.CharField(
        verbose_name=_('Ідентифікатор сесії Stripe'),
        max_length=255,
        blank=True,
    )

    class Meta:
        verbose_name = _('Замовлення')
        verbose_name_plural = pgettext_lazy('order plural', 'Замовлення')

    def __str__(self):
        return _('Замовлення №%(number)s (%(username)s)') % {
            'number': self.pk,
            'username': self.user.username,
        }

    def get_total(self):
        return sum(item.get_subtotal() for item in self.items.all())


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Замовлення'),
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        verbose_name=_('Книга'),
    )
    quantity = models.PositiveIntegerField(
        verbose_name=_('Кількість'),
        default=1,
    )
    price = models.DecimalField(
        verbose_name=_('Ціна'),
        max_digits=8,
        decimal_places=2,
    )

    class Meta:
        verbose_name = _('Позиція замовлення')
        verbose_name_plural = _('Позиції замовлення')

    def __str__(self):
        return f'{self.book.title} x{self.quantity}'

    def get_subtotal(self):
        return self.price * self.quantity