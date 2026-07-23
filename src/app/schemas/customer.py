from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.app.contracts.customer import CustomerDTO
from src.app.contracts.enums import CustomerStatus


class CustomerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    status: CustomerStatus = CustomerStatus.LEAD
    notes: str | None = Field(default=None, max_length=2_000)


    @field_validator("name")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        # min_length alone accepts "   ", which is not a name.
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class CustomerResponse(BaseModel):
    id: UUID
    name: str
    status: CustomerStatus
    last_contact_at: datetime | None
    notes: str | None

    @classmethod
    def from_contract(cls, customer: CustomerDTO) -> "CustomerResponse":
        # Contract -> schema conversion lives on the schema, so routers stay
        # thin and no contract ever leaks out as a response by accident.
        return cls(
            id=customer.id,
            name=customer.name,
            status=customer.status,
            last_contact_at=customer.last_contact_at,
            notes=customer.notes,
        )
