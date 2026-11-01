# Payment Service

Асинхронный микросервис обработки платежей: принимает запросы на оплату,
обрабатывает их через эмулятор внешнего шлюза и уведомляет клиента
webhook'ом. Реализованы Outbox pattern, идемпотентность, retry
с экспоненциальной задержкой и Dead Letter Queue.

---

## Содержание

- [Стек](#стек)
- [Быстрый старт](#быстрый-старт)
- [API](#api)
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
```
После старта:

Swagger UI: http://127.0.0.1:8000/docs  

Redoc: http://127.0.0.1:8000/redoc

RabbitMQ management: http://127.0.0.1:15672 (payment / payment)

Проверка работоспособности:

*bash*

```
curl -X POST http://127.0.0.1:8000/api/v1/payments \
  -H "X-API-Key: lD9sq1I1A7IM9Egvu6HFj9EZPrN1V1obs_CTlSm6egc" \
  -H "Idempotency-Key: order-1" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Test payment",
    "metadata": {"user_id": 42},
    "webhook_url": "https://webhook.site/your-uuid"
  }'
```
 Примерный ответ → 202 Accepted, {"payment_id": "...", "status": "pending", "created_at": "..."}

Через 2–5 секунд
```
curl http://127.0.0.1:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: lD9sq1I1A7IM9Egvu6HFj9EZPrN1V1obs_CTlSm6egc"
```
Ответ → {"status": "succeeded" | "failed", "processed_at": "...", ...}

## API
Все эндпоинты требуют заголовок X-API-Key. В dev-окружении —
задаётся в .env (API_KEY). Специально ***не добавил .env в .gitignore*** 
(для просмотра настроек конфигурации).
`Перед использованием эндпоинтов, нажимаем кнопку авторизации 
в документации и добавляем API-KEY.`

## POST /api/v1/payments
Создаёт платёж и событие в outbox. Ответ — 202 Accepted
с payment_id, status, created_at.

## Заголовки:

Заголовок	Обязательный	Описание
X-API-Key	да	статический API-ключ
Idempotency-Key	да	уникальный ключ (1–255 символов)
Content-Type	да	application/json
Тело:

*json*
```{
  "amount": "100.50",
  "currency": "RUB",
  "description": "Test payment",
  "metadata": {"user_id": 42},
  "webhook_url": "https://example.com/webhook"
}
```
Ограничения:

amount — Decimal, > 0, до 2 знаков после запятой

currency — RUB | USD | EUR

description — до 512 символов, опционально

metadata — произвольный JSON-объект

webhook_url — валидный http/https URL

## Идемпотентность
Два уровня:

**На API:** UNIQUE на payments.idempotency_key. Повторный POST
с тем же ключом возвращает тот же payment_id, не создавая
новый платёж. Реализовано через try/except IntegrityError —
защита от гонки, когда два параллельных запроса с одним ключом
одновременно проходят SELECT и оба делают INSERT.

**На consumer:** перед обработкой проверяется
payment.status != "pending". Это защита от повторной доставки
RabbitMQ (at-least-once): если consumer упал между обработкой
и ack, сообщение вернётся в очередь, но второй раз платёж
не обработается.

## Retry и DLQ
Инфраструктурные ошибки (БД упала, необработанное исключение)
маршрутизируются в retry-очереди с экспоненциальной задержкой:

```
attempt 1 (initial) → fail → publish в payments.retry.1s
attempt 2 → fail → publish в payments.retry.4s
attempt 3 → fail → publish в payments.dlq
```
Retry-очереди имеют x-message-ttl и x-dead-letter-exchange обратно
на основную очередь — сообщение «висит» нужное время и возвращается
само.

Бизнес-ошибки (шлюз вернул неуспех в 10% случаев) ***не
ретраятся*** — это финальный статус failed. Webhook отправляется
с status: failed, платёж закрыт.

Webhook-ошибки не роняют consumer. Иначе один нерабочий URL
пользователя отправлял бы уже обработанный платёж в DLQ, где он
провисел бы вечно. send_webhook_with_retries ловит свои
исключения; после 3 неудач ошибка логируется и теряется.

## Тесты
Тесты используют Testcontainers — изолированный PostgreSQL
на каждый прогон, без загрязнения dev-БД.

## Требования:

Docker Desktop запущен

Установлены pytest, pytest-asyncio, testcontainers[postgres]

# Запуск
```python -m pytest tests/ -v  ```  

Покрытые сценарии (tests/test_idempotency.py):
| Тест |	Что проверяет |
|---|---|
| `test_same_key_returns_same_payment`	| базовый idempotency: тот же ключ → тот же payment_id |
| `test_same_key_different_body_returns_original` |	второй body игнорируется, платёж не перезаписан |
| `test_different_keys_create_different_payments`	| разные ключи → разные платежи |
| `test_missing_idempotency_key_returns_422`	| обязательность заголовка |
| `test_empty_idempotency_key_returns_422`	| min_length=1 |
| `test_concurrent_same_key_only_one_payment`	| race condition: 10 параллельных POST → одна строка в БД |
| `test_outbox_has_single_event_per_payment` | outbox не дублируется|
| `test_wrong_api_key_returns_401`	| auth не сломан |

Ключевой тест — test_concurrent_same_key_only_one_payment.
Он запускает 10 параллельных POST через asyncio.gather и проверяет,
что в БД ровно одна строка с этим idempotency_key. Если этот тест
зелёный — идемпотентность прошла.
