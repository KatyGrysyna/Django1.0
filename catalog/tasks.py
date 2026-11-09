import json

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.mail import send_mail
from django.core.management import call_command
from django.utils import timezone
from django.utils.translation import gettext as _, override

from .models import Book, Order


@shared_task
def send_order_confirmation(order_id, language=None):
    """Send a payment confirmation in the customer's language."""
    order = (
        Order.objects.select_related('user')
        .filter(pk=order_id, status='paid')
        .first()
    )

    if order is None or not order.user.email:
        return 0

    with override(language or settings.LANGUAGE_CODE):
        subject = _('Дякуємо за замовлення')
        payment_line = _('Замовлення #%(order_id)s оплачено.') % {
            'order_id': order.pk,
        }
        total_line = _('Сума: %(total)s грн') % {
            'total': order.get_total(),
        }

        return send_mail(
            subject=subject,
            message=f'{payment_line}\n{total_line}',
            from_email=None,
            recipient_list=[order.user.email],
        )
@shared_task
def generate_inventory_report():
    """Save a JSON inventory report and return its path."""
    generated_at = timezone.now()
    books = list(
        Book.objects.order_by('id').values('id', 'title', 'stock')
    )

    report = {
        'generated_at': generated_at.isoformat(),
        'book_count': len(books),
        'total_stock': sum(book['stock'] for book in books),
        'books': books,
    }

    storage = FileSystemStorage(location=settings.BASE_DIR / 'reports')
    filename = f'inventory-{generated_at:%Y-%m-%d_%H-%M-%S}.json'
    content = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    saved_name = storage.save(filename, ContentFile(content.encode('utf-8')))

    return f'reports/{saved_name}'


@shared_task
def clear_expired_sessions():
    """Remove expired Django sessions."""
    call_command('clearsessions', verbosity=0)