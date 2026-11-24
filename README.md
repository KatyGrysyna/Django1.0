# Книжковий магазин і складський сервіс

[![Django CI](https://github.com/KatyGrysyna/Django1.0/actions/workflows/django.yml/badge.svg?branch=microservices-warehouse&event=push)](https://github.com/KatyGrysyna/Django1.0/actions/workflows/django.yml?query=branch%3Amicroservices-warehouse)
![Coverage requirement](https://img.shields.io/badge/coverage_requirement-%E2%89%A5_70%25-brightgreen)

Навчальний проєкт із двома окремими Django-застосунками в одному репозиторії:

- **ProjectA** — книжковий магазин: каталог, користувачі, кошик, замовлення та Stripe Checkout.
- **ProjectB** — склад: залишки книг, резервування, підтвердження, звільнення та автоматичне завершення прострочених резервів.

Кожен проєкт має власні налаштування, міграції, Custom User Model і базу PostgreSQL. ProjectA звертається до ProjectB через REST API з JWT. Прямого доступу до бази іншого проєкту немає.

Робоча гілка: `microservices-warehouse`. Frontend — Django templates і Bootstrap; окрема SPA не використовується.

## Опубліковане демо

| Ресурс | ProjectA | ProjectB |
| --- | --- | --- |
| Інтерфейс | [Книжковий магазин](https://bookshop-ci-cd-deploy.onrender.com/uk/) | [Warehouse Swagger UI](https://bookshop-warehouse.onrender.com/api/docs/) |
| Swagger UI | [Bookshop API](https://bookshop-ci-cd-deploy.onrender.com/api/docs/) | [Warehouse API](https://bookshop-warehouse.onrender.com/api/docs/) |
| OpenAPI schema | [Bookshop schema](https://bookshop-ci-cd-deploy.onrender.com/api/schema/) | [Warehouse schema](https://bookshop-warehouse.onrender.com/api/schema/) |
| Health check | [Bookshop health](https://bookshop-ci-cd-deploy.onrender.com/health/) | [Warehouse health](https://bookshop-warehouse.onrender.com/health/) |

ProjectB є API-сервісом: для знайомства з ним відкривайте Swagger, а не кореневу адресу. Операції зі складом потребують JWT і відповідних прав.

Оплата в демо працює у **Stripe Sandbox**. Реальні платежі для перевірки не потрібні.

## Технології

Обидва проєкти використовують Python 3.12, Django 6.1, Django REST Framework, PostgreSQL 16, Redis, Celery, Docker Compose, NGINX, Gunicorn, SimpleJWT, drf-spectacular, pytest та Sentry.

Додатково ProjectA використовує Stripe, Bootstrap, django-filter, CORS і асинхронні JSON views. Production-конфігурації обох проєктів використовують WhiteNoise.

Залежності: `requirements.txt` для ProjectA і `project_b/requirements.txt` для ProjectB. У локальному Compose використовується Redis 7; у хмарі — сумісний із Redis Render Key Value на Valkey.

## Архітектура

Схема локального середовища Docker Compose:

~~~mermaid
flowchart LR
    Browser["Браузер / API-клієнт"]
    Stripe["Stripe Sandbox"]

    subgraph A["ProjectA — книжковий магазин"]
        NA["NGINX :8000"]
        WA["Gunicorn + Django / DRF"]
        DA[("PostgreSQL A")]
        RA[("Redis A")]
        CA["Celery worker A"]
        BA["Celery Beat A"]
        NA --> WA
        WA --> DA
        WA --> RA
        BA --> RA
        RA --> CA
        CA --> DA
    end

    subgraph B["ProjectB — склад"]
        NB["NGINX :8001"]
        WB["Gunicorn + Django / DRF"]
        DB[("PostgreSQL B")]
        RB[("Redis B")]
        CB["Celery worker B"]
        BB["Celery Beat B"]
        NB --> WB
        WB --> DB
        WB --> RB
        BB --> RB
        RB --> CB
        CB --> DB
    end

    Browser --> NA
    Browser --> NB
    WA -->|"REST API + JWT"| WB
    CA -->|"REST API + JWT"| WB
    WA --> Stripe
    CA --> Stripe
    Browser -->|"Checkout"| Stripe
~~~

У контейнерній мережі ProjectA використовує адресу `http://warehouse:8000/api`. Для браузера доступні NGINX на портах 8000 і 8001.

У хмарі HTTPS забезпечує Render, статичні файли віддає WhiteNoise, а Gunicorn обслуговує Django. Окремі NGINX-контейнери налаштовані для Compose. Хмарний обмін між проєктами йде через публічний HTTPS API.

### Дані та оформлення замовлення

ProjectB є джерелом складських залишків. Поле `Book.stock` у ProjectA містить синхронізовану доступну кількість для каталогу. Зв'язок між проєктами — числовий `external_book_id`, що відповідає ID книги в ProjectA.

1. ProjectA створює замовлення та запитує резерв у ProjectB.
2. ProjectB у транзакції блокує складські записи, перевіряє доступну кількість і створює резерв із терміном дії.
3. ProjectA створює Stripe Checkout Session. Для оформлення зі складським резервом використовується Stripe idempotency key.
4. Під час повернення зі Stripe ProjectA перевіряє власника замовлення, статус платежу, валюту та суму.
5. Підтвердження резерву зменшує загальну та зарезервовану кількість у ProjectB.
6. Фонова звірка замовлень перевіряє Stripe і завершує складські операції, зокрема коли покупець не повернувся на сторінку успіху.

Повторний запит резервування з тим самим користувачем, номером замовлення та складом позицій не створює другого резерву. Підтвердження та звільнення враховують поточний стан. Термін резерву — одна година; прострочені резерви звільняє Celery.

Stripe webhooks не реалізовані: використано перевірку при поверненні та періодичну звірку. Кнопка повернення зі Stripe сама по собі не підтверджує оплату.

### Обробка помилок

Клієнт складу має таймаути підключення й читання, перевіряє HTTP-статуси та структуру відповіді, повторно авторизується після 401. Типові ситуації:

| Ситуація | Обробка |
| --- | --- |
| Некоректний запит | HTTP 400, повідомлення про валідацію |
| Немає JWT / неправильні облікові дані | HTTP 401 |
| Бракує прав | HTTP 403 |
| Чужий або відсутній резерв | HTTP 404 |
| Недостатній залишок або конфлікт стану | HTTP 409 |
| Склад недоступний / таймаут | Виняток клієнта, логування, повідомлення користувачу; кошик зберігається |

У логах клієнта фіксуються метод, шлях API та статус. Паролі й JWT не додаються до цих повідомлень. Транзакції PostgreSQL, блокування рядків і перевірки стану захищають резерви від конкурентних змін.

## Локальний запуск з нуля

Потрібні Git, Docker Desktop із Linux-контейнерами та Docker Compose v2. Команди нижче виконуються з кореня репозиторію в PowerShell. Якщо доступна лише команда `docker compose`, використовуйте її замість `docker-compose`.

### 1. Клонування

~~~powershell
git clone --branch microservices-warehouse https://github.com/KatyGrysyna/Django1.0.git
cd Django1.0
~~~

### 2. Два файли середовища

Створіть `.env` у корені репозиторію:

~~~dotenv
DJANGO_SETTINGS_MODULE=shop_project.settings.development
SECRET_KEY=replace_with_a_long_random_bookshop_key
DEBUG=True
DB_NAME=bookshop
DB_USER=bookshop_user
DB_PASSWORD=replace_with_a_local_bookshop_database_password
DB_HOST=db
DB_PORT=5432
REDIS_HOST=redis
REDIS_PORT=6379
STRIPE_PUBLISHABLE_KEY=pk_test_replace_me
STRIPE_SECRET_KEY=sk_test_replace_me
WAREHOUSE_ENABLED=False
WAREHOUSE_API_URL=http://warehouse:8000/api
WAREHOUSE_USERNAME=bookshop_service
WAREHOUSE_PASSWORD=replace_after_creating_the_service_user
SENTRY_DSN=
~~~

Створіть окремий `project_b/.env`:

~~~dotenv
DJANGO_SETTINGS_MODULE=warehouse_project.settings
SECRET_KEY=replace_with_a_different_long_random_warehouse_key
DEBUG=True
POSTGRES_DB=warehouse
POSTGRES_USER=warehouse_user
POSTGRES_PASSWORD=replace_with_a_local_warehouse_database_password
DB_HOST=warehouse-db
DB_PORT=5432
REDIS_HOST=warehouse-redis
REDIS_PORT=6379
SENTRY_DSN=
~~~

Замініть шаблонні секрети власними значеннями. Для перевірки Checkout потрібні тестові ключі вашого Stripe Sandbox. Для цього локального запуска `DATABASE_URL` не задається: використовуються бази з Compose. Обидва `.env` виключені з Git; секрети не потрібно додавати до README або комітів.

### 3. Бази, міграції та застосунки

Спочатку запустіть PostgreSQL і Redis та підготуйте обидві схеми до запуску фонових задач:

~~~powershell
docker-compose config --quiet
docker-compose build web warehouse
docker-compose up -d --wait --wait-timeout 90 db redis warehouse-db warehouse-redis
docker-compose run --rm --no-deps --entrypoint python web manage.py migrate --noinput
docker-compose run --rm --no-deps --entrypoint python web manage.py collectstatic --noinput
docker-compose run --rm --no-deps --entrypoint python warehouse manage.py migrate --noinput
docker-compose run --rm --no-deps --entrypoint python warehouse manage.py setup_warehouse_groups
docker-compose run --rm --no-deps --entrypoint python warehouse manage.py collectstatic --noinput
docker-compose up -d --build
~~~

`web` також застосовує міграції й збирає статику через свій entrypoint. Попередня підготовка вище дозволяє запускати workers уже зі створеними таблицями.

| Сторінка | Адреса |
| --- | --- |
| Магазин українською | [localhost:8000/uk/](http://127.0.0.1:8000/uk/) |
| Магазин англійською | [localhost:8000/en/](http://127.0.0.1:8000/en/) |
| Адмінпанель ProjectA | [localhost:8000/uk/admin/](http://127.0.0.1:8000/uk/admin/) |
| Адмінпанель ProjectB | [localhost:8001/admin/](http://127.0.0.1:8001/admin/) |
| Swagger ProjectA | [localhost:8000/api/docs/](http://127.0.0.1:8000/api/docs/) |
| Swagger ProjectB | [localhost:8001/api/docs/](http://127.0.0.1:8001/api/docs/) |

### 4. Адміністратори, сервісний користувач і книги

Створіть окремих адміністраторів:

~~~powershell
docker-compose exec web python manage.py createsuperuser
docker-compose exec warehouse python manage.py createsuperuser
~~~

У ProjectA через адмінпанель створіть категорії та книги. Запам'ятайте ID книг.

У ProjectB:

1. Створіть Warehouse user `bookshop_service` з паролем.
2. Після збереження відкрийте його для редагування та додайте до `warehouse_clients`.
3. Залиште `Active=True`, `Staff=False`, `Superuser=False`.
4. Створіть Stock items. Поле «Book ID in ProjectA» має містити ID відповідної книги магазину; задайте назву та початкову загальну кількість, наприклад 10.

У кореневому `.env` встановіть `WAREHOUSE_ENABLED=True` і запишіть пароль цього сервісного користувача в `WAREHOUSE_PASSWORD`. Пароль бази даних і пароль користувача API — різні налаштування.

Повторно створіть контейнери ProjectA для завантаження зміненого середовища:

~~~powershell
docker-compose up -d --no-deps --force-recreate web celery celery-beat
~~~

Залишки в каталозі оновлюються фоновою задачею приблизно раз на хвилину. Перевірте логи:

~~~powershell
docker-compose logs --tail=80 celery warehouse-celery
~~~

Для перевірки покупки увійдіть у магазин, додайте книгу в кошик і пройдіть Checkout у Sandbox за [інструкцією Stripe](https://docs.stripe.com/testing). Після оплати перевірте замовлення й залишки в обох адмінпанелях.

### 5. Повторний запуск і зупинка

Запуск і перевірка стану:

~~~powershell
docker-compose up -d
docker-compose ps
~~~

Зупинка, коли роботу завершено:

~~~powershell
docker-compose down
~~~

`down` без видалення томів зберігає іменовані томи PostgreSQL. Повторно створювати бази й адміністраторів після звичайної зупинки не потрібно.

## API та права доступу

### ProjectA

Використано власну модель `accounts.CustomUser`, Django permissions, успадкування CBV та DRF ViewSets. HTML-операції з книгами перевіряють відповідні model permissions; API запису книг і категорій вимагає `is_staff=True`. Перегляд каталогу відкритий.

| Endpoint | Методи |
| --- | --- |
| `/api/books/`, `/api/categories/` | GET, POST |
| `/api/books/<id>/`, `/api/categories/<id>/` | GET, PUT, PATCH, DELETE |
| `/api/orders/`, `/api/cart/` | GET, POST |
| `/api/orders/<id>/`, `/api/cart/<id>/` | GET, PUT, PATCH, DELETE |
| `/api/token/`, `/api/token/refresh/`, `/api/token/verify/` | POST |

Замовлення та REST-кошики доступні тільки власнику. Змінювати або видаляти замовлення можна лише до запуску оплати й складського резервування, поки воно у дозволеному початковому стані.

Приклад тіла створення замовлення:

~~~json
{"items": [{"book_id": 1, "quantity": 2}]}
~~~

Ціну та власника встановлює сервер. HTML-кошик зберігається в сесії; REST-кошик — у базі даних. Вони не синхронізуються автоматично. REST-створення замовлення не відкриває Stripe: Checkout реалізовано в HTML-інтерфейсі.

Списки DRF мають пагінацію по 20 записів. Для книг доступні фільтри `category`, `category_slug`, `title`, `author`, `min_price`, `max_price`. Throttling: 60 запитів/хв для анонімних користувачів, 300 для авторизованих, 10 для JWT endpoints.

Окремо збережено асинхронний GET API попередніх завдань: `/uk/api/books/`, `/uk/api/books/<id>/`, `/uk/api/categories/`; також доступний префікс `/en/`.

### ProjectB

Власна модель користувача — `warehouse_accounts.WarehouseUser`. Stock API успадковує `ReadOnlyModelViewSet`; reservations API поєднує успадкування та create mixin.

| Група | Права |
| --- | --- |
| `warehouse_viewers` | Перегляд складських позицій |
| `warehouse_managers` | Перегляд, додавання й зміна складських позицій |
| `warehouse_clients` | Перегляд складу, створення, перегляд і зміна власних резервів |

Групи створює команда `setup_warehouse_groups` після міграцій. Наявність групи сама по собі не надає доступу до Django admin: для адміністративного інтерфейсу окремо потрібен staff-статус. Сервісному користувачу ProjectA він не потрібний.

| Endpoint | Методи | Призначення |
| --- | --- | --- |
| `/api/token/` | POST | Отримати JWT за username/password |
| `/api/token/refresh/` | POST | Оновити access token |
| `/api/stock/` | GET | Список залишків |
| `/api/stock/<id>/` | GET | Одна складська позиція |
| `/api/reservations/` | GET, POST | Власні резерви / створення резерву |
| `/api/reservations/<uuid>/` | GET | Власний резерв |
| `/api/reservations/<uuid>/confirm/` | POST | Підтвердити резерв |
| `/api/reservations/<uuid>/release/` | POST | Звільнити резерв |

`<id>` у stock detail — первинний ключ StockItem. Для пошуку за ID книги використовуйте `/api/stock/?external_book_id=1`. Запис залишків через stock REST API не відкритий; ним керують через адмінпанель з відповідними правами.

Приклад створення резерву:

~~~json
{
  "external_order_id": 123,
  "items": [
    {"external_book_id": 1, "quantity": 2},
    {"external_book_id": 3, "quantity": 1}
  ]
}
~~~

Новий резерв повертає 201; повторення того самого запиту — 200. Доступ до чужого резерву повертає 404. Можливі стани: `pending`, `confirmed`, `released`, `expired`.

У кожного проєкту власні користувачі та JWT. Токен ProjectA не використовується для входу у ProjectB. Для захищених запитів:

~~~text
Authorization: Bearer <access_token>
~~~

JWT access token діє 15 хвилин, refresh token — один день. Повні схеми запитів і відповідей наведені у Swagger обох проєктів.

## Кешування, Celery та локалізація

ProjectA кешує дані каталогу та HTML-фрагменти, ProjectB — список складських позицій. Кеш враховує мову; зміни даних інвалідують відповідні записи після завершення транзакції.

| Проєкт | Задача | Розклад |
| --- | --- | --- |
| A | `catalog.tasks.sync_warehouse_stock` | Кожні 60 секунд |
| A | `catalog.tasks.reconcile_warehouse_orders` | Кожні 60 секунд |
| A | `catalog.tasks.generate_inventory_report` | 08:00 UTC щодня |
| A | `catalog.tasks.clear_expired_sessions` | 03:15 UTC щодня |
| B | `inventory.expire_overdue_reservations` | Кожні 60 секунд |

ProjectA також має задачу повідомлення про оплату. Локальна пошта використовує console backend; на Render вона вимкнена через `EMAIL_ENABLED=False`. Звіти про залишки записуються в `reports/`.

Обидва проєкти підтримують українську й англійську мови. У магазині використовується перемикач мови; для Warehouse API можна передавати `Accept-Language: uk` або `en`. Переклади перевіряються тестами та компілюються в CI.

## Тестування

Запускайте ці команди в локальному Compose із локальними базами. Тести використовують окремі test settings і тестові PostgreSQL-бази; зовнішні виклики Stripe та складу підміняються в автоматизованих сценаріях.

~~~powershell
docker-compose exec -e DJANGO_SETTINGS_MODULE=shop_project.settings_test -e SENTRY_DSN= web python -m pytest --cov --cov-report=term-missing --cov-report=html --cov-fail-under=70
docker-compose exec -e DJANGO_SETTINGS_MODULE=warehouse_project.settings_test -e SENTRY_DSN= warehouse python -m pytest --cov --cov-report=term-missing --cov-report=html --cov-fail-under=70
~~~

Є unit-, integration- та API-тести: моделі, permissions, JWT, локалізація, кеш, недоступність сервісів, клієнт складу, checkout, життєвий цикл резервів, Celery tasks та конкурентне резервування в PostgreSQL.

Поріг **70% перевіряється окремо для кожного проєкту**. Badge показує вимогу, а не поточний вимір. Актуальні кількість тестів і coverage дивіться в останньому успішному [GitHub Actions run](https://github.com/KatyGrysyna/Django1.0/actions/workflows/django.yml?query=branch%3Amicroservices-warehouse), у кроці Run tests with coverage та артефактах `coverage-ProjectA` і `coverage-ProjectB`.

Додаткові перевірки:

~~~powershell
docker-compose exec web python manage.py check
docker-compose exec warehouse python manage.py check
docker-compose run --rm --no-deps --entrypoint python web -m black --check .
docker-compose run --rm --no-deps --entrypoint python web -m flake8 .
docker-compose exec web python manage.py spectacular --validate --fail-on-warn --file /tmp/bookshop-schema.yml
docker-compose exec warehouse python manage.py spectacular --validate --fail-on-warn --file /tmp/warehouse-schema.yml
~~~

## CI/CD

Workflow: `.github/workflows/django.yml`.

1. Дві matrix jobs перевіряють ProjectA і ProjectB: залежності, Black, flake8, переклади, Django checks, відсутність незбережених міграцій, Redis і pytest з coverage ≥70%.
2. Звіти XML та HTML зберігаються як `coverage-ProjectA` і `coverage-ProjectB` на 7 днів.
3. Після успішних перевірок збираються два Docker-образи: `bookshop` і `warehouse`.
4. Для push образи публікуються в Docker Hub із тегами назви гілки та повного SHA коміту.
5. Для push у `microservices-warehouse` запускаються два Render deploy hooks. Параметр `imgURL` містить SHA-тег, тому запитується розгортання образів цього коміту.

CI запускається для push у `main`, `ci-cd-deploy`, `microservices-warehouse`, для pull requests та вручну. Pull requests і ручний запуск перевіряють код і збирають образи, але не публікують їх і не запускають CD.

Налаштування GitHub Actions:

| Тип | Назва | Призначення |
| --- | --- | --- |
| Repository variable | `DOCKERHUB_USERNAME` | Власник Docker Hub repositories |
| Repository secret | `DOCKERHUB_TOKEN` | Публікація образів |
| Repository secret | `RENDER_BOOKSHOP_DEPLOY_HOOK` | Deploy hook сервісу магазину |
| Repository secret | `RENDER_WAREHOUSE_DEPLOY_HOOK` | Deploy hook складського сервісу |

Образи демо:

~~~text
docker.io/katerinkakc/bookshop:microservices-warehouse
docker.io/katerinkakc/warehouse:microservices-warehouse
~~~

Render приймає deploy hook асинхронно. Успішний крок GitHub підтверджує прийняття запиту; готовність розгортання перевіряється за `Deploy succeeded / Live` у Render та `/health/`. Registry і repository у `imgURL` мають збігатися з Image URL сервісу. [Документація deploy hooks](https://render.com/docs/deploy-hooks).

## Хмарне розгортання та налаштування

Обидва Docker-образи запущені як Render Web Services у Frankfurt. Для кожного:

- Docker Command: `bash /app/start-render.sh`.
- Health Check Path: `/health/`.
- Production settings через Environment Variables.
- Окремі `SECRET_KEY`, `DATABASE_URL` і Sentry-проєкти.

Скрипт старту застосовує міграції, збирає статику та запускає Gunicorn, Celery worker і Celery Beat. Скрипт ProjectB також налаштовує групи. Якщо один із процесів завершується, скрипт зупиняє інші та завершує контейнер із помилкою.

### Змінні середовища

| Змінна | ProjectA | ProjectB |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | `shop_project.settings.production` | `warehouse_project.settings_production` |
| `SECRET_KEY` | Власний випадковий секрет A | Інший випадковий секрет B |
| `DATABASE_URL` | URL PostgreSQL магазину | URL окремої PostgreSQL бази складу |
| `SENTRY_DSN` | Sentry project bookshop | Sentry project warehouse |
| `SENTRY_ENVIRONMENT` | `production` | `production` |
| `CACHE_URL` | Redis URL із суфіксом `/1` | Redis URL із суфіксом `/4` |
| `CELERY_BROKER_URL` | Redis URL із суфіксом `/0` | Redis URL із суфіксом `/3` |
| `CELERY_RESULT_BACKEND` | Redis URL із суфіксом `/2` | Redis URL із суфіксом `/5` |
| `EMAIL_ENABLED` | `False` | Не потрібна |
| `STRIPE_PUBLISHABLE_KEY` | Власний тестовий `pk_test_…` | Не потрібна |
| `STRIPE_SECRET_KEY` | Власний тестовий `sk_test_…` | Не потрібна |
| `WAREHOUSE_ENABLED` | `True` | Не потрібна |
| `WAREHOUSE_API_URL` | `https://bookshop-warehouse.onrender.com/api` | Не потрібна |
| `WAREHOUSE_USERNAME` | `bookshop_service` | Не потрібна |
| `WAREHOUSE_PASSWORD` | Пароль сервісного користувача у хмарній базі B | Не потрібна |

У демо база A — Render Postgres, база B — Neon PostgreSQL з прямим connection URL і SSL-параметрами. Локальні користувачі та книги автоматично не переносяться до хмарних баз: початкові дані й сервісний користувач створюються окремо.

Redis URL береться з Internal URL сервісу `bookshop-cache` у тому самому Render workspace і регіоні. Використовується один Key Value instance із шістьма логічними базами, розділеними між A та B. Політика пам'яті — `noeviction`; вона не замінює збереження даних на диск.

Render hostname автоматично додається до `ALLOWED_HOSTS`. Для власного домену налаштовуються `ALLOWED_HOSTS` і, за потреби, `CSRF_TRUSTED_ORIGINS`. Production settings вимикають DEBUG, вмикають HTTPS redirect, secure cookies, HSTS та захисні HTTP-заголовки.

### Моніторинг і перевірка

Кожен сервіс має окремий Sentry-проєкт. Production-конфігурації підключають SDK за наявності `SENTRY_DSN`; порожнє значення вимикає підключення. Приклад локального перегляду логів:

~~~powershell
docker-compose logs --tail=100 web warehouse celery warehouse-celery
~~~

У Render відповідні повідомлення доступні в Logs. Завершення задачі Celery позначається `succeeded`; це дозволяє перевіряти синхронізацію та звільнення резервів.

Публічна перевірка доступності:

~~~powershell
curl.exe -i https://bookshop-ci-cd-deploy.onrender.com/health/
curl.exe -i https://bookshop-warehouse.onrender.com/health/
~~~

Очікується HTTP 200. Warehouse health також повертає результати перевірки PostgreSQL і кешу.

### Обмеження безкоштовного демо

Render Free може зупиняти web service після 15 хвилин без вхідного трафіку; наступний запуск триває приблизно хвилину. Ліміт 750 instance hours на місяць спільний для workspace. Файли контейнера втрачаються після перезапуску; Free Postgres закінчує дію через 30 днів, а Free Key Value не гарантує збереження даних після перезапуску. SMTP-порти на Free web services заблоковані. [Обмеження Render Free](https://render.com/docs/free).

У цій конфігурації Celery worker і Beat працюють усередині web-контейнера й також зупиняються, коли він засинає. Це навчальне демо, а не гарантія цілодобового виконання задач. JSON-звіти в файловій системі контейнера не є довготривалим сховищем.

Перед завершенням строку Free Postgres потрібно експортувати потрібні дані та підготувати перенесення бази. Neon Free також має власні [ліміти використання](https://neon.com/docs/introduction/plans). Для демонстрації після простою спочатку відкрийте health-сторінки обох сервісів і дочекайтеся їх готовності.

## Використання AI та попередні завдання

Під час розробки використано OpenAI Codex для code review, підготовки тестів, пояснення помилок та документації. Авторка переносила зміни в PyCharm, запускала команди, перевіряла результати та налаштовувала хмарні сервіси.

Збережено матеріали попереднього завдання:

- [AI review](AI_REVIEW.md) — аналіз трьох views і рішення за результатами рев'ю.
- [AI prompts](AI_PROMPTS.md) — запити та контекст роботи з AI.
- `tests/test_ai_models.py` — тести моделей із позначкою `Generated with AI, reviewed and modified`.
- [Історичний звіт моделей](coverage_models.xml) — результат попереднього завдання, до подальшого розширення моделей; не є поточним coverage усього проєкту.

Для поточної версії джерелом результатів перевірок є GitHub Actions для гілки `microservices-warehouse`.

