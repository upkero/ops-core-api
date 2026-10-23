"""several resources of one type at the same time

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23

A restaurant has more than one table for four. Until now a slot was unique per
(resource type, date, time), so the diary could hold one table per time. `unit`
says which of the identical resources a slot belongs to (table 1, table 2, ...).
Existing rows become unit 1, which is what they were.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("booking_slot", sa.Column("unit", sa.SmallInteger(), nullable=False, server_default="1"))
    op.drop_constraint("uq_booking_slot_resource_datetime", "booking_slot", type_="unique")
    op.create_unique_constraint(
        "uq_booking_slot_resource_unit_datetime", "booking_slot", ["resource_type", "unit", "slot_date", "slot_time"]
    )


def downgrade() -> None:
    # Fails if two units share a time, which is the honest outcome: the old
    # schema cannot represent that diary.
    op.drop_constraint("uq_booking_slot_resource_unit_datetime", "booking_slot", type_="unique")
    op.create_unique_constraint(
        "uq_booking_slot_resource_datetime", "booking_slot", ["resource_type", "slot_date", "slot_time"]
    )
    op.drop_column("booking_slot", "unit")
