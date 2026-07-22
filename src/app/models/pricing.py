import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.models.base import Base


class PricingItem(Base):
    __tablename__ = "pricing_item"
    __table_args__ = (CheckConstraint("unit_price >= 0", name="ck_pricing_item_price_non_negative"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    # Numeric, never float: money must not accumulate binary rounding error.
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    description: Mapped[str | None] = mapped_column(Text, default=None)
