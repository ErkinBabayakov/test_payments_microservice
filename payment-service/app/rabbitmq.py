from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.config import settings

broker = RabbitBroker(settings.RABBITMQ_URL)

# exchange для основных сообщений
payments_exchange = RabbitExchange(settings.PAYMENT_EXCHANGE_NAME, type=ExchangeType.DIRECT, durable=True)

retry_exchange = RabbitExchange("payments.retry", type=ExchangeType.DIRECT, durable=True)
# DLX/DLQ
dlx_exchange = RabbitExchange(settings.DLX_EXCHANGE, type=ExchangeType.DIRECT, durable=True)

payments_new_queue = RabbitQueue(
    settings.PAYMENT_QUEUE_NAME, 
    durable=True,
    routing_key=settings.PAYMENT_SUCCEEDED_ROUTING_KEY,
    arguments={
        "x-dead-letter-exchange": "payments.dlx",
        "x-dead-letter-routing-key": "payment.failed",
    }
)

payments_dlq = RabbitQueue(
    settings.DLQ_QUEUE,
    durable=True, 
    routing_key=settings.DLQ_ROUTING_KEY
)