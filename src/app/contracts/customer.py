from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.app.contracts.enums import CustomerStatus


@dataclass(frozen=True, slots=True)
class CustomerDTO:
    id: UUID
    name: str
    status: CustomerStatus
    last_contact_at: datetime | None
    notes: str | None
