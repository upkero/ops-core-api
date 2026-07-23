"""add an idempotency key to bookings

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("booking", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    # Unique, but nullable: bookings made without a key are unaffected, while
    # two concurrent retries carrying the same key cannot both insert.
    op.create_index("ix_booking_idempotency_key", "booking", ["idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_booking_idempotency_key", table_name="booking")
    op.drop_column("booking", "idempotency_key")
