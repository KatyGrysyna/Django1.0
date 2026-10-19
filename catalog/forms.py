from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Book


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = [
            'title',
            'author',
            'price',
            'description',
            'stock',
            'category',
        ]

        help_texts = {
            'price': _('Ціна у гривнях.'),
            'stock': _('Кількість доступних примірників.'),
        }

        error_messages = {
            'title': {
                'required': _('Вкажіть назву книги.'),
            },
            'author': {
                'required': _('Вкажіть автора книги.'),
            },
            'price': {
                'required': _('Вкажіть ціну книги.'),
                'invalid': _('Введіть коректну ціну.'),
            },
            'stock': {
                'required': _('Вкажіть кількість книг.'),
                'invalid': _('Введіть ціле число.'),
            },
            'category': {
                'required': _('Оберіть категорію.'),
                'invalid_choice': _('Оберіть категорію зі списку.'),
            },
        }