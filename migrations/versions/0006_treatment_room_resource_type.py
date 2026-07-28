"""add treatment_room to the resource_type enum

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-28

Written by hand: `alembic revision --autogenerate` compares tables, columns and
constraints, and does not notice a new value inside an existing enum type.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS (PostgreSQL 12+) makes the statement idempotent, so a
    # database that already carries the value is left alone instead of failing.
    op.execute("ALTER TYPE resource_type ADD VALUE IF NOT EXISTS 'treatment_room'")


def downgrade() -> None:
    # PostgreSQL cannot drop a value from an enum — only recreate the type. A
    # deliberate no-op: the value is harmless while nothing uses it.
    pass
