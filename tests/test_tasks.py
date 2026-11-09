import json
from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.utils import timezone

from catalog.tasks import (
    clear_expired_sessions,
    generate_inventory_report,
    send_order_confirmation,
)
from .factories import BookFactory, OrderFactory, OrderItemFactory


pytestmark = pytest.mark.django_db


def test_paid_order_sends_confirmation_to_buyer(mailoutbox):
    # Generated with AI, reviewed and modified
    order = OrderFactory(status='paid')
    OrderItemFactory(order=order, quantity=2)

    sent = send_order_confirmation.run(order.pk, 'uk')

    assert sent == 1
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == [order.user.email]
    assert f'Замовлення #{order.pk} оплачено.' in message.body
    assert f'Сума: {order.get_total()} грн' in message.body


def test_pending_order_does_not_send_confirmation(mailoutbox):
    # Generated with AI, reviewed and modified
    order = OrderFactory(status='pending')

    assert send_order_confirmation.run(order.pk, 'uk') == 0
    assert len(mailoutbox) == 0


def test_inventory_report_contains_books_and_total_stock(settings, tmp_path):
    # Generated with AI, reviewed and modified
    settings.BASE_DIR = tmp_path
    first = BookFactory(stock=3)
    second = BookFactory(stock=5)

    report_path = tmp_path / generate_inventory_report.run()
    report = json.loads(report_path.read_text(encoding='utf-8'))

    assert report['book_count'] == 2
    assert report['total_stock'] == 8
    assert report['books'] == [
        {'id': first.pk, 'title': first.title, 'stock': 3},
        {'id': second.pk, 'title': second.title, 'stock': 5},
    ]


def test_clear_expired_sessions_keeps_active_session():
    # Generated with AI, reviewed and modified
    now = timezone.now()
    expired = Session.objects.create(
        session_key='expired', session_data='', expire_date=now - timedelta(days=1)
    )
    active = Session.objects.create(
        session_key='active', session_data='', expire_date=now + timedelta(days=1)
    )

    clear_expired_sessions.run()

    assert not Session.objects.filter(pk=expired.pk).exists()
    assert Session.objects.filter(pk=active.pk).exists()