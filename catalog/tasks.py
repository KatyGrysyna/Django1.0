import logging

import stripe
from django.db import OperationalError
from django.db.models import Q

from .warehouse_client import WarehouseError

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
        Order.objects.select_related("user").filter(pk=order_id, status="paid").first()
    )

    if order is None or not order.user.email:
        return 0

    with override(language or settings.LANGUAGE_CODE):
        subject = _("Дякуємо за замовлення")
        payment_line = _("Замовлення #%(order_id)s оплачено.") % {
            "order_id": order.pk,
        }
        total_line = _("Сума: %(total)s грн") % {
            "total": order.get_total(),
        }

        return send_mail(
            subject=subject,
            message=f"{payment_line}\n{total_line}",
            from_email=None,
            recipient_list=[order.user.email],
        )


@shared_task
def generate_inventory_report():
    """Save a JSON inventory report and return its path."""
    generated_at = timezone.now()
    books = list(Book.objects.order_by("id").values("id", "title", "stock"))

    report = {
        "generated_at": generated_at.isoformat(),
        "book_count": len(books),
        "total_stock": sum(book["stock"] for book in books),
        "books": books,
    }

    storage = FileSystemStorage(location=settings.BASE_DIR / "reports")
    filename = f"inventory-{generated_at:%Y-%m-%d_%H-%M-%S}.json"
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    saved_name = storage.save(filename, ContentFile(content.encode("utf-8")))

    return f"reports/{saved_name}"


@shared_task
def clear_expired_sessions():
    """Remove expired Django sessions."""
    call_command("clearsessions", verbosity=0)


@shared_task
def reconcile_warehouse_orders():
    """Reconcile unfinished warehouse orders independently of the browser."""
    from .checkout_reconciliation import reconcile_warehouse_order

    results = {
        "checked": 0,
        "paid": 0,
        "cancelled": 0,
        "pending": 0,
        "skipped": 0,
        "failed": 0,
    }

    if not settings.WAREHOUSE_ENABLED:
        return results

    order_ids = list(
        Order.objects.filter(
            warehouse_reservation_id__isnull=False,
        )
        .filter(
            Q(status="pending")
            | Q(status="paid", warehouse_status="pending")
            | Q(
                status="cancelled",
                warehouse_status__in=["pending", "releasing"],
            )
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )

    for order_id in order_ids:
        results["checked"] += 1

        try:
            state = reconcile_warehouse_order(order_id)
        except Order.DoesNotExist:
            results["skipped"] += 1
        except (stripe.StripeError, WarehouseError, OperationalError) as exc:
            results["failed"] += 1
            logging.getLogger(__name__).error(
                "Order reconciliation failed: order=%s error=%s",
                order_id,
                type(exc).__name__,
            )
        else:
            results[state] += 1

    return results


@shared_task
def sync_warehouse_stock():
    """Refresh catalogue availability from the warehouse API."""
    from .warehouse_stock_sync import sync_stock_from_warehouse

    return sync_stock_from_warehouse()
