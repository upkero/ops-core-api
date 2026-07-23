"""allow a booking to be cancelled

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

booking_status = postgresql.ENUM("active", "cancelled", name="booking_status", create_type=False)


def upgrade() -> None:
    booking_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "booking",
        sa.Column("status", booking_status, nullable=False, server_default="active"),
    )
    op.alter_column("booking", "status", server_default=None)
    op.add_column("booking", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))

    # A plain UNIQUE(slot_id) would leave a cancelled slot permanently
    # unbookable. Only the active booking has to be unique, which is a partial
    # index — so the double-booking guarantee survives cancellation.
    op.drop_constraint("booking_slot_id_key", "booking", type_="unique")
    op.create_index("ix_booking_slot_id", "booking", ["slot_id"])
    op.create_index(
        "uq_booking_active_slot",
        "booking",
        ["slot_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    # The old schema allows one booking per slot ever, so cancelled rows cannot
    # be represented and any slot booked more than once would collide.
    op.execute("DELETE FROM booking WHERE status = 'cancelled'")

    op.drop_index("uq_booking_active_slot", table_name="booking")
    op.drop_index("ix_booking_slot_id", table_name="booking")
    op.create_unique_constraint("booking_slot_id_key", "booking", ["slot_id"])

    op.drop_column("booking", "cancelled_at")
    op.drop_column("booking", "status")
    booking_status.drop(op.get_bind(), checkfirst=True)
