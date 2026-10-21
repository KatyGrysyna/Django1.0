# Книжковий магазин

Навчальний Django-проєкт: каталог книг, категорії, реєстрація користувачів, кошик, оформлення замовлень через Stripe та асинхронний JSON API.

Інтерфейс підтримує українську й англійську мови.

## Технології

- Python 3.12 та Django 6.1.
- PostgreSQL 16.
- Docker Compose.
- Stripe Checkout.
- Bootstrap.
- pytest, pytest-django, pytest-cov і factory-boy.
- Redis 7 як окремий сервіс у Docker Compose.

Залежності наведено в `requirements.txt`.

## Можливості

- Каталог із фільтруванням за категорією та пагінацією.
- Сторінка книги з автором, описом, ціною та залишком.
- Створення, редагування й видалення книг із перевіркою прав.
- Реєстрація, вхід і вихід користувачів.
- Кошик у сесії користувача.
- Збереження ціни придбання в позиціях замовлення.
- Оформлення замовлення через POST-форму з CSRF-токеном.
- Перевірка власника замовлення, статусу оплати, валюти та суми через Stripe.
- Збереження кошика, зміненого під час оплати.
- Асинхронні API для книг і категорій.
- Українська та англійська локалізації.
- Логування запитів і помилок.

## Запуск через Docker

Потрібні Git і запущений Docker Desktop із підтримкою Linux-контейнерів.

### 1. Клонування

```powershell
git clone https://github.com/KatyGrysyna/Django1.0.git
cd Django1.0
```

### 2. Налаштування середовища

Створіть `.env` у корені проєкту, поруч із `manage.py`:

```dotenv
SECRET_KEY=replace_with_a_long_random_secret_key
DEBUG=True

DB_NAME=bookshop
DB_USER=bookshop_user
DB_PASSWORD=replace_with_your_local_database_password
DB_HOST=db
DB_PORT=5432

REDIS_HOST=redis
REDIS_PORT=6379

STRIPE_PUBLISHABLE_KEY=pk_test_replace_me
STRIPE_SECRET_KEY=sk_test_replace_me
```

Замініть `SECRET_KEY` і `DB_PASSWORD` власними значеннями. Для перевірки оплати вкажіть власні тестові ключі Stripe.

У Docker використовується `DB_HOST=db`, оскільки `db` — назва сервісу PostgreSQL.

Файл `.env` виключено з Git через `.gitignore`.

### 3. Запуск контейнерів

```powershell
docker-compose up -d --build
```

Під час запуску web-контейнер очікує PostgreSQL, застосовує міграції, збирає статичні файли та запускає сервер розробки.

Сторінки:

- [Український каталог](http://127.0.0.1:8000/uk/)
- [English catalogue](http://127.0.0.1:8000/en/)
- [Адміністрування](http://127.0.0.1:8000/uk/admin/)

Перегляд логів:

```powershell
docker-compose logs -f web
```

### 4. Створення адміністратора

```powershell
docker-compose exec web python manage.py createsuperuser
```

Увійдіть до адмінпанелі та створіть категорії й книги.

Звичайним користувачам для керування книгами потрібні відповідні права `add_book`, `change_book` або `delete_book`. Суперкористувач має ці права.

### 5. Зупинка

```powershell
docker-compose down
```

Ця команда зберігає іменований том PostgreSQL із даними.

## Оплата та повідомлення

Для навчальної перевірки використовується тестовий режим Stripe.

Замовлення та його позиції створюються в одній транзакції бази даних. Запит до Stripe виконується після її завершення.

При помилці створення Stripe Session сторінка кошика повертає HTTP 503 із повідомленням. Кошик зберігається, замовлення залишається у статусі `pending`.

Під час повернення зі Stripe сервер перевіряє оплату. Кошик очищається лише тоді, коли його книги, кількості та ціни відповідають оплаченому замовленню.

Лист підтвердження в налаштуваннях розробки виводиться в консоль web-контейнера.

Поточна реалізація підтверджує оплату під час відкриття сторінки успіху. Stripe webhooks і захист повторного оформлення через idempotency key не реалізовані.

## Асинхронний API

Усі наведені endpoints приймають GET-запити. Замість префікса `/uk/` також можна використовувати `/en/`.

| Endpoint | Призначення |
| --- | --- |
| `/uk/api/books/` | Список книг із фільтром і пагінацією |
| `/uk/api/books/<id>/` | Деталі книги та її категорії |
| `/uk/api/categories/` | Категорії з кількістю книг |

Параметри списку книг:

| Параметр | Значення |
| --- | --- |
| `category` | Необов'язковий slug категорії |
| `page` | Номер сторінки, починаючи з 1 |
| `page_size` | Від 1 до 100; за замовчуванням 20 |

Приклад:

```text
/uk/api/books/?page=1&page_size=10
```

Відповідь містить `books` та `pagination` із полями:

- `page`;
- `page_size`;
- `total`;
- `total_pages`;
- `has_next`;
- `has_previous`.

Некоректні параметри повертають HTTP 400. Сторінка поза діапазоном повертає HTTP 404.

Для порожнього каталогу перша сторінка повертає порожній список і HTTP 200.

## REST API — Django REST Framework

REST API доступний за префіксом `/api/` без мовного префікса.

Використано ViewSets, DefaultRouter, вкладені serializers, django-filter,
SimpleJWT, drf-spectacular та django-cors-headers.

### Документація

- [Swagger UI](http://127.0.0.1:8000/api/docs/)
- [OpenAPI schema](http://127.0.0.1:8000/api/schema/)

### Endpoints

| Endpoint | Методи | Призначення |
| --- | --- | --- |
| `/api/books/` | GET, POST | Список і створення книг |
| `/api/books/<id>/` | GET, PUT, PATCH, DELETE | Перегляд, редагування та видалення книги |
| `/api/categories/` | GET, POST | Список і створення категорій |
| `/api/categories/<id>/` | GET, PUT, PATCH, DELETE | Операції з категорією |
| `/api/orders/` | GET, POST | Власні замовлення та створення замовлення |
| `/api/orders/<id>/` | GET, PUT, PATCH, DELETE | Операції з власним замовленням |
| `/api/cart/` | GET, POST | Перегляд і створення власного кошика |
| `/api/cart/<id>/` | GET, PUT, PATCH, DELETE | Операції з власним кошиком |

### JWT-авторизація

| Endpoint | Метод | Тіло запиту |
| --- | --- | --- |
| `/api/token/` | POST | `username`, `password` |
| `/api/token/refresh/` | POST | `refresh` |
| `/api/token/verify/` | POST | `token` |

Отримання токенів повертає `access` та `refresh`.
Access-токен діє 15 хвилин, refresh-токен — 1 день.

Для захищених запитів використовується заголовок:

```text
Authorization: Bearer <access_token>
```

У Swagger UI натисніть **Authorize** та вставте access-токен без префікса `Bearer`.

### Права доступу

- Перегляд книг і категорій доступний без авторизації.
- Створення, редагування та видалення книг і категорій доступні користувачам із `is_staff=True`. Це перевіряє `IsAdminOrReadOnly`, побудований на `IsAdminUser`.
- Для замовлень і кошиків використано `IsAuthenticated` та власний permission `IsOwnerOrReadOnly`.
- Querysets замовлень і кошиків обмежені поточним користувачем. Звернення до чужого об'єкта повертає HTTP 404.
- Власник призначається сервером. Переданий клієнтом `user` не змінює власника.
- Замовлення можна змінити або видалити лише у статусі `pending` без створеної Stripe Session.

### Вкладені дані

Книга містить вкладену категорію. Позиції замовлення та кошика містять вкладені книги.

Для створення або редагування книги категорія передається через `category_id`.

Приклад створення замовлення або кошика:

```json
{
  "items": [
    {
      "book_id": 1,
      "quantity": 2
    }
  ]
}
```

Для замовлення список `items` обов'язковий і має містити хоча б одну позицію.
Кількість повинна бути додатною; повторення книги в одному списку заборонено.

Ціна позиції замовлення визначається сервером і зберігається на момент запису.
Сума кошика розраховується за поточними цінами книг.

Переданий під час оновлення список `items` повністю замінює попередні позиції.
Порожній список очищає кошик. Один користувач може мати один кошик у базі даних.

REST API використовує моделі `Cart` і `CartItem` у базі даних.
Кошик HTML-сайту зберігається окремо в сесії; автоматичної синхронізації між ними немає.

Створення замовлення через REST API зберігає його зі статусом `pending`.
Оплата через Stripe реалізована в HTML-інтерфейсі.

### Пагінація та фільтрування

Списки повертають по **20 об'єктів на сторінку**.
Відповідь містить `count`, `next`, `previous` та `results`.

Приклад:

```text
/api/books/?page=2
```

Фільтри книг:

- `category` — ID категорії;
- `category_slug` — slug категорії;
- `title` — частина назви без урахування регістру;
- `author` — частина імені автора без урахування регістру;
- `min_price`, `max_price` — межі ціни включно.

Приклад:

```text
/api/books/?min_price=100&max_price=500
```

Категорії можна фільтрувати за точними значеннями `name` і `slug`.
Замовлення — за `status`, `created_after` та `created_before`.
Дати передаються у форматі ISO 8601.

### Throttling

- Анонімні запити: 60 за хвилину.
- Авторизовані запити: 300 за хвилину.
- JWT endpoints: 10 за хвилину.

Перевищення ліміту повертає HTTP 429 із заголовком `Retry-After`.

### CORS

За замовчуванням дозволено такі origins:

- `http://localhost:3000`
- `http://127.0.0.1:3000`
- `http://localhost:5173`
- `http://127.0.0.1:5173`

Власний список можна задати в `.env` через кому:

```dotenv
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
```

CORS застосовується до шляхів `/api/`.

### Перевірка REST API

Реалізовано **80 API-тестів** із використанням `APIClient`:

- каталог і категорії — 24;
- замовлення — 21;
- кошик — 19;
- JWT, throttling, CORS і документація — 16.

Запуск:

```powershell
docker-compose exec web python -m pytest tests/test_api_catalog.py tests/test_api_orders.py tests/test_api_cart.py tests/test_api_config.py -v
```

Перевірка OpenAPI-схеми:

```powershell
docker-compose exec web python manage.py spectacular --validate --fail-on-warn --file /tmp/bookshop-schema.yml
```

Схема пройшла перевірку без помилок і попереджень.


## Тестування

Тести використовують `shop_project.settings_test`, окрему тестову базу PostgreSQL, фабрики даних та підміну звернень до Stripe.

Контейнери мають бути запущені.

Перевірка конфігурації:

```powershell
docker-compose exec web python manage.py check
```

Усі тести з вимірюванням покриття:

```powershell
docker-compose exec web python -m pytest --cov --cov-report=term-missing --cov-report=html --cov-fail-under=70
```

Результат перевіреного повного запуску:

| Показник | Результат |
| --- | --- |
| Усі тести | 160 passed |
| API-тести | 80 passed |
| Загальне покриття | 96,99% |
| `catalog/models.py` | 97,33% |
| `accounts/models.py` | 100% |
| `catalog/serializers.py` | 100% |
| `catalog/permissions.py` | 100% |
| `catalog/async_views.py` | 100% |

### AI-тести моделей

Для завдання обрано `Book`, `Order` та `OrderItem`.

У `tests/test_ai_models.py` містяться 10 тестових випадків. У кожній тестовій функції є коментар:

```python
# Generated with AI, reviewed and modified
```

Окремий запуск із XML-звітом:

```powershell
docker-compose exec web python -m pytest tests/test_ai_models.py -v --cov=catalog.models --cov-report=term-missing --cov-report=xml:coverage_models.xml --cov-fail-under=60
```

Звіт `coverage_models.xml` збережено під час попереднього завдання з AI, до додавання моделей `Cart` і `CartItem`. Покриття модуля `catalog.models` у тому окремому запуску становило 97,96%. Поточні результати повного запуску наведено в таблиці вище.   

Звіт для здачі: [coverage_models.xml](coverage_models.xml).

## AI Usage

Для виконання завдання використано AI-асистента OpenAI Codex.

Основний запит містив такі частини:

- «Виберіть 3 складних views/serializers з вашого проєкту».
- «Проведіть code review через ChatGPT/Claude».
- «Згенеруйте тести для 2-3 моделей за допомогою AI».
- «Згенеруйте docstrings для всіх views з AI».
- «Оновіть README з AI».

AI допоміг:

1. Провести ревью `checkout`, `checkout_success` та асинхронного `book_list`.
2. Додати POST-оформлення, транзакцію запису замовлення й обробку помилок Stripe.
3. Зберегти кошик, змінений до першого підтвердження оплати.
4. Додати перевірку параметрів і пагінацію асинхронного API.
5. Створити тести моделей і тести для змін після ревью.
6. Написати docstrings для всіх 16 власних views та оновити документацію.

Авторка проєкту переносила зміни в PyCharm, запускала перевірки та надавала результати для аналізу.

Документація використання AI:

- [AI_REVIEW.md](AI_REVIEW.md) — початковий код, рекомендації, рішення та фінальний код трьох views.
- [AI_PROMPTS.md](AI_PROMPTS.md) — уривки фактичного запиту та контекст подальшої роботи.