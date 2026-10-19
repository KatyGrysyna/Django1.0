import logging
from decimal import Decimal
from smtplib import SMTPException

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from .cart import Cart
from .forms import BookForm
from .models import Book, Category, Order, OrderItem

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)


class BookListView(ListView):
    """Display six books per page with an optional category filter."""

    model = Book
    template_name = 'catalog/book_list.html'
    context_object_name = 'books'
    paginate_by = 6

    def get_queryset(self):
        """Return books ordered by ID and filtered by category slug."""
        queryset = Book.objects.order_by('id')
        category_slug = self.request.GET.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        return queryset

    def get_context_data(self, **kwargs):
        """Add available categories and the selected filter to the context."""
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        context['selected_category'] = self.request.GET.get('category')
        return context


class BookDetailView(DetailView):
    """Display a book's details or return HTTP 404 if it does not exist."""

    model = Book
    template_name = 'catalog/book_detail.html'
    context_object_name = 'book'


class BookCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Let authenticated users with add permission create a book.

    Display validation errors or redirect to the catalogue after saving.
    """

    model = Book
    form_class = BookForm
    template_name = 'catalog/book_form.html'
    success_url = reverse_lazy('catalog:book_list')
    permission_required = 'catalog.add_book'


class BookUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Let authenticated users with change permission edit a book.

    Display validation errors or redirect to the catalogue after saving.
    """

    model = Book
    form_class = BookForm
    template_name = 'catalog/book_form.html'
    success_url = reverse_lazy('catalog:book_list')
    permission_required = 'catalog.change_book'


class BookDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Let authenticated users with delete permission remove a book.

    Show confirmation on GET and delete the book on POST.
    Redirect to the catalogue after deletion.
    """

    model = Book
    template_name = 'catalog/book_confirm_delete.html'
    success_url = reverse_lazy('catalog:book_list')
    permission_required = 'catalog.delete_book'


def cart_add(request, book_id):
    """Add one copy of an existing book to the session cart and redirect."""
    cart = Cart(request)
    book = get_object_or_404(Book, id=book_id)
    cart.add(book=book)
    return redirect('catalog:cart_detail')


def cart_remove(request, book_id):
    """Remove all copies of an existing book from the cart and redirect."""
    cart = Cart(request)
    book = get_object_or_404(Book, id=book_id)
    cart.remove(book)
    return redirect('catalog:cart_detail')


def cart_clear(request):
    """Remove all items from the session cart and redirect to its page."""
    cart = Cart(request)
    cart.clear()
    return redirect('catalog:cart_detail')


def cart_detail(request):
    """Display the current session cart, its items and total price."""
    cart = Cart(request)
    return render(request, 'catalog/cart_detail.html', {'cart': cart})


@login_required
@require_POST
def checkout(request):
    """Create an order and redirect the customer to Stripe Checkout.

    Save the order and its items in one database transaction.
    Preserve the cart and return HTTP 503 if Stripe creation fails.
    """
    cart = Cart(request)

    if len(cart) == 0:
        return redirect('catalog:cart_detail')

    with transaction.atomic():
        order = Order.objects.create(user=request.user)

        line_items = []
        for item in cart:
            OrderItem.objects.create(
                order=order,
                book=item['book'],
                quantity=item['quantity'],
                price=item['price'],
            )
            line_items.append({
                'price_data': {
                    'currency': 'uah',
                    'product_data': {
                        'name': item['book'].title,
                    },
                    'unit_amount': int(item['price'] * 100),
                },
                'quantity': item['quantity'],
            })

    try:
        session = stripe.checkout.Session.create(
            line_items=line_items,
            mode='payment',
            success_url=request.build_absolute_uri(
                reverse('catalog:checkout_success')
            ) + f'?order_id={order.id}',
            cancel_url=request.build_absolute_uri(
                reverse('catalog:checkout_cancel')
            ),
        )
    except stripe.StripeError:
        logger.exception(
            'Could not create Stripe checkout for order %s',
            order.pk,
        )
        return render(
            request,
            'catalog/cart_detail.html',
            {
                'cart': cart,
                'checkout_error': _(
                    'Не вдалося створити оплату. Спробуйте пізніше.'
                ),
            },
            status=503,
        )

    order.stripe_session_id = session.id
    order.save(update_fields=['stripe_session_id'])

    return HttpResponseRedirect(session.url, status=303)


@login_required
def checkout_success(request):
    """Verify payment for an order belonging to the authenticated user.

    Check Stripe payment status, currency and amount before marking it paid.
    On the first successful status change, clear a matching cart and attempt
    to send a confirmation email. Preserve a cart changed after checkout.
    """
    try:
        order_id = int(request.GET.get('order_id', ''))
    except (TypeError, ValueError):
        raise Http404

    order = get_object_or_404(
        Order,
        pk=order_id,
        user=request.user,
    )

    if order.status == 'paid':
        return render(
            request,
            'catalog/checkout_success.html',
            {'order': order},
        )

    if order.status != 'pending' or not order.stripe_session_id:
        return redirect('catalog:cart_detail')

    try:
        session = stripe.checkout.Session.retrieve(
            order.stripe_session_id,
        )
    except stripe.StripeError:
        logger.exception(
            'Could not retrieve Stripe session for order %s',
            order.pk,
        )
        return redirect('catalog:cart_detail')

    if session.payment_status != 'paid':
        return redirect('catalog:cart_detail')

    total = order.get_total()

    if (
        session.currency != 'uah'
        or session.amount_total != int(total * 100)
    ):
        raise PermissionDenied

    updated = Order.objects.filter(
        pk=order.pk,
        status='pending',
    ).update(status='paid')

    order.refresh_from_db()

    if order.status != 'paid':
        return redirect('catalog:cart_detail')

    if updated:
        cart = Cart(request)

        current_items = sorted(
            (book_id, item['quantity'], Decimal(item['price']))
            for book_id, item in cart.cart.items()
        )

        paid_items = sorted(
            (str(item.book_id), item.quantity, item.price)
            for item in order.items.all()
        )

        if current_items == paid_items:
            cart.clear()

        if request.user.email:
            message = (
                _('Замовлення #%(order_id)s оплачено.')
                % {'order_id': order.pk}
            )
            message += '\n' + (
                _('Сума: %(total)s грн')
                % {'total': total}
            )

            try:
                send_mail(
                    subject=_('Дякуємо за замовлення'),
                    message=message,
                    from_email=None,
                    recipient_list=[request.user.email],
                )
            except (SMTPException, OSError):
                logger.exception(
                    'Could not send confirmation for order %s',
                    order.pk,
                )

    return render(
        request,
        'catalog/checkout_success.html',
        {'order': order},
    )


def checkout_cancel(request):
    """Display the cancellation page while preserving the order and cart."""
    return render(request, 'catalog/checkout_cancel.html')