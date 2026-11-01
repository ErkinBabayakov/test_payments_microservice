import secrets
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import SessionLocal
from app.exceptions import NotSucceededAPIKeyHTTPException
from app.services.payment import PaymentService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(
        api_key: Annotated[str | None, Depends(api_key_header)],
        settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    """Функция для проверки API-ключей"""
    if not api_key or not secrets.compare_digest(api_key, settings.API_KEY):
        raise NotSucceededAPIKeyHTTPException


async def require_idempotency_key(
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=255)
) -> str:
    return idempotency_key


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as db:
        yield db

def get_payment_service(db: Annotated[Session, Depends(get_db)]) -> PaymentService:
    return PaymentService(db)