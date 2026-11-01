import asyncio
import logging
import random
from datetime import UTC, datetime

from faststream.rabbit import RabbitRouter

from app.config import settings
from app.database import SessionLocal
from app.models import PaymentOrm
from app.rabbitmq import broker, payments_exchange, payments_new_queue, retry_exchange
from app.services.webhook import send_webhook_with_retries

log = logging.getLogger(__name__)
router = RabbitRouter()

async def emulate_gateway() -> bool:
    """Функция для эмуляции обработки платежа 2-5 сек., при 90% успеха, 10% ошибки"""

    await asyncio.sleep(random.uniform(settings.GATEWAY_MIN_DELAY_SECONDS, settings.GATEWAY_MAX_DELAY_SECONDS))
    return random.random() < settings.GATEWAY_SUCCESS_RATE

@router.subscriber(payments_new_queue, exchange=payments_exchange)
async def handle_payment_created(payload: dict) -> None:
    """Фунция-обработчик сообщения о создании платежа из очереди payments.new"""
    retry_count = int(payload.get("_retry_count", 0))
    payment_id = payload["payment_id"]

    try:
        await process_payment(payment_id)
    except Exception as exc:
        log.exception("payment processing failed payment_id=%s attempt=%d", payment_id, retry_count + 1)

        await _route_failure(payload, retry_count, str(exc))

async def process_payment(payment_id: str) -> None:
    """Функция для обработки платежа"""
    async with SessionLocal() as session:
        payment = await session.get(PaymentOrm, payment_id)
        if payment is None:
            log.warning("Платеж %s не найден, пропускаю", payment_id)
            return

        # идемпотентность (если уже обработано, то не трогаем)
        if payment.status != "pending":
            log.info("Платеж %s уже %s, пропускаю", payment_id, payment.status)
            return

        # эмуляция внешнего шлюза
        success = await emulate_gateway()

        payment.status = "succeeded" if success else "failed"
        payment.processed_at = datetime.now(UTC)
        await session.commit()

    # webhook вне транзакции, с retry внутри
    await send_webhook_with_retries(
        url=payment.webhook_url,
        payload={
            "payment_id": str(payment.id),
            "status": payment.status,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "processed_at": payment.processed_at.isoformat(),
        },
    ) 

async def _route_failure(payload: dict, retry_count: int, error: str) -> None:
    """Функция для маршрутизации упавшего сообщения в retry-очередь или DLQ"""

    next_count = retry_count + 1
    enriched = {**payload, "_retry_count": next_count, "_last_error": error[:500]}

    if next_count >= settings.CONSUMER_MAX_ATTEMPTS:
        log.error("Исчерпано максимальное количество попыток, оплатить платеж не получилось. Отправляем платеж %s в DLQ, попытка=%d",
                  payload["payment_id"], next_count)

        await broker.publish(
            enriched,
            exchange=settings.DLX_EXCHANGE,
            routing_key=settings.DLQ_ROUTING_KEY
        )
        return

    delay = settings.CONSUMER_RETRY_DELAYS[next_count - 1]
    log.warning(
        "Платеж повторяется payment_id=%s attempt=%d delay=%ds",
        payload["payment_id"], next_count, delay
    )

    await broker.publish(
        enriched,
        exchange=retry_exchange,
        routing_key=f"retry.{delay}s"
    )