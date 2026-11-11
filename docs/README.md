# MAISON Restaurant — Backend, этап 1

REST API каталога и гостевой корзины. Django 6.1.2, Django REST Framework, PostgreSQL 17, Docker Compose, Gunicorn, Nginx.

> В этом репозитории находится Backend. Клиентский React-проект разрабатывается отдельно. Второй этап ещё не начат. Это описание не заменяет оригинальные технические задания.

## Структура

- `backend/apps/catalog/` — категории, блюда, поиск, фильтрация, сортировка и seed-данные.
- `backend/apps/cart/` — гостевая корзина, токены, позиции и итоговая стоимость.
- `backend/config/` — Django settings, URLConf и Swagger/OpenAPI.
- `backend/docker-compose.yml` — локальная инфраструктура (HTTPS Nginx рассчитан на существующие сертификаты).
- `.github/workflows/backend-tests.yml` — проверки Pull Requests.

## Локальный запуск на Ubuntu через Docker

Из корня репозитория:

```bash
cd backend
cp .env.example .env
```

Для `.env` требуется задать локальный `SECRET_KEY`. Его можно сгенерировать командой:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
```

Вставить полученную строку после `SECRET_KEY=` в `.env`. Не использовать production-секрет, не коммитить `.env`.

Запустить только БД, чтобы локально не требовались TLS-сертификаты:

```bash
docker compose config --quiet
docker compose up -d db
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm web python manage.py test --noinput -v 2
```

Образ `web` собирается из `backend/Dockerfile`. Внутри Docker переменная `DB_HOST` устанавливается в `db`. `docker compose run` запускает одноразовый контейнер для проверки; Nginx не запускается.

Для Swagger нужно запустить локальный Django-сервер отдельно либо создать сертификаты/локальный reverse proxy. Проще через Docker:

```bash
docker compose run --rm -p 8000:8000 web python manage.py runserver 0.0.0.0:8000
```

Открыть `http://localhost:8000/api/swagger/`. Использовать только локально. Внимание: при `SESSION_COOKIE_SECURE = True` вход в Admin по обычному HTTP может зависеть от поведения браузера. Для локального HTTP можно временно установить в локальных настройках `SESSION_COOKIE_SECURE = not DEBUG` и `CSRF_COOKIE_SECURE = not DEBUG`, не ослабляя production.

## Проверки без Docker

Требуются Python с установленным `backend/requirements.txt` и отдельная PostgreSQL с реквизитами из `.env`, доступная из Ubuntu по указанному `DB_HOST`.

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test --noinput -v 2
python manage.py spectacular --file schema.yaml --validate
```

`manage.py test` создаёт отдельную временную тестовую БД, выполняет тесты и удаляет её. Тестов не следует запускать с production-учётной записью PostgreSQL.

## REST API

| Метод | URL | Назначение |
| --- | --- | --- |
| GET | `/api/v1/categories/` | Активные категории |
| GET | `/api/v1/dishes/` | Блюда: `search`, `category`, `featured`, `page` |
| GET | `/api/v1/dishes/{slug}/` | Детали блюда |
| POST | `/api/v1/cart/` | Создание гостевой корзины |
| GET | `/api/v1/cart/` | Получение корзины по `X-Cart-Token` |
| POST | `/api/v1/cart/items/` | Добавление блюда |
| PATCH | `/api/v1/cart/items/{id}/` | Изменение количества |
| DELETE | `/api/v1/cart/items/{id}/` | Удаление позиции |

Создать корзину можно без токена; остальные запросы корзины требуют секретный заголовок `X-Cart-Token`. Токен выдаётся один раз при создании корзины. Деньги возвращаются строками с двумя десятичными знаками в KGS; сервер считает суммы по актуальным ценам из БД.

Swagger: `/api/swagger/`; OpenAPI JSON: `/api/schema/`.

## Демонстрационные блюда

`python manage.py seed_catalog` заполняет **учебную** БД восемью блюдами и локальными изображениями-заглушками. Цены и фото в этой команде **не подтверждены макетом Figma**. Команда повторяемая: не заменяет существующие цены и загруженные изображения блюд.

**Не запускать `seed_catalog` на production без анализа состояния данных.** До формальной сдачи сверить цены, описания, фотографии и рекомендации с исходным дизайном. Чек-лист: `docs/catalog_fixtures.md`.

## Развёртывание

Рабочий AWS EC2 настроен отдельно от репозитория, согласно владельцу проекта. Этот набор исправлений не заменяет серверные `.env`, Dockerfile, Compose-конфигурации, Certbot или Nginx. Сначала проверить PR и локальную среду; отдельно согласовать production-развёртывание и план отката.

## Ответственные

- Бексултан: модели Category/Dish, миграции, Admin и seed.
- Бекзат: каталог API, поиск, фильтрация, Swagger.
- Арген (Backend Lead): корзина, интеграция, Code Review и объединение изменений.

Изменения в `main` — через PR, в PR указывать реально выполненные проверки и известные ограничения.
