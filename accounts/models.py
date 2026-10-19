from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class CustomUser(AbstractUser):
    phone = models.CharField(
        verbose_name=_('Номер телефону'),
        max_length=20,
        blank=True,
    )

    class Meta:
        verbose_name = _('Користувач')
        verbose_name_plural = _('Користувачі')