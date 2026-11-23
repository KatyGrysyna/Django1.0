from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _


class WarehouseUser(AbstractUser):
    """User account of the warehouse service."""

    class Meta:
        verbose_name = _("warehouse user")
        verbose_name_plural = _("warehouse users")
