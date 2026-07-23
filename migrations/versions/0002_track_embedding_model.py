"""track which model produced each embedding

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rows written before this migration carry no provenance. Marking them
# "legacy" rather than guessing means the search guard rejects them loudly and
# asks for a re-index, instead of comparing them against vectors from another
# model and returning confident nonsense.
_UNKNOWN_PROVENANCE = "legacy"


def upgrade() -> None:
    op.add_column(
        "document_chunk",
        sa.Column("embedding_model", sa.String(length=100), nullable=False, server_default=_UNKNOWN_PROVENANCE),
    )
    op.create_index("ix_document_chunk_embedding_model", "document_chunk", ["embedding_model"])
    # The default existed only to backfill; new rows must state their model.
    op.alter_column("document_chunk", "embedding_model", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_document_chunk_embedding_model", table_name="document_chunk")
    op.drop_column("document_chunk", "embedding_model")
