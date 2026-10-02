"""resize embedding vectors to 1024 (bge-m3)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-02

Vectors of one width cannot be cast to another, and vectors from two models are
not comparable anyway, so every stored embedding is dropped. Re-index afterwards:
    python -m src.app.cli.seed --force
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_document_chunk_embedding_hnsw"


def _resize(width: int) -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute("DELETE FROM document_chunk")
    op.execute("UPDATE knowledge_document SET embedding = NULL")
    op.execute(f"ALTER TABLE document_chunk ALTER COLUMN embedding TYPE vector({width})")
    op.execute(f"ALTER TABLE knowledge_document ALTER COLUMN embedding TYPE vector({width})")
    op.execute(f"CREATE INDEX {_INDEX} ON document_chunk USING hnsw (embedding vector_cosine_ops)")


def upgrade() -> None:
    _resize(1024)


def downgrade() -> None:
    _resize(1536)
