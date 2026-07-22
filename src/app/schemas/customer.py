from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.app.contracts.customer import CustomerDTO
from src.app.contracts.enums import CustomerStatus


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
