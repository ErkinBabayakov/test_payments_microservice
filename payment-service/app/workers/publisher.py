import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Outbox
from app.rabbitmq import broker, payments_exchange

log = logging.getLogger(__name__)

POOL_INTERVAL = 1.0
BATCH_SIZE = 50

async def publish_outbox() -> None:
    """Scheduler для Outbox"""
    while True:
        try:
            await _publish_batch()
        except Exception:
            log.exception("outbox publisher failed, retrying in %.1fs", POOL_INTERVAL)
        await asyncio.sleep(POOL_INTERVAL)

        

async def _publish_batch() -> None:
    """Функция для чтения Outbox и отправки сообщений в очередь (батчами)"""
    async with SessionLocal() as session, session.begin():
        rows = (
            await session.execute(
                select(Outbox)
                .where(Outbox.published_at.is_(None))
                .order_by(Outbox.created_at)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()

        if not rows:
            return

        for row in rows:
            await broker.publish(
                row.payload,
                exchange=payments_exchange, 
                queue=settings.PAYMENT_QUEUE_NAME,
                routing_key="payment.created",
                message_id=str(row.id),   
                persist=True,
            )
            
            row.published_at = datetime.now(UTC)
                