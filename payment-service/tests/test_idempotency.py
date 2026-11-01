import asyncio

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payments import Outbox, PaymentOrm

BASE_HEADERS = {
    "X-API-Key": "lD9sq1I1A7IM9Egvu6HFj9EZPrN1V1obs_CTlSm6egc",
    "Content-Type": "application/json",
}

VALID_BODY = {
    "amount": "100.50",
    "currency": "RUB",
    "description": "first",
    "metadata": {"user_id": 42},
    "webhook_url": "https://example.com/webhook",
}


async def _create(client: AsyncClient, idem_key: str, body: dict | None = None):
    return await client.post(
        "/api/v1/payments",
        json=body or VALID_BODY,
        headers={**BASE_HEADERS, "Idempotency-Key": idem_key},
    )


#1. Один ключ, два POST -> один payment_id 

async def test_same_key_returns_same_payment(client: AsyncClient):
    r1 = await _create(client, "idem-1")
    assert r1.status_code == 202
    pid1 = r1.json()["payment_id"]

    r2 = await _create(client, "idem-1")
    assert r2.status_code == 202
    assert r2.json()["payment_id"] == pid1


#2. Один ключ, разное тело -> первый платёж не перезаписался

async def test_same_key_different_body_returns_original(client: AsyncClient, db_session: AsyncSession):
    r1 = await _create(client, "idem-2")
    assert r1.status_code == 202
    pid = r1.json()["payment_id"]

    changed = {**VALID_BODY, "amount": "999.99", "currency": "USD", "description": "second"}
    r2 = await _create(client, "idem-2", body=changed)

    assert r2.status_code == 202
    assert r2.json()["payment_id"] == pid

    row = await db_session.scalar(select(PaymentOrm).where(PaymentOrm.id == pid))
    assert str(row.amount) == "100.50"
    assert row.currency == "RUB"


#3. Разные ключи -> разные платежи 

async def test_different_keys_create_different_payments(client: AsyncClient):
    r1 = await _create(client, "key-A")
    r2 = await _create(client, "key-B")
    assert r1.json()["payment_id"] != r2.json()["payment_id"]


#4. Передача без Idempotency-Key -> 422 

async def test_missing_idempotency_key_returns_422(client: AsyncClient):
    r = await client.post("/api/v1/payments", json=VALID_BODY, headers=BASE_HEADERS)
    assert r.status_code == 422


#5. Пустой Idempotency-Key -> 422 

async def test_empty_idempotency_key_returns_422(client: AsyncClient):
    r = await client.post(
        "/api/v1/payments",
        json=VALID_BODY,
        headers={**BASE_HEADERS, "Idempotency-Key": ""},
    )
    assert r.status_code == 422


#6. Race condition: 10 параллельных POST -> одна строка 

async def test_concurrent_same_key_only_one_payment(client: AsyncClient, db_session: AsyncSession):
    body = {**VALID_BODY, "amount": "1.00", "description": "race"}
    headers = {**BASE_HEADERS, "Idempotency-Key": "race-key"}

    responses = await asyncio.gather(
        *[client.post("/api/v1/payments", json=body, headers=headers) for _ in range(10)],
        return_exceptions=True,
    )

    ids = set()
    for r in responses:
        if isinstance(r, Exception):
            continue
        assert r.status_code in (202, 409)
        if r.status_code == 202:
            ids.add(r.json()["payment_id"])

    assert len(ids) == 1

    count = await db_session.scalar(
        select(func.count()).select_from(PaymentOrm).where(
            PaymentOrm.idempotency_key == "race-key"
        )
    )
    assert count == 1


# 7. Проверка Outbox не дубликат

async def test_outbox_has_single_event_per_payment(client: AsyncClient, db_session: AsyncSession):
    r = await _create(client, "idem-outbox")
    assert r.status_code == 202
    pid = r.json()["payment_id"]

    await _create(client, "idem-outbox")

    rows = (await db_session.scalars(select(Outbox))).all()

    count = sum(1 for r in rows if r.payload.get("payment_id") == pid)
    assert count == 1


#8. Неверный API_KEY -> 401 

async def test_wrong_api_key_returns_401(client: AsyncClient):
    r = await client.post(
        "/api/v1/payments",
        json=VALID_BODY,
        headers={"X-API-Key": "wrong-key", "Idempotency-Key": "idem-auth"},
    )
    assert r.status_code == 401