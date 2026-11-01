import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import IdempotentException, PaymentNotFoundException
from app.models.payments import Outbox, PaymentOrm
from app.schemas.payments import PaymentAccepted, PaymentCreateSchema, PaymentDetail


class PaymentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_payment(self, payment_data: PaymentCreateSchema, idempotency_key: str):
        existing = await self.session.scalar(select(PaymentOrm).where(PaymentOrm.idempotency_key == idempotency_key))

        if existing:
            return PaymentAccepted(
                payment_id=existing.id,
                status=existing.status,
                created_at=existing.created_at,
            )

        # атомарно записываем payment + outbox в рамках одной транзакции

        try:
            payment = PaymentOrm(
                amount=payment_data.amount,
                currency=payment_data.currency.value,
                description=payment_data.description,
                meta=payment_data.metadata,
                webhook_url=str(payment_data.webhook_url),
                idempotency_key=idempotency_key,
            )
            self.session.add(payment)
            await self.session.flush()

            self.session.add(Outbox(
                event_type="payment.created",
                payload={"payment_id": str(payment.id)},
            )
        )
            await self.session.commit()

            return PaymentAccepted(
                payment_id=payment.id,
                status=payment.status,
                created_at=payment.created_at
            )
                
        except IntegrityError:
            await self.session.rollback()

            # если параллельный запрос с тем же ключом успел первым
            existing = await self.session.scalar(
                select(PaymentOrm).where(PaymentOrm.idempotency_key == idempotency_key)
            )
            if not existing:
                raise IdempotentException

            return PaymentAccepted(
                payment_id=existing.id,
                status=existing.status,
                created_at=existing.created_at
            )

    async def get_payment(self, payment_id: uuid.UUID) -> PaymentDetail:

        payment = await self.session.get(PaymentOrm, str(payment_id))

        if not payment:
            raise PaymentNotFoundException
        
        return PaymentDetail.model_validate(payment)



