"""ORM models.

Every model is re-exported here so that importing this package populates
`Base.metadata` — Alembic's env.py relies on that for autogenerate.
"""

from src.app.models.base import Base
from src.app.models.booking import Booking, BookingSlot, ResourceType
from src.app.models.customer import Customer, CustomerStatus
from src.app.models.knowledge import EMBEDDING_DIMENSIONS, DocumentChunk, KnowledgeDocument
from src.app.models.pricing import PricingItem

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "Base",
    "Booking",
    "BookingSlot",
    "Customer",
    "CustomerStatus",
    "DocumentChunk",
    "KnowledgeDocument",
    "PricingItem",
    "ResourceType",
]
