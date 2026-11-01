import asyncio
import logging

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from app.config import settings
from app.rabbitmq import broker
from app.workers.consumer import router
from app.workers.publisher import publish_outbox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

async def connect_rabbitmq(url: str) -> AbstractRobustConnection:
    return await aio_pika.connect_robust(url)

async def declare_payment_exchange(channel: AbstractChannel, exchange_name: str, durable: bool = True):
    return await channel.declare_exchange(exchange_name, durable=durable)


async def declare_retry() -> None:
    """Retry-очереди с TTL и DLX обратно на основную очередь."""

    conn = await connect_rabbitmq(settings.RABBITMQ_URL)

    try:
        channel = await conn.channel()
        await declare_payment_exchange(channel, settings.PAYMENT_EXCHANGE_NAME, durable=True)
        ex_retry = await declare_payment_exchange(channel, "payments.retry", durable=True)
        await declare_payment_exchange(channel, settings.DLX_EXCHANGE, durable=True)

        for delay in settings.CONSUMER_RETRY_DELAYS:
            q = await channel.declare_queue(
                f"payments.retry.{delay}s",
                durable=True,
                arguments={
                    "x-message-ttl": delay * 1000,
                    "x-dead-letter-exchange": "payments",
                    "x-dead-letter-routing-key": "payment.created",
                }
            )
            await q.bind(ex_retry, routing_key=f"retry.{delay}s")
    finally:
        await conn.close()

async def main() -> None:
    await declare_retry()

    broker.include_router(router)
    await broker.start()
    logger.info("broker started, consumer is running")

    try:
        await publish_outbox()
    finally:
        await broker.stop()


if __name__ == "__main__":
    asyncio.run(main())


