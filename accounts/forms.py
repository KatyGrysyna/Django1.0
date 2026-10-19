from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ('username', 'email')

        labels = {
            'username': _("Ім'я користувача"),
            'email': _('Електронна пошта'),
        }

        help_texts = {
            'email': _('Введіть свою електронну адресу.'),
        }

        error_messages = {
            'username': {
                'required': _("Вкажіть ім'я користувача."),
                'unique': _("Користувач із таким ім'ям уже існує."),
            },
            'email': {
                'invalid': _('Введіть коректну електронну адресу.'),
            },
        }