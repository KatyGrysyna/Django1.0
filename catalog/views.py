import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404, redirect, render
from .models import Book, Category, Order, OrderItem
from .cart import Cart

stripe.api_key = settings.STRIPE_SECRET_KEY


class BookListView(ListView):
    model = Book
    template_name = 'catalog/book_list.html'
    context_object_name = 'books'
    paginate_by = 6

    def get_queryset(self):
        queryset = Book.objects.all()
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
    template_name = 'catalog/book_form.html'
    fields = ['title', 'author', 'price', 'description', 'stock', 'category']
    success_url = reverse_lazy('catalog:book_list')
    permission_required = 'catalog.add_book'


class BookUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Book
    template_name = 'catalog/book_form.html'
    fields = ['title', 'author', 'price', 'description', 'stock', 'category']
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

    return redirect(session.url, code=303)
def checkout_success(request):
    order_id = request.GET.get('order_id')
    order = get_object_or_404(Order, id=order_id)
    order.status = 'paid'
    order.save()

    cart = Cart(request)
    cart.clear()

    return render(request, 'catalog/checkout_success.html', {'order': order})


def checkout_cancel(request):
    return render(request, 'catalog/checkout_cancel.html')