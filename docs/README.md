# MAISON Restaurant

**Учебный проект ресторанного Backend API на Django REST Framework.**

MAISON Restaurant — серверная часть веб-приложения ресторана. В проекте работают каталог, гостевая корзина, авторизация сотрудников и API смен. Модели и сервисы бронирования доступны внутри Django. Для HTTP API бронирований требуется интеграция `reservation_api`.

> **Область проекта:** этот репозиторий содержит Backend. Клиентское приложение на React разрабатывается отдельно.

## Возможности

### Этап 1 — каталог и корзина

- Просмотр категорий и карточек блюд с изображениями.
- Поиск блюд, фильтрация по категории и признаку «рекомендуемое», пагинация.
- Просмотр подробной информации о блюде по `slug`.
- Гостевая корзина без регистрации: добавление блюд, изменение количества, удаление позиций.
- Доступ к корзине по заголовку `X-Cart-Token`; расчёт итоговой стоимости в сомах (KGS).

### Этап 2 — бронирования и сотрудники

**Доступно в этой ветке**

- Учётные записи сотрудников на базе стандартного Django `User` и модели `EmployeeProfile`.
- Вход по рабочей почте и паролю, JWT access/refresh, выход и получение своего профиля.
- Восстановление пароля через стандартные механизмы Django.
- Ролевой доступ: владелец, администратор ресторана, официант, повар.
- Модели и сервисы столов, бронирований, истории и плана зала в `reservations`.

**После подключения `reservation_api`**

- Публичная заявка на бронирование без регистрации.
- Создание и редактирование бронирований сотрудниками; назначение стола, подтверждение, прибытие и отмена.
- Проверки времени посещения, количества гостей, вместимости и занятости стола.
- История основных изменений бронирования.
- План зала с состояниями столов на заданные дату и время.

### Этап 3 — операции смены

- Владелец или администратор открывает смену, добавляет сотрудников и закрепляет столы за официантами смены.
- Активные сотрудники видят текущую смену. Официант видит закреплённые за ним столы, владелец и администратор видят все назначения.
- Смены, состав и назначения доступны для просмотра в Django Admin владельцу или администратору с соответствующими разрешениями Django.

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
│   │   └── operations/        # Смены, состав и назначения
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

По плану интеграции `reservations` отвечает за данные и правила бронирования, а `reservation_api` — за HTTP-запросы и ответы.

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

Маршрут ниже описывает контракт второго этапа и станет доступен после интеграции `reservation_api`.

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
| `GET` | `/api/v1/staff/shifts/{id}/employees/` | `owner`, `administrator` | Состав смены, `200` |
| `POST` | `/api/v1/staff/shifts/{id}/employees/` | `owner`, `administrator` | `{"employee_id": 7}`. Возвращает запись о сотруднике смены, `201` |
| `PUT` | `/api/v1/staff/shifts/{id}/tables/{table_id}/` | `owner`, `administrator` | `{"waiter_id": 7}`. Возвращает назначение, `201` при создании и `200` при повторе с тем же официантом |
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
```

Подставьте значения `ACCESS_TOKEN`, `SHIFT_ID`, `TABLE_ID` и ID профиля вместо `7`. Бизнес-ошибки возвращают `400` с полями `code` и `detail`, например `{"code": "shift_already_open", "detail": "Смена уже открыта."}`. Отсутствующая запись возвращает `404`, отсутствующий или недействительный JWT — `401`, недостаточные права — `403`.

Закрытие смены, переназначение стола и отчёты о продажах ожидают `orders`. Создание заказа, кухня и оплата через HTTP зависят от `order_api`. После интеграции сквозная проверка должна пройти от открытия смены и назначения стола до заказа, кухни, оплаты, закрытия и отражения оплаты в отчёте.

### Управление бронированиями (для сотрудников)

Эти маршруты также относятся к контракту будущей интеграции.

| Метод | Маршрут | Назначение |
| --- | --- | --- |
| `GET` | `/api/v1/staff/reservations/` | Список с фильтрами и поиском |
| `POST` | `/api/v1/staff/reservations/` | Создание брони сотрудником |
| `GET` | `/api/v1/staff/reservations/{id}/` | Детали брони |
| `PATCH` | `/api/v1/staff/reservations/{id}/` | Редактирование разрешённых полей |
| `POST` | `/api/v1/staff/reservations/{id}/assign-table/` | Назначение или перенос стола |
| `POST` | `/api/v1/staff/reservations/{id}/confirm/` | Подтверждение |
| `POST` | `/api/v1/staff/reservations/{id}/arrive/` | Отметка прибытия |
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
- Статусы: `pending` → `confirmed` → `arrived`; из `pending` или `confirmed` возможна отмена (`cancelled`).
- Стол должен быть активным, вмещать гостей и не иметь пересекающейся активной брони. Отменённая бронь не занимает стол.
- Начальный план зала включает **12 столов на 40 посадочных мест**.
- План зала показывает `free`, `reserved` или `occupied` в зависимости от бронирований на выбранный интервал.
- Основные изменения фиксируются в истории бронирования.

Учебный MVP использует базовые проверки конфликтов и разумные ограничения данных. Наличие полноценной защиты от всех конкурентных запросов следует подтверждать отдельными PostgreSQL-тестами, а не предполагать по одному успешному сценарию.

## Роли и права

| Роль | Доступ |
| --- | --- |
| `owner` | Управление бронированиями и сотрудниками в пределах разрешённых интерфейсов |
| `administrator` | Управление бронированиями и назначением столов через предусмотренный API |
| `waiter` | Просмотр назначенных ему бронирований и статусов всех столов, без данных чужих гостей |
| `chef` | Нет доступа к разделу бронирований на втором этапе |
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
