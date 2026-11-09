from django.conf import settings
from django.core.cache.utils import make_template_fragment_key
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from .category_cache import invalidate_category_list_cache

from .models import Book, Category


def book_detail_key(book_id):
    return f'catalog:book-detail:{book_id}'


@receiver([post_save, post_delete], sender=Book)
def invalidate_book_detail(sender, instance, using, **kwargs):
    """Remove book details and translated catalogue cards after commit."""
    book_id = instance.pk
    keys = [book_detail_key(book_id)]

    for language, _ in settings.LANGUAGES:
        card_key = make_template_fragment_key('book_card', [book_id, language])
        keys.append(card_key)

    transaction.on_commit(lambda: cache.delete_many(keys), using=using)


@receiver(post_save, sender=Category)
def invalidate_category_book_details(sender, instance, created, using, **kwargs):
    """Remove cached books that contain the old category details."""
    if created:
        return

    category_id = instance.pk

    def clear_books():
        book_ids = (
            Book.objects.using(using)
            .filter(category_id=category_id)
            .values_list('pk', flat=True)
        )
        keys = [book_detail_key(book_id) for book_id in book_ids]
        if keys:
            cache.delete_many(keys)

    transaction.on_commit(clear_books, using=using)

@receiver([post_save, post_delete], sender=Book)
@receiver([post_save, post_delete], sender=Category)
def refresh_category_list_after_change(sender, using, **kwargs):
    """Refresh the public category list after a committed change."""
    transaction.on_commit(invalidate_category_list_cache, using=using)