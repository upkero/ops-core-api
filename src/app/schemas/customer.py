from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from src.app.contracts.enums import CustomerStatus
from src.app.schemas.base import NonBlankName, ResponseModel


class CustomerCreateRequest(BaseModel):
    name: NonBlankName
    status: CustomerStatus = CustomerStatus.LEAD
    notes: str | None = Field(default=None, max_length=2_000)


class CustomerResponse(ResponseModel):
    id: UUID
    name: str
    status: CustomerStatus
    last_contact_at: datetime | None
    notes: str | None
