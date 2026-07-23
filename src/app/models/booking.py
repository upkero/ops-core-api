import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.contracts.enums import ResourceType
from src.app.models.base import Base, pg_enum


class BookingSlot(Base):
    __tablename__ = "booking_slot"
    __table_args__ = (
        UniqueConstraint("resource_type", "slot_date", "slot_time", name="uq_booking_slot_resource_datetime"),
        Index("ix_booking_slot_lookup", "slot_date", "resource_type", "is_available"),
        CheckConstraint("capacity > 0", name="ck_booking_slot_capacity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[ResourceType] = mapped_column(pg_enum(ResourceType, "resource_type"))
    slot_date: Mapped[date] = mapped_column(Date)
    slot_time: Mapped[time] = mapped_column(Time)
    capacity: Mapped[int] = mapped_column(Integer)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)


class Booking(Base):
    __tablename__ = "booking"
    __table_args__ = (CheckConstraint("party_size > 0", name="ck_booking_party_size_positive"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # A booking is a table under a name, nothing more. There is deliberately no
    # link to the CRM Customer: that entity models an account with a lifecycle
    # (lead, active, churned) for the sales and MCP flows, and a phone
    # reservation has no account behind it. Keeping the name here also records
    # what was actually said at the time, rather than whatever the account is
    # renamed to later.
    guest_name: Mapped[str] = mapped_column(String(200), index=True)
    # Unique: the "one booking per slot" rule is enforced by the service *and*
    # by the database, so a race the application logic misses still cannot
    # produce a double booking.
    slot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("booking_slot.id", ondelete="CASCADE"), unique=True)
    party_size: Mapped[int] = mapped_column(Integer)
    # Client-supplied retry token. Unique, so a repeated request cannot create a
    # second booking even if two retries arrive at the same instant — the
    # database refuses the duplicate rather than the application hoping to
    # notice it first.
    # unique + index together produce a single unique index, which is what the
    # replay lookup reads and what stops two simultaneous retries inserting.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
