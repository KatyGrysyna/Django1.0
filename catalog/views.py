import logging
from smtplib import SMTPException

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from .cart import Cart
from .forms import BookForm
from .models import Book, Category, Order, OrderItem

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)


class BookListView(ListView):
    model = Book
    template_name = 'catalog/book_list.html'
    context_object_name = 'books'
    paginate_by = 6

    def get_queryset(self):
        queryset = Book.objects.order_by('id')
        category_slug = self.request.GET.get('category')
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = Category.objects.all()
        context['selected_category'] = self.request.GET.get('category')
        return context


class BookDetailView(DetailView):
    model = Book
    template_name = 'catalog/book_detail.html'
    context_object_name = 'book'


class BookCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Book
    form_class = BookForm
    template_name = 'catalog/book_form.html'
    success_url = reverse_lazy('catalog:book_list')
    permission_required = 'catalog.add_book'


class BookUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Book
    form_class = BookForm
    template_name = 'catalog/book_form.html'
    success_url = reverse_lazy('catalog:book_list')
    permission_required = 'catalog.change_book'


class BookDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = Book
    template_name = 'catalog/book_confirm_delete.html'
    success_url = reverse_lazy('catalog:book_list')
    permission_required = 'catalog.delete_book'


def cart_add(request, book_id):
    cart = Cart(request)
    book = get_object_or_404(Book, id=book_id)
    cart.add(book=book)
    return redirect('catalog:cart_detail')


def cart_remove(request, book_id):
    cart = Cart(request)
    book = get_object_or_404(Book, id=book_id)
    cart.remove(book)
    return redirect('catalog:cart_detail')


def cart_clear(request):
    cart = Cart(request)
    cart.clear()
    return redirect('catalog:cart_detail')


def cart_detail(request):
    cart = Cart(request)
    return render(request, 'catalog/cart_detail.html', {'cart': cart})


@login_required
def checkout(request):
    cart = Cart(request)

    if len(cart) == 0:
        return redirect('catalog:cart_detail')

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

    order.stripe_session_id = session.id
    order.save()

    return HttpResponseRedirect(session.url, status=303)
@login_required
def checkout_success(request):
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
        Cart(request).clear()

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
    return render(request, 'catalog/checkout_cancel.html')