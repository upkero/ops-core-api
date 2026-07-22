"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1536

customer_status = postgresql.ENUM("active", "lead", "churned", name="customer_status", create_type=False)
resource_type = postgresql.ENUM("table", "meeting_room", name="resource_type", create_type=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    customer_status.create(op.get_bind(), checkfirst=True)
    resource_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "customer",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", customer_status, nullable=False),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customer_name", "customer", ["name"])

    op.create_table(
        "booking_slot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_type", resource_type, nullable=False),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column("slot_time", sa.Time(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("resource_type", "slot_date", "slot_time", name="uq_booking_slot_resource_datetime"),
        sa.CheckConstraint("capacity > 0", name="ck_booking_slot_capacity_positive"),
    )
    op.create_index("ix_booking_slot_lookup", "booking_slot", ["slot_date", "resource_type", "is_available"])

    op.create_table(
        "booking",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slot_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["slot_id"], ["booking_slot.id"], ondelete="CASCADE"),
        sa.CheckConstraint("party_size > 0", name="ck_booking_party_size_positive"),
    )
    op.create_index("ix_booking_customer_id", "booking", ["customer_id"])

    op.create_table(
        "pricing_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("service_name", sa.String(length=200), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint("unit_price >= 0", name="ck_pricing_item_price_non_negative"),
    )
    # unique + index on the same column yields one unique index, not a separate
    # constraint — mirrors what the ORM model declares.
    op.create_index("ix_pricing_item_service_name", "pricing_item", ["service_name"], unique=True)

    op.create_table(
        "knowledge_document",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_document_title", "knowledge_document", ["title"])

    op.create_table(
        "document_chunk",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_document.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_position"),
    )
    op.create_index("ix_document_chunk_document_id", "document_chunk", ["document_id"])
    # Opclass must match the query operator (<=>), or the index is never used.
    op.create_index(
        "ix_document_chunk_embedding_hnsw",
        "document_chunk",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("document_chunk")
    op.drop_table("knowledge_document")
    op.drop_table("pricing_item")
    op.drop_table("booking")
    op.drop_table("booking_slot")
    op.drop_table("customer")
    resource_type.drop(op.get_bind(), checkfirst=True)
    customer_status.drop(op.get_bind(), checkfirst=True)
