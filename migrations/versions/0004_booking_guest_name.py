"""book a table under a guest name, not a CRM account

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "booking_customer_id_fkey"


def upgrade() -> None:
    # Added nullable first: the column is mandatory, but existing rows have no
    # value yet, so it cannot be NOT NULL until they are backfilled from the
    # account they used to point at.
    op.add_column("booking", sa.Column("guest_name", sa.String(length=200), nullable=True))
    op.execute("UPDATE booking SET guest_name = customer.name FROM customer WHERE customer.id = booking.customer_id")
    op.alter_column("booking", "guest_name", nullable=False)
    op.create_index("ix_booking_guest_name", "booking", ["guest_name"])

    op.drop_index("ix_booking_customer_id", table_name="booking")
    op.drop_constraint(_FK, "booking", type_="foreignkey")
    op.drop_column("booking", "customer_id")


def downgrade() -> None:
    """Destructive: every booking is deleted. Take a backup first.

    The old schema requires each booking to point at a customer, and that link
    cannot be rebuilt — matching a guest name back to an account is the same
    fuzzy guess this migration exists to avoid. Leaving the rows behind with an
    empty customer_id would produce a database that does not satisfy its own
    schema, so they go.
    """
    op.execute("DELETE FROM booking")

    op.add_column("booking", sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False))
    op.create_foreign_key(_FK, "booking", "customer", ["customer_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_booking_customer_id", "booking", ["customer_id"])

    op.drop_index("ix_booking_guest_name", table_name="booking")
    op.drop_column("booking", "guest_name")
