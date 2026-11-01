# Payment Service

Асинхронный микросервис обработки платежей: принимает запросы на оплату,
обрабатывает их через эмулятор внешнего шлюза и уведомляет клиента
webhook'ом. Реализованы Outbox pattern, идемпотентность, retry
с экспоненциальной задержкой и Dead Letter Queue.

---

## Содержание

- [Стек](#стек)
- [Архитектура](#архитектура)
- [Быстрый старт](#быстрый-старт)
- [API](#api)
- [Как это работает](#как-это-работает)
- [Конфигурация](#конфигурация)
- [Тесты](#тесты)
---

## Стек

- **Python 3.12**
- **FastAPI** + Pydantic v2 — HTTP API
- **SQLAlchemy 2.0** (async) + **asyncpg** — ORM
- **PostgreSQL 16** — БД
- **RabbitMQ 3.13** + **FastStream** — брокер сообщений
- **Alembic** — миграции
- **Docker** + **Docker Compose** — окружение
- **Pytest** + **pytest-asyncio** + **Testcontainers** — тесты
- **httpx** — отправка webhook и ASGI-клиент для тестов

---

**Компоненты Docker Compose:**

| Сервис | Роль |
|---|---|
| `payment-db` | PostgreSQL 16 |
| `rabbitmq` | RabbitMQ с management UI |
| `migrate` | одноразовый контейнер: `alembic upgrade head` |
| `payment-service-backend` | FastAPI API на `:8000` |
| `consumer` | publisher (outbox → RabbitMQ) + consumer (RabbitMQ → обработка) |

API **не подключается к RabbitMQ** — только пишет в Postgres. Публикацией
занимается отдельный процесс `consumer`. Это значит, что если RabbitMQ
лежит, платежи продолжают приниматься и копятся в outbox, а публикация
догоняет после восстановления.

---

## Быстрый старт

**Требования:** Docker Desktop (или Docker + Docker Compose).

```bash
# 1. Скопировать пример окружения
cp .env.example .env

# 2. Поднять всё
docker compose up --build

# 3. Дождаться, пока migrate завершится (Exited 0)
#    и api/consumer станут Up
docker compose ps
После старта:

Swagger UI: http://127.0.0.1:8000/docs

RabbitMQ management: http://127.0.0.1:15672 (guest / guest)

Проверка работоспособности:

bash
curl -X POST http://127.0.0.1:8000/api/v1/payments \
  -H "X-API-Key: dev-key-change-me" \
  -H "Idempotency-Key: order-1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Test payment",
    "metadata": {"user_id": 42},
    "webhook_url": "https://webhook.site/your-uuid"
  }'
# → 202 Accepted, {"payment_id": "...", "status": "pending", "created_at": "..."}

# Через 2–5 секунд
curl http://127.0.0.1:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: dev-key-change-me"
# → {"status": "succeeded" | "failed", "processed_at": "...", ...}
API
Все эндпоинты требуют заголовок X-API-Key. В dev-окружении —
dev-key-change-me (задаётся в .env).

POST /api/v1/payments
Создаёт платёж и событие в outbox. Ответ — 202 Accepted
с payment_id, status, created_at.

Заголовки:

Заголовок	Обязательный	Описание
X-API-Key	да	статический API-ключ
Idempotency-Key	да	уникальный ключ (1–255 символов)
Content-Type	да	application/json
Тело:

json
{
  "amount": "100.50",
  "currency": "RUB",
  "description": "Test payment",
  "metadata": {"user_id": 42},
  "webhook_url": "https://example.com/webhook"
}
Ограничения:

amount — Decimal, > 0, до 2 знаков после запятой

currency — RUB | USD | EUR

description — до 512 символов, опционально

metadata — произвольный JSON-объект

webhook_url — валидный http/https URL

Ответы:

Код	Когда
202	платёж создан (или уже существует с этим Idempotency-Key)
401	нет X-API-Key или неверный
422	невалидное тело / отсутствует Idempotency-Key / пустой Idempotency-Key
GET /api/v1/payments/{payment_id}
Возвращает детальную информацию о платеже.

json
{
  "id": "5204c10e-11c5-498c-95d2-9925fc7c344d",
  "amount": "100.50",
  "currency": "RUB",
  "description": "Test payment",
  "metadata": {"user_id": 42},
  "status": "succeeded",
  "webhook_url": "https://example.com/webhook",
  "created_at": "2026-11-01T11:29:41.611817Z",
  "processed_at": "2026-11-01T11:29:46.028943Z"
}
Код	Когда
200	платёж найден
401	нет X-API-Key или неверный
404	платёж не найден
Webhook
После обработки платежа (2–5 сек) на webhook_url отправляется POST:

json
{
  "payment_id": "5204c10e-...",
  "status": "succeeded",
  "amount": "100.50",
  "currency": "RUB",
  "processed_at": "2026-11-01T11:29:46.028943Z"
}
Доставка — at-least-once, 3 попытки с экспоненциальным backoff
(1s → 2s → 4s). Ретраи — только на 5xx и сетевые ошибки; на 4xx
доставка прекращается (клиент сам виноват).

Как это работает
Outbox pattern
Классическая проблема «dual write»: запись в БД и публикация
в RabbitMQ — две операции, которые нельзя выполнить атомарно.
Если процесс упадёт между коммитом БД и публикацией, событие
потеряется.

Решение:

В одной транзакции Postgres пишутся payment и outbox (событие).

Отдельный процесс consumer читает outbox через
SELECT ... FOR UPDATE SKIP LOCKED и публикует в RabbitMQ.

После успешной публикации в outbox.published_at проставляется
время. Publisher confirm гарантирует: если publish не удался,
published_at не проставится, событие опубликуется повторно.

SKIP LOCKED позволяет масштабировать publisher горизонтально —
каждый outbox-ряд заберёт ровно один инстанс.

Идемпотентность
Два уровня:

На API: UNIQUE на payments.idempotency_key. Повторный POST
с тем же ключом возвращает тот же payment_id, не создавая
новый платёж. Реализовано через try/except IntegrityError —
защита от гонки, когда два параллельных запроса с одним ключом
одновременно проходят SELECT и оба делают INSERT.

На consumer: перед обработкой проверяется
payment.status != "pending". Это защита от повторной доставки
RabbitMQ (at-least-once): если consumer упал между обработкой
и ack, сообщение вернётся в очередь, но второй раз платёж
не обработается.

Retry и DLQ
Инфраструктурные ошибки (БД упала, необработанное исключение)
маршрутизируются в retry-очереди с экспоненциальной задержкой:

text
attempt 1 (initial) → fail → publish в payments.retry.1s
attempt 2 → fail → publish в payments.retry.4s
attempt 3 → fail → publish в payments.dlq
Retry-очереди имеют x-message-ttl и x-dead-letter-exchange обратно
на основную очередь — сообщение «висит» нужное время и возвращается
само.

Бизнес-ошибки (шлюз вернул неуспех в 10% случаев) не
ретраятся — это финальный статус failed. Webhook отправляется
с status: failed, платёж закрыт.

Webhook-ошибки не роняют consumer. Иначе один нерабочий URL
пользователя отправлял бы уже обработанный платёж в DLQ, где он
провисел бы вечно. send_webhook_with_retries ловит свои
исключения; после 3 неудач ошибка логируется и теряется.

Конфигурация
Переменные окружения (в .env, в docker-compose.yml или в shell):

Переменная	Дефолт	Описание
API_KEY	dev-key-change-me	статический API-ключ
DB_HOST	payment-db (в compose) / localhost (локально)	хост Postgres
DB_PORT	5432	порт Postgres
DB_USER	payment	пользователь
DB_PASSWORD	payment	пароль
DB_NAME	payments	имя БД
RABBITMQ_URL	amqp://guest:guest@rabbitmq:5672/	URL брокера
PAYMENT_EXCHANGE_NAME	payments	exchange для событий
PAYMENT_QUEUE_NAME	payments.new	основная очередь
DLX_EXCHANGE	payments.dlx	dead letter exchange
DLQ_QUEUE	payments.dlq	dead letter queue
WEBHOOK_TIMEOUT_SECONDS	10.0	таймаут одного webhook-запроса
WEBHOOK_MAX_RETRIES	3	попыток доставки webhook
BASE_DELAY	1.0	базовая задержка backoff
GATEWAY_SUCCESS_RATE	0.9	доля успешных эмуляций шлюза
GATEWAY_MIN_DELAY_SECONDS	2.0	минимальная эмуляция шлюза
GATEWAY_MAX_DELAY_SECONDS	5.0	максимальная эмуляция шлюза
CONSUMER_MAX_ATTEMPTS	3	попыток до DLQ
CONSUMER_RETRY_DELAYS	[1,4,16]	задержки retry в секундах
DATABASE_URL собирается через @property из DB_* —
в конструктор Settings его передавать нельзя.

Тесты
Тесты используют Testcontainers — изолированный PostgreSQL
на каждый прогон, реальный (не мок), без загрязнения dev-БД.

Требования:

Docker Desktop запущен

Установлены pytest, pytest-asyncio, testcontainers[postgres]

bash
# Установка (если ещё не)
python -m pip install -r requirements-dev.txt

# Запуск
python -m pytest tests/ -v
Покрытые сценарии (tests/test_idempotency.py):

Тест	Что проверяет
test_same_key_returns_same_payment	базовый idempotency: тот же ключ → тот же payment_id
test_same_key_different_body_returns_original	второй body игнорируется, платёж не перезаписан
test_different_keys_create_different_payments	разные ключи → разные платежи
test_missing_idempotency_key_returns_422	обязательность заголовка
test_empty_idempotency_key_returns_422	min_length=1
test_concurrent_same_key_only_one_payment	race condition: 10 параллельных POST → одна строка в БД
test_outbox_has_single_event_per_payment	outbox не дублируется
test_wrong_api_key_returns_401	auth не сломан
Ключевой тест — test_concurrent_same_key_only_one_payment.
Он запускает 10 параллельных POST через asyncio.gather и проверяет,
что в БД ровно одна строка с этим idempotency_key. Если этот тест
зелёный — идемпотентность реальная, а не «на словах».
