"""Populate the database with demo data.

Run with:  python -m src.app.cli.seed  [--force]

Kept as a management command rather than an Alembic data migration: seeding
needs the embedding client to vectorise the knowledge base, and a migration
has no business reaching into the application's service layer.
"""

import argparse
import asyncio
from datetime import UTC, datetime, time, timedelta
from logging import getLogger

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.bootstrap.container import ApplicationContainer
from src.app.cli.seed_data import CUSTOMERS, DOCUMENTS, SERVICES, SLOT_DAYS, SLOT_START_OFFSET, SLOT_TEMPLATE
from src.app.core.logging import setup_logging
from src.app.core.settings.logging import get_logging_settings
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


def _slots() -> list[BookingSlot]:
    first_day = (datetime.now(UTC) + SLOT_START_OFFSET).date()
    return [
        BookingSlot(
            resource_type=resource_type,
            slot_date=first_day + timedelta(days=day),
            slot_time=time(hour, minute),
            capacity=capacity,
            is_available=True,
        )
        for day in range(SLOT_DAYS)
        for resource_type, hour, minute, capacity in SLOT_TEMPLATE
    ]


def _services() -> list[PricingItem]:
    return [
        PricingItem(service_name=name, unit_price=price, description=description)
        for name, price, description in SERVICES
    ]


async def seed(*, force: bool) -> None:
    container = ApplicationContainer()
    try:
        async with container.session_factory() as session, session.begin():
            if await _is_seeded(session):
                if not force:
                    logger.info("Database already contains data; nothing to do. Use --force to reseed.")
                    return
                logger.info("Clearing existing data before reseeding.")
                await _clear(session)

            session.add_all([*_customers(), *_slots(), *_services()])
            await session.flush()

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
                SLOT_DAYS * len(SLOT_TEMPLATE),
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
