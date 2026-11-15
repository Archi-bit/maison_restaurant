# MAISON Restaurant

**Учебный проект ресторанного Backend API на Django REST Framework.**

MAISON Restaurant — серверная часть веб-приложения ресторана. В проекте работают каталог, гостевая корзина, авторизация сотрудников, бронирования, смены, заказы, кухонная очередь и отчёты по продажам.

> **Область проекта:** этот репозиторий содержит Backend. Клиентское приложение на React разрабатывается отдельно.

## Возможности

### Этап 1 — каталог и корзина

- Просмотр категорий и карточек блюд с изображениями.
- Поиск блюд, фильтрация по категории и признаку «рекомендуемое», пагинация.
- Просмотр подробной информации о блюде по `slug`.
- Гостевая корзина без регистрации: добавление блюд, изменение количества, удаление позиций.
- Доступ к корзине по заголовку `X-Cart-Token`; расчёт итоговой стоимости в сомах (KGS).

### Этап 2 — бронирования и сотрудники

- Учётные записи сотрудников на базе стандартного Django `User` и модели `EmployeeProfile`.
- Вход по рабочей почте и паролю, JWT access/refresh, выход и получение своего профиля.
- Восстановление пароля через стандартные механизмы Django.
- Ролевой доступ: владелец, администратор ресторана, официант, повар.
- Модели и сервисы столов, бронирований, истории и плана зала в `reservations`.

- Публичная заявка на бронирование без регистрации.
- Создание и редактирование бронирований сотрудниками; назначение стола, подтверждение, прибытие и отмена.
- Проверки времени посещения, количества гостей, вместимости и занятости стола.
- История основных изменений бронирования.
- План зала с состояниями столов на заданные дату и время.

### Этап 3 — смены и заказы

- Владелец или администратор открывает и закрывает смену, добавляет сотрудников и распределяет столы между официантами смены.
- Активные сотрудники видят текущую смену. Официант видит закреплённые за ним столы, владелец и администратор видят все назначения.
- Смены, состав и назначения доступны для просмотра в Django Admin владельцу или администратору с соответствующими разрешениями Django.
- Владелец и администратор видят выручку, средний чек, популярные блюда, продажи по каналам и сравнение периодов. Продажи можно выгрузить в CSV.
- Сотрудники создают и ведут заказы по ролям. Повар работает с кухонной очередью. После закрытия заказа назначенный официант, администратор или владелец может завершить визит.

## Технологии

| Компонент | Технология |
| --- | --- |
| Язык | Python 3.12 |
| Backend | Django 6.1.2, Django REST Framework |
| Авторизация сотрудников | SimpleJWT |
| База данных | PostgreSQL 17 |
| API-документация | drf-spectacular / OpenAPI / Swagger UI |
| Контейнеризация | Docker, Docker Compose |
| Веб-сервер | Gunicorn, Nginx |
| Проверки | Django Test Framework, GitHub Actions |
| Часовой пояс | Asia/Bishkek |

## Структура проекта

```text
maison_restaurant/
├── .github/
│   └── workflows/
│       └── backend-tests.yml
├── backend/
│   ├── apps/
│   │   ├── catalog/           # Категории и блюда
│   │   ├── cart/              # Гостевая корзина
│   │   ├── staff/             # Сотрудники, JWT и права доступа
│   │   ├── reservations/      # Столы, модели и сервисы бронирований
│   │   ├── reservation_api/   # HTTP API бронирований
│   │   ├── orders/            # Модели и сервисы заказов
│   │   ├── order_api/         # HTTP API заказов и кухни
│   │   └── operations/        # Смены, назначения и отчёты
│   ├── config/                # settings.py, urls.py, ASGI/WSGI
│   ├── nginx/                 # Конфигурация Nginx
│   ├── .env.example
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── manage.py
│   └── requirements.txt
└── docs/
    └── README.md
```

## Локальный запуск через Docker

Понадобятся Git и Docker с плагином Docker Compose. Команды ниже выполняются из корня репозитория, если не указано другое.

**1. Клонировать проект и создать файл окружения**

```bash
git clone https://github.com/Archi-bit/maison_restaurant.git
cd maison_restaurant/backend
cp .env.example .env
```

Откройте `.env` и задайте собственный `SECRET_KEY` и пароль локальной БД. Для генерации ключа:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
```

Минимальный пример локальной конфигурации:

```dotenv
SECRET_KEY=your-local-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,testserver
DB_NAME=maison_dev
DB_USER=maison_dev
DB_PASSWORD=your-local-db-password
DB_HOST=db
DB_PORT=5432
CORS_ALLOWED_ORIGINS=http://localhost:5173
MEDIA_SOURCE=./media
```

`.env` содержит секреты и **не должен попадать в Git**.

**2. Запустить PostgreSQL**

```bash
docker compose up -d db
```

**3. Применить миграции и, при необходимости, добавить демонстрационные данные**

```bash
docker compose run --rm web python manage.py migrate --noinput
# Учебные данные каталога (не запускать без проверки на production):
docker compose run --rm web python manage.py seed_catalog
```

Начальные столы можно загрузить командой `docker compose run --rm web python manage.py seed_restaurant_tables`. Для проверки назначений создайте в Django Admin активного пользователя и профиль с ролью `waiter`. Используйте идентификаторы профиля и стола из Django Admin.

**4. Запустить локальный Django-сервер**

```bash
docker compose run --rm -p 8000:8000 web python manage.py runserver 0.0.0.0:8000
```

После запуска доступны:

- Swagger UI: <http://localhost:8000/api/swagger/>
- OpenAPI: <http://localhost:8000/api/schema/>
- Django Admin: <http://localhost:8000/admin/>
- API: `http://localhost:8000/api/v1/`

**Почему не `docker compose up` для всего проекта?** Текущая конфигурация Nginx рассчитана на HTTPS с уже созданными TLS-сертификатами. Для локального знакомства с API достаточно контейнеров БД и Django, без Nginx и Certbot.

### Первоначальное создание владельца

После миграций создайте Django-суперпользователя и откройте Django Shell:

```bash
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py shell
```

В Shell укажите логин созданного пользователя, рабочую почту и имя владельца:

```python
from django.contrib.auth import get_user_model

from apps.staff.models import EmployeeProfile

user = get_user_model().objects.get(username="maison_owner")
EmployeeProfile.objects.create(
    user=user,
    work_email="owner@example.com",
    full_name="Владелец ресторана",
    role=EmployeeProfile.Role.OWNER,
)
```

Для входа в Django Admin учётная запись должна быть активной и иметь `is_staff=True`. Для управления профилями нужны соответствующие разрешения Django и роль `owner`. Активный суперпользователь уже имеет разрешения Django. Профиль создаётся отдельным шагом, и его рабочая почта используется для входа в staff API.

## REST API

Базовый путь: `/api/v1/`. Формат запросов и ответов — JSON, если не указано иное.

### Каталог и корзина

| Метод | Маршрут | Назначение |
| --- | --- | --- |
| `GET` | `/api/v1/categories/` | Категории |
| `GET` | `/api/v1/dishes/` | Блюда, поиск и фильтры |
| `GET` | `/api/v1/dishes/{slug}/` | Детали блюда |
| `POST` | `/api/v1/cart/` | Создать корзину |
| `GET` | `/api/v1/cart/` | Получить корзину |
| `POST` | `/api/v1/cart/items/` | Добавить позицию |
| `PATCH` | `/api/v1/cart/items/{id}/` | Изменить количество |
| `DELETE` | `/api/v1/cart/items/{id}/` | Удалить позицию |

Корзина не требует регистрации. После `POST /api/v1/cart/` клиент получает токен, который нужно передавать в заголовке `X-Cart-Token` в последующих запросах к корзине.

### Публичное бронирование

| Метод | Маршрут | Назначение |
| --- | --- | --- |
| `POST` | `/api/v1/reservations/` | Создать заявку на бронирование |

Пример запроса:

```bash
curl -X POST http://localhost:8000/api/v1/reservations/ \
  -H 'Content-Type: application/json' \
  -d '{
    "guest_name": "Тимур Беков",
    "phone": "+996555010027",
    "date": "2030-05-15",
    "start_time": "19:00",
    "guests_count": 2
  }'
```

Дата в примере условная: для успешного создания укажите **будущую** дату. Публичный запрос создаёт заявку со статусом `pending`; гость не может самостоятельно назначить стол или подтвердить бронь.

### Авторизация сотрудников

| Метод | Маршрут | Назначение |
| --- | --- | --- |
| `POST` | `/api/v1/staff/auth/login/` | Вход сотрудника |
| `POST` | `/api/v1/staff/auth/refresh/` | Обновление access token |
| `POST` | `/api/v1/staff/auth/logout/` | Выход и отзыв refresh token |
| `GET` | `/api/v1/staff/auth/me/` | Текущий профиль |
| `POST` | `/api/v1/staff/auth/password-reset/` | Запрос на восстановление пароля |
| `POST` | `/api/v1/staff/auth/password-reset/confirm/` | Установка нового пароля по токену |

Пример входа:

```json
{
  "work_email": "employee@example.com",
  "password": "example-password",
  "remember_me": false
}
```

Для защищённых запросов используется заголовок:

```http
Authorization: Bearer <access_token>
```

В учебном Junior MVP длительность авторизации ограничена сроками, предусмотренными в `staff`: до 3 дней без `remember_me` и до 30 дней с ним (фиксированный предел от входа, без отслеживания неактивности). Короткоживущий access token обновляется через refresh token. Точные правила и время жизни токенов определяются настройками реализованного Backend.

### Смены ресторана

Для каждого запроса нужен `Authorization: Bearer <access_token>` после входа через `POST /api/v1/staff/auth/login/`.

| Метод | Маршрут | Роли | Запрос и результат |
| --- | --- | --- | --- |
| `POST` | `/api/v1/staff/shifts/open/` | `owner`, `administrator` | Пустое тело или `{}`. Возвращает смену, `201` |
| `GET` | `/api/v1/staff/shifts/current/` | Все активные сотрудники | Объект текущей смены или `{"shift": null}`, `200` |
| `POST` | `/api/v1/staff/shifts/{id}/close/` | `owner`, `administrator` | Пустое тело или `{}`. Возвращает закрытую смену, `200` |
| `GET` | `/api/v1/staff/shifts/{id}/employees/` | `owner`, `administrator` | Состав смены, `200` |
| `POST` | `/api/v1/staff/shifts/{id}/employees/` | `owner`, `administrator` | `{"employee_id": 7}`. Возвращает запись о сотруднике смены, `201` |
| `PUT` | `/api/v1/staff/shifts/{id}/tables/{table_id}/` | `owner`, `administrator` | `{"waiter_id": 7}`. Возвращает назначение, `201` при создании и `200` при повторе или смене официанта |
| `GET` | `/api/v1/staff/shifts/current/tables/` | `owner`, `administrator`, `waiter` | Список назначений, `200`. У официанта список ограничен его столами. Без открытой смены возвращается `[]` |

Для React последовательность выглядит так. Получите access token, откройте смену, возьмите её `id` из ответа, добавьте официанта по ID профиля и назначьте ему стол. Затем обновите список через `GET /api/v1/staff/shifts/current/tables/`. Поля ответов доступны в Swagger.

```bash
API=http://localhost:8000/api/v1
curl -X POST "$API/staff/shifts/open/" -H "Authorization: Bearer $ACCESS_TOKEN"
curl -X POST "$API/staff/shifts/$SHIFT_ID/employees/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"employee_id": 7}'
curl -X PUT "$API/staff/shifts/$SHIFT_ID/tables/$TABLE_ID/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"waiter_id": 7}'
curl -X POST "$API/staff/shifts/$SHIFT_ID/close/" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Подставьте значения `ACCESS_TOKEN`, `SHIFT_ID`, `TABLE_ID` и ID профиля вместо `7`. Бизнес-ошибки возвращают `400` с полями `code` и `detail`, например `{"code": "shift_already_open", "detail": "Смена уже открыта."}`. Отсутствующая запись возвращает `404`, отсутствующий или недействительный JWT — `401`, недостаточные права — `403`.

Заказ со статусом, отличным от `closed` и `cancelled`, блокирует закрытие смены (`active_orders`). Для смены официанта проверяются заказы на этом столе в той же смене (`table_already_assigned`). В заказах сохраняется исходный официант.

Для локального сценария откройте смену, добавьте официанта и закрепите за ним стол. Создайте бронь с этим столом, подтвердите её и отметьте прибытие гостя. Проведите заказ через API до статуса `closed`, завершите визит, закройте смену и запросите отчёт за день оплаты.

### Заказы и кухня

Базовый URL для локальной разработки — `http://localhost:8000/api/v1/`. Получите `access` через `POST /api/v1/staff/auth/login/` и передавайте заголовок `Authorization: Bearer example.access.token` со своим токеном. Заголовок `X-Cart-Token` используется только в гостевой корзине.

Пути в таблице указаны относительно базового URL.

| Метод | Путь | Роли | Ответ |
| --- | --- | --- | --- |
| `GET` | `staff/orders/` | Владелец, администратор, официант (свои) | `200`, список |
| `POST` | `staff/orders/` | Владелец, администратор, официант (свой стол) | `201`, заказ в `draft` |
| `GET` | `staff/orders/{id}/` | Владелец, администратор, официант (свой) | `200`, заказ с позициями и историей |
| `POST` | `staff/orders/{id}/items/` | Владелец, администратор, официант (свой) | `201`, обновлённый заказ |
| `PATCH` | `staff/orders/{id}/items/{item_id}/` | Владелец, администратор, официант (свой) | `200`, обновлённый заказ |
| `DELETE` | `staff/orders/{id}/items/{item_id}/` | Владелец, администратор, официант (свой) | `204`, пустое тело |
| `POST` | `staff/orders/{id}/send/` | Владелец, администратор, официант (свой) | `200`, `draft` → `new` |
| `POST` | `staff/orders/{id}/preparing/` | Владелец, администратор, повар | `200`, кухонные данные, `new` → `preparing` |
| `POST` | `staff/orders/{id}/ready/` | Владелец, администратор, повар | `200`, кухонные данные, `preparing` → `ready` |
| `POST` | `staff/orders/{id}/serve/` | Владелец, администратор, официант (свой) | `200`, `ready` → `served` |
| `POST` | `staff/orders/{id}/pay/` | Владелец, администратор, официант (свой) | `200`, заказ в `served` с `is_paid: true` |
| `POST` | `staff/orders/{id}/close/` | Владелец, администратор, официант (свой) | `200`, оплаченный `served` → `closed` |
| `POST` | `staff/orders/{id}/cancel/` | Владелец, администратор | `200`, `draft` или `new` → `cancelled` |
| `GET` | `staff/waiter/orders/` | Официант | `200`, список своих заказов |
| `GET` | `staff/kitchen/orders/` | Владелец, администратор, повар | `200`, кухонная очередь |
| `POST` | `staff/reservations/{id}/complete/` | Владелец, администратор, назначенный официант | `200`, бронь в `completed` |

У всех трёх списков есть `count`, `next`, `previous` и `results`. Параметры `staff/orders/` — `status`, `channel`, `date` в формате `YYYY-MM-DD`, `table_id` и `page`. Список официанта принимает `status` и `page`. Кухня принимает `status` (`new`, `preparing`, `ready`), `station` (`hot`, `cold`) и `page`. При выборе цеха в заказах остаются позиции этого цеха. Даты и время заказов возвращаются в ISO 8601 для Asia/Bishkek.

Пример тела запроса для заказа в зале

```json
{"channel":"dine_in","reservation_id":27,"note":"Подать вместе"}
```

Бронь должна быть в `arrived`, а стол закреплён за официантом открытой смены. Для `takeaway` и `delivery` владелец или администратор передаёт `channel` и при необходимости `note`.

Пример добавления позиции в черновик

```json
{"dish_id":1,"quantity":2,"note":"Без орехов"}
```

В `PATCH` позиции можно передать `quantity`, `note` или оба поля. Количество от 1 до 99, заметка до 255 символов. Сервер сохраняет цену блюда из каталога и возвращает суммы строками, например `"1890.00"` в KGS.

Ответ `GET staff/kitchen/orders/?status=new&station=hot`

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [{
    "id": 42,
    "number": "№0042",
    "table_code": "T05",
    "channel": "dine_in",
    "status": "new",
    "created_at": "2026-11-12T19:18:00+06:00",
    "items": [{"dish_name":"Стейк","quantity":2,"station":"hot","note":"Без орехов"}]
  }]
}
```

Для ручной отметки оплаты отправьте `{"method":"cash"}` или `{"method":"card"}`. Для отмены отправьте `{"reason":"Гость отказался"}`. Остальные действия принимают `{}`.

- `400` — неверные поля или недопустимое действие. Пример бизнес-ошибки `{"code":"already_paid","detail":"Заказ уже оплачен."}`. Ошибки входных полей содержат сообщения по именам полей.
- `401` — отсутствует действительный JWT.
- `403` — сотруднику недоступно действие.
- `404` — запись отсутствует или не входит в доступную сотруднику выборку.

В React показывайте загрузку, результат и сообщение ошибки. После действия обновляйте заказ или кухонную очередь с сервера. Кухонную очередь можно обновлять кнопкой «Обновить».

### Отчёты по продажам

Отчёты доступны ролям `owner` и `administrator` с JWT. Укажите `date_from` и `date_to` в формате `YYYY-MM-DD`. Обе даты включены, период ограничен 366 днями. Если параметр пропущен, вместо него используется текущая дата в Asia/Bishkek.

| Метод | Маршрут | Результат |
| --- | --- | --- |
| `GET` | `/api/v1/staff/reports/summary/` | `revenue`, `paid_orders_count`, `average_check`, `currency` |
| `GET` | `/api/v1/staff/reports/popular-dishes/` | До 10 результатов с `dish_id`, `dish_name` и суммарным `quantity` |
| `GET` | `/api/v1/staff/reports/channels/` | По одной строке для `dine_in`, `takeaway` и `delivery` с `paid_orders_count` и `revenue` |
| `GET` | `/api/v1/staff/reports/compare/` | `current_revenue`, `previous_revenue`, `difference` и `percent_change` за два соседних периода одинаковой длины |
| `GET` | `/api/v1/staff/reports/sales.csv` | Файл UTF-8 со столбцами `order_number`, `paid_at`, `channel`, `total`, `payment_method` |

В отчёты попадают оплаченные заказы по `paid_at`, кроме отменённых. Суммы в KGS рассчитаны по ценам, сохранённым в позициях заказа, и возвращаются строками с двумя знаками после точки. `percent_change` также возвращается строкой с двумя знаками или `null`, если выручка предыдущего периода равна нулю.

```bash
curl "$API/staff/reports/summary/?date_from=2026-11-01&date_to=2026-11-07" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl "$API/staff/reports/sales.csv?date_from=2026-11-01&date_to=2026-11-07" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Accept: text/csv' -o sales.csv
```

### Управление бронированиями (для сотрудников)

| Метод | Маршрут | Назначение |
| --- | --- | --- |
| `GET` | `/api/v1/staff/reservations/` | Список с фильтрами и поиском |
| `POST` | `/api/v1/staff/reservations/` | Создание брони сотрудником |
| `GET` | `/api/v1/staff/reservations/{id}/` | Детали брони |
| `PATCH` | `/api/v1/staff/reservations/{id}/` | Редактирование разрешённых полей |
| `POST` | `/api/v1/staff/reservations/{id}/assign-table/` | Назначение или перенос стола |
| `POST` | `/api/v1/staff/reservations/{id}/confirm/` | Подтверждение |
| `POST` | `/api/v1/staff/reservations/{id}/arrive/` | Отметка прибытия |
| `POST` | `/api/v1/staff/reservations/{id}/complete/` | Завершение визита после закрытия или отмены связанного заказа |
| `POST` | `/api/v1/staff/reservations/{id}/cancel/` | Отмена |
| `GET` | `/api/v1/staff/reservations/{id}/history/` | История изменений |
| `GET` | `/api/v1/staff/tables/` | План зала на дату и время |

Для списка предусмотрены параметры `date`, `status`, `search`, `page` и `page_size`. План зала принимает `date`, `time` и `duration_minutes`.

Swagger UI показывает маршруты, подключённые в запущенной версии. При интеграции с React сверяйте форматы с её OpenAPI-схемой.

## Основные правила бронирования

- Рабочее время ресторана для бронирования: **12:00–23:00**, часовой пояс **Asia/Bishkek**.
- Количество гостей: **от 1 до 6**.
- Публичная заявка создаётся на **120 минут**; для внутренних броней длительность может задаваться отдельно по правилам API.
- Начальное состояние заявки — `pending` (ожидает обработки).
- Для подтверждения бронирования сначала требуется назначить стол.
- Статусы идут от `pending` через `confirmed` и `arrived` к `completed`. Из `pending` и `confirmed` возможна отмена (`cancelled`).
- Стол должен быть активным, вмещать гостей и не иметь пересекающейся активной брони. Отменённая бронь не занимает стол.
- Начальный план зала включает **12 столов на 40 посадочных мест**.
- План зала показывает `free`, `reserved` или `occupied` в зависимости от бронирований на выбранный интервал.
- Основные изменения фиксируются в истории бронирования.

Учебный MVP использует базовые проверки конфликтов и разумные ограничения данных. Наличие полноценной защиты от всех конкурентных запросов следует подтверждать отдельными PostgreSQL-тестами, а не предполагать по одному успешному сценарию.

## Роли и права

| Роль | Доступ |
| --- | --- |
| `owner` | Управление бронированиями, сотрудниками, сменами и заказами, доступ к кухне и отчётам |
| `administrator` | Управление бронированиями, сменами и заказами, доступ к кухне и отчётам |
| `waiter` | Свои заказы и назначенные бронирования, завершение своих визитов, свои назначения в смене и статусы столов |
| `chef` | Просмотр текущей смены и кухонной очереди, начало и завершение приготовления |
| Гость | Просмотр каталога, работа с корзиной, отправка публичной заявки |

Авторизация сотрудников не делает гостевые маршруты закрытыми. Роль проверяется на сервере; клиент не может назначить себе права через содержимое запроса.

## Проверки

Из папки `backend/`:

```bash
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm web python manage.py migrate --plan
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm web python manage.py test --noinput -v 2
docker compose run --rm web python manage.py spectacular --file /tmp/maison-schema.yaml --validate
```

В `.github/workflows/backend-tests.yml` настроены проверки Django, применение миграций, полный набор тестов и проверка схемы OpenAPI на PostgreSQL 17 при Pull Request и push в `main`.

## Развёртывание и конфигурация

Проект рассчитан на Docker Compose с PostgreSQL, Gunicorn и Nginx. Для HTTPS используется Certbot с сертификатами, которые должны быть настроены **отдельно**. Развёртывание на сервер не сводится к локальным командам из этого README.

Домен серверного окружения: <https://maison-restaurant.duckdns.org/>. Доступность новых маршрутов второго этапа зависит от того, опубликована ли соответствующая версия Backend.

Для реальной отправки писем восстановления пароля требуется настроенная почтовая доставка. **В локальном окружении используется Console Email Backend:** письмо отображается в выводе Django, но не отправляется на настоящий email.

Не коммитьте `.env`, пароли, JWT, сертификаты и другие секреты. Перед миграциями рабочей базы данных необходимы отдельная проверка и резервная копия.

## Ограничения учебного проекта

Онлайн-оплата, SMS-уведомления и публичная регистрация сотрудников за рамками учебного проекта.

Цель проекта — освоить командную Backend-разработку: модели Django, REST API, разграничение прав, PostgreSQL, тестирование, Git, интеграцию модулей и базовое развёртывание.

## Команда Backend

| Разработчик | Зона ответственности на втором этапе |
| --- | --- |
| Арген — Backend Team Lead | `staff`, авторизация, permissions, конфигурация, интеграция и проверки |
| Бексултан | `reservations`: модели, сервисы, история, план зала |
| Бекзат | `reservation_api`: serializers, views, endpoints, API-тесты |

Код первого этапа сохраняется, а функциональность второго подключается через новые Django-приложения. Изменения в `main` вносятся через Pull Request после проверки интеграции.

---

**MAISON Restaurant** — учебный командный проект. Backend: этапы 1–3, Junior MVP.
