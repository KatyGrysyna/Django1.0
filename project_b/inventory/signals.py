from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import StockItem
from .stock_cache import invalidate_stock_cache


@receiver(
    [post_save, post_delete],
    sender=StockItem,
    dispatch_uid="inventory.invalidate_stock_cache",
)
def stock_changed(sender, using, **kwargs):
    transaction.on_commit(invalidate_stock_cache, using=using)