from django.db.models.deletion import ProtectedError
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import APIException


class CatalogDeletionConflict(APIException):
    status_code = 409
    default_detail = _(
        "Не можна видалити книгу або категорію, пов’язану із замовленням."
    )
    default_code = "catalog_in_use"


class ProtectedCatalogDeleteMixin:
    def perform_destroy(self, instance):
        try:
            return super().perform_destroy(instance)
        except ProtectedError:
            raise CatalogDeletionConflict() from None
