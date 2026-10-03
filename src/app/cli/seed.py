"""Populate the database with demo data.

Run with:  python -m src.app.cli.seed  [--force]

Kept as a management command rather than an Alembic data migration: seeding
needs the embedding client to vectorise the knowledge base, and a migration
has no business reaching into the application's service layer.
"""

import argparse
import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from logging import getLogger

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.bootstrap.container import ApplicationContainer
from src.app.cli.seed_data import CUSTOMERS, DOCUMENTS, SERVICES, SLOT_TEMPLATE
from src.app.core.logging import setup_logging
from src.app.core.settings.app import get_app_settings
from src.app.core.settings.logging import get_logging_settings
from src.app.interfaces.llm.embedding_client import EmbeddingClient
from src.app.models.booking import Booking, BookingSlot
from src.app.models.customer import Customer
from src.app.models.knowledge import DocumentChunk, KnowledgeDocument
from src.app.models.pricing import PricingItem
from src.app.repositories.knowledge import SqlAlchemyKnowledgeRepository
from src.app.services.knowledge import KnowledgeService

logger = getLogger("seed")


async def _is_seeded(session: AsyncSession) -> bool:
    return bool(await session.scalar(select(func.count()).select_from(Customer)))


async def _clear(session: AsyncSession) -> None:
    # Order matters even with ON DELETE CASCADE: deleting children first keeps
    # the statement list readable and independent of the FK configuration.
    for model in (Booking, DocumentChunk, BookingSlot, KnowledgeDocument, Customer, PricingItem):
        await session.execute(delete(model))


def _customers() -> list[Customer]:
    now = datetime.now(UTC)
    return [
        Customer(
            name=name,
            status=status,
            last_contact_at=now - timedelta(days=days_ago) if days_ago is not None else None,
            notes=notes,
        )
        for name, status, days_ago, notes in CUSTOMERS
    ]


async def ensure_slots(session: AsyncSession, *, today: date, days: int) -> int:
    """Make sure every day from tomorrow through `today + days` has its slots.

    Idempotent and additive: rows that already exist (booked or not) are left
    alone, and only the missing ones are inserted. Running it on every start is
    what keeps the window rolling forward instead of running dry a week after
    the first seed. The unique constraint on (resource, date, time) is what
    makes "no duplicates" a database guarantee rather than a hope.
    """
    rows = [
        {
            "resource_type": resource_type,
            "slot_date": today + timedelta(days=day),
            "slot_time": time(hour, minute),
            "capacity": capacity,
            "is_available": True,
        }
        for day in range(1, days + 1)
        for resource_type, hour, minute, capacity in SLOT_TEMPLATE
    ]
    result = await session.execute(
        insert(BookingSlot)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_booking_slot_resource_datetime")
        .returning(BookingSlot.id)
    )
    return len(result.all())


async def reindex_unindexed_documents(session: AsyncSession, embedding_client: Callable[[], EmbeddingClient]) -> int:
    """Re-embed documents left without chunks (migration 0007 empties them).

    The client is only built when there is something to do, so a normal restart
    does not pay for it (a local model takes seconds to load).
    """
    repository = SqlAlchemyKnowledgeRepository(session)
    if not await repository.list_unindexed_documents():
        return 0
    return await KnowledgeService(repository, embedding_client()).reindex_unindexed_documents()


def _services() -> list[PricingItem]:
    return [
        PricingItem(service_name=name, unit_price=price, description=description)
        for name, price, description in SERVICES
    ]


async def seed(*, force: bool) -> None:
    settings = get_app_settings()
    today = datetime.now(settings.business_tz).date()
    container = ApplicationContainer()
    try:
        async with container.session_factory() as session, session.begin():
            if await _is_seeded(session):
                if not force:
                    # The rest of the demo data is a one-off, but the slot window
                    # has to keep moving: this runs on every start.
                    added = await ensure_slots(session, today=today, days=settings.slot_window_days)
                    reindexed = await reindex_unindexed_documents(session, lambda: container.embedding_client)
                    logger.info(
                        "Database already contains data; added %d missing slots, re-indexed %d documents.",
                        added,
                        reindexed,
                    )
                    return
                logger.info("Clearing existing data before reseeding.")
                await _clear(session)

            session.add_all([*_customers(), *_services()])
            await session.flush()
            slot_total = await ensure_slots(session, today=today, days=settings.slot_window_days)

            # Documents go through the service so they are chunked and embedded
            # exactly the way the API would do it.
            knowledge = KnowledgeService(SqlAlchemyKnowledgeRepository(session), container.embedding_client)
            chunk_total = 0
            for title, content in DOCUMENTS:
                document = await knowledge.add_document(title, content)
                chunk_total += document.chunk_count

            logger.info(
                "Seeded %d customers, %d slots, %d services, %d documents (%d chunks).",
                len(CUSTOMERS),
                slot_total,
                len(SERVICES),
                len(DOCUMENTS),
                chunk_total,
            )
    finally:
        await container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the database with demo data.")
    parser.add_argument("--force", action="store_true", help="Delete existing rows and reseed.")
    args = parser.parse_args()

    setup_logging(get_logging_settings())
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
