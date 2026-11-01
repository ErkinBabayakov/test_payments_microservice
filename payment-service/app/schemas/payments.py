import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Currency(Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"

class PaymentStatus(Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class PaymentCreateSchema(BaseModel):
    amount: Decimal = Field(gt=0, decimal_places=2, max_digits=17)
    currency: Currency
    description: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

class PaymentAccepted(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: uuid.UUID
    status: PaymentStatus
    created_at: datetime

class PaymentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    currency: Currency
    description: str | None
    meta: dict[str, Any] = Field(serialization_alias="metadata")
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None

