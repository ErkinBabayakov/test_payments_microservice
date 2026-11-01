import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.dependencies import (
    get_payment_service,
    require_idempotency_key,
    verify_api_key,
)
from app.exceptions import (
    PaymentException,
    PaymentHTTPException,
    PaymentNotFoundException,
    PaymentNotFoundHTTPException,
)
from app.schemas.payments import PaymentAccepted, PaymentCreateSchema, PaymentDetail
from app.services.payment import PaymentService

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["Платежи"],
    dependencies=[Depends(verify_api_key)],
)

@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=PaymentAccepted)
async def create_payment(
    payload: PaymentCreateSchema,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    payment_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> PaymentAccepted:
    
    try:
        payment = await payment_service.create_payment(payload, idempotency_key)
        return payment
    except PaymentException:
        raise PaymentHTTPException


@router.get("/{payment_id}", response_model=PaymentDetail)
async def get_payment(
    payment_id: uuid.UUID,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)]
) -> PaymentDetail:
    try:
        return await payment_service.get_payment(payment_id)
    except PaymentNotFoundException:
        raise PaymentNotFoundHTTPException

