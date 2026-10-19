# AI Code Review — Книжковий магазин

## Мета

Провести за допомогою AI ревью трьох views, застосувати обґрунтовані рекомендації та перевірити зміни тестами.

## Обрані views

1. `catalog.views.checkout` — створення замовлення та Stripe Checkout Session.
2. `catalog.views.checkout_success` — перевірка оплати та підтвердження замовлення.
3. `catalog.async_views.book_list` — асинхронний список книг.

Оригінальний код взято зі стану проєкту до змін у гілці `ai-improvements`: коміт `5da4ce4`.

## 1. Ревью checkout

Файл: `catalog/views.py`.

### Оригінальний код

```python
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
```

### AI-рекомендації

1. **Використати POST для створення замовлення.**
   У початковій версії GET-запит створював записи в базі.
   Додати `require_POST`, а в шаблоні кошика використати POST-форму з CSRF-токеном.

2. **Створювати замовлення та його позиції в одній транзакції.**
   Використати `transaction.atomic()`, щоб помилка під час запису позиції не залишала частково створене замовлення.
   Запит до Stripe виконувати після завершення транзакції, щоб не тримати її відкритою під час мережевого очікування.

3. **Обробляти помилки Stripe.**
   Перехоплювати `stripe.StripeError`, записувати помилку в лог та показувати повідомлення з HTTP 503.
   Зберігати кошик, щоб користувач міг повторити спробу.

### Рішення та застосовані зміни

Усі три рекомендації прийнято та реалізовано.

Додано імпорти:

```python
from django.db import transaction
from django.views.decorators.http import require_POST
```

У шаблоні `templates/catalog/cart_detail.html` додано:

- POST-форму оформлення замовлення з CSRF-токеном;
- відображення повідомлення `checkout_error`;
- посилання на вхід для неавторизованого користувача з поверненням до кошика.

### Фінальний код

```python
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
```

### Перевірка

У `tests/test_checkout.py` додано тести:

- `test_checkout_rejects_get` — GET повертає HTTP 405 і не створює замовлення;
- `test_checkout_handles_stripe_creation_error` — помилка Stripe повертає HTTP 503, кошик зберігається;
- `test_checkout_rolls_back_partial_order` — помилка запису позиції відкочує створення замовлення та його позицій;
- `test_checkout_requires_csrf_token` — POST без CSRF-токена відхиляється, а з коректним токеном виконується.

Команда запуску:

```powershell
docker-compose exec web python -m pytest tests/test_checkout.py -v
```

### Межі реалізації

Транзакція охоплює лише записи в базі даних. Вона не відкочує операції Stripe.

Після помилки створення Stripe Session замовлення залишається у статусі `pending`, а кошик зберігається. Повторний POST може створити нове замовлення: захист від повторного оформлення через idempotency key у цій зміні не реалізовано.

## 2. Ревью checkout_success

Файл: `catalog/views.py`.

### Оригінальний код

```python
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
```

### Виявлена проблема

Користувач може відкрити Stripe, а в іншій вкладці змінити кошик: додати книгу або змінити кількість.

Під час першого підтвердження оплати початкова версія безумовно виконувала `Cart(request).clear()`. Через це зміни в кошику втрачалися, хоча вони не належали до оплаченого замовлення.

Обробка повторного відкриття вже оплаченого замовлення була передбачена раніше. Виправлення стосується саме першого підтвердження оплати.

### AI-рекомендації

1. Перед очищенням порівнювати поточний кошик із позиціями оплаченого замовлення: ID книги, кількість і ціну.
2. Перетворювати ціни з кошика на `Decimal`, щоб порівнювати числові значення без втрати точності.
3. Очищати кошик лише за повного збігу. Якщо він змінився, зберігати його повністю.
4. Зберегти наявні перевірки власника замовлення, статусу Stripe, валюти та суми.
5. Додати тести для змін кошика до першого підтвердження оплати й описати поведінку в docstring.

### Рішення та застосовані зміни

Рекомендації прийнято та реалізовано.

Додано імпорт:

```python
from decimal import Decimal
```

Безумовне очищення замінено порівнянням відсортованих списків позицій.

Перевірки власника, статусу оплати, валюти та суми вже існували до цього ревью і збережені. Умовне оновлення `pending` → `paid` також збережене: очищення кошика та спроба надсилання листа виконуються лише тоді, коли цей запит змінив статус.

### Фінальний код

```python
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
```

### Перевірка

У `tests/test_checkout.py` додано параметризований тест `test_first_payment_confirmation_preserves_changed_cart`.

Він перевіряє три зміни кошика до першого підтвердження оплати:

- додавання іншої книги;
- зміну кількості;
- зміну ціни позиції.

У кожному сценарії замовлення має перейти у статус `paid`, а змінений кошик — зберегтися.

Наявні тести також перевіряють:

- очищення кошика, який відповідає оплаченому замовленню;
- повторне відкриття сторінки без повторного надсилання листа;
- відмову в підтвердженні чужого замовлення;
- відхилення неправильної валюти або суми;
- збереження стану при помилці Stripe;
- збереження підтвердженої оплати при помилці надсилання листа.

Команда запуску:

```powershell
docker-compose exec web python -m pytest tests/test_checkout.py -v
```

## 3. Ревью асинхронного book_list

Файл: `catalog/async_views.py`.

### Оригінальний код

```python
@require_GET
async def book_list(request):
    queryset = Book.objects.order_by('id')

    category_slug = request.GET.get('category')
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)

    books = [
        {
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'price': str(book.price),
            'stock': book.stock,
            'category_id': book.category_id,
        }
        async for book in queryset
    ]

    return JsonResponse(
        {'books': books},
        json_dumps_params={'ensure_ascii': False},
    )
```

### Виявлена проблема

View повертала всі книги, які відповідають фільтру. Зі збільшенням каталогу зростали обсяг відповіді та кількість об'єктів, завантажених у пам'ять за один запит.

Асинхронне виконання запиту саме по собі не обмежує кількість отриманих записів.

### AI-рекомендації

1. Додати параметри `page` та `page_size`.
2. Повертати 20 книг за замовчуванням і дозволяти не більше 100 на сторінку.
3. Перевіряти параметри: номер сторінки має бути додатним цілим числом, розмір сторінки — цілим числом від 1 до 100.
4. Повертати HTTP 400 для некоректних параметрів і HTTP 404 для сторінки поза діапазоном.
5. Застосовувати фільтр категорії до підрахунку та вибору сторінки.
6. Зберегти сортування за ID й асинхронну роботу з ORM: `await queryset.acount()` та `async for`.
7. Додати до JSON інформацію про поточну сторінку, загальну кількість записів і наявність сусідніх сторінок.

### Рішення та застосовані зміни

Рекомендації прийнято та реалізовано.

До виконання запитів перевіряються параметри пагінації. Із бази завантажуються об'єкти лише запитаної сторінки.

Поле `books` збережено, додано об'єкт `pagination`. За відсутності параметрів відповідь тепер містить перші 20 книг. Для отримання всього каталогу клієнт має послідовно запитувати сторінки.

Для порожнього каталогу сторінка 1 повертає HTTP 200, порожній список, `total = 0` та `total_pages = 1`.

### Фінальний код

```python
@require_GET
async def book_list(request):
    """Return a filtered page of books using asynchronous ORM queries.

    Default to 20 books per page and allow at most 100.
    Return HTTP 400 for invalid parameters and 404 for a missing page.
    """
    try:
        page = int(request.GET.get('page', '1'))
        page_size = int(request.GET.get('page_size', '20'))

        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError

    except (TypeError, ValueError):
        return JsonResponse(
            {
                'error': (
                    'page must be a positive integer; '
                    'page_size must be an integer from 1 to 100.'
                ),
            },
            status=400,
        )

    queryset = Book.objects.order_by('id')

    category_slug = request.GET.get('category')
    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)

    total = await queryset.acount()
    total_pages = max(1, (total + page_size - 1) // page_size)

    if page > total_pages:
        return JsonResponse(
            {'error': 'Page not found.'},
            status=404,
        )

    start = (page - 1) * page_size

    books = [
        {
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'price': str(book.price),
            'stock': book.stock,
            'category_id': book.category_id,
        }
        async for book in queryset[start:start + page_size]
    ]

    return JsonResponse(
        {
            'books': books,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_previous': page > 1,
            },
        },
        json_dumps_params={'ensure_ascii': False},
    )
```

### Перевірка

У `tests/test_views.py` додано тести, які перевіряють:

- першу, проміжну та останню сторінки відфільтрованого каталогу;
- порядок книг і відсутність книг з інших категорій;
- загальну кількість записів та прапорці `has_next` і `has_previous`;
- порожній каталог;
- HTTP 400 для нечислових, нульових або від'ємних значень сторінки та некоректного розміру сторінки;
- відхилення `page_size = 101`;
- HTTP 404 для сторінки поза діапазоном;
- розмір сторінки 20 за замовчуванням;
- можливість передати `page_size = 100`.

Команда запуску:

```powershell
docker-compose exec web python -m pytest tests/test_views.py -v
```