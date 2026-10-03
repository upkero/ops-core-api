"""Tests that need a real Postgres with pgvector.

The `<=>` query, the row lock and the ILIKE escaping are SQL, so a fake
repository cannot prove any of them work. Skipped unless TEST_DB_URL points at
a database; CI supplies one via a pgvector service container.
"""

from datetime import date, time
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.enums import ResourceType
from src.app.contracts.knowledge import EMBEDDING_DIMENSIONS, NewChunk, NewDocument
from src.app.contracts.pagination import PaginationParams
from src.app.exceptions.domain import SlotUnavailableError
from src.app.llm.hashing_embedding_client import HashingEmbeddingClient
from src.app.models.booking import BookingSlot
from src.app.models.customer import Customer
from src.app.models.pricing import PricingItem
from src.app.repositories.booking import SqlAlchemyBookingRepository
from src.app.repositories.customer import SqlAlchemyCustomerRepository
from src.app.repositories.knowledge import SqlAlchemyKnowledgeRepository
from src.app.repositories.pricing import SqlAlchemyPricingRepository
from src.app.services.booking import BookingService

CHUNKS = [
    "Appointments can be cancelled or rescheduled free of charge up to twenty-four hours before the start time.",
    "Parking is available in the underground garage beneath the building for two hours free of charge.",
    "Our deep tissue massage uses firm pressure to release chronic muscle tension in the back and shoulders.",
]


@pytest.fixture
def embedder() -> HashingEmbeddingClient:
    return HashingEmbeddingClient(dimensions=EMBEDDING_DIMENSIONS)


async def _store_chunks(session: AsyncSession, embedder: HashingEmbeddingClient) -> SqlAlchemyKnowledgeRepository:
    repository = SqlAlchemyKnowledgeRepository(session)
    vectors = await embedder.embed_batch(CHUNKS)
    await repository.add_document(
        NewDocument(
            title="Clinic handbook",
            content="\n\n".join(CHUNKS),
            embedding=vectors[0],
            embedding_model=embedder.fingerprint,
            chunks=[
                NewChunk(chunk_index=index, chunk_text=chunk, embedding=vector)
                for index, (chunk, vector) in enumerate(zip(CHUNKS, vectors, strict=True))
            ],
        )
    )
    return repository


async def test_search_ranks_the_relevant_chunk_first(
    session: AsyncSession,
    embedder: HashingEmbeddingClient,
) -> None:
    repository = await _store_chunks(session, embedder)

    matches = await repository.search_chunks(
        await embedder.embed_query("how do I cancel my appointment"),
        top_k=3,
        embedding_model=embedder.fingerprint,
    )

    assert matches[0].chunk_text == CHUNKS[0]
    assert matches[0].document_title == "Clinic handbook"


async def test_search_returns_matches_in_ascending_distance_order(
    session: AsyncSession,
    embedder: HashingEmbeddingClient,
) -> None:
    repository = await _store_chunks(session, embedder)

    matches = await repository.search_chunks(
        await embedder.embed_query("underground parking garage"),
        top_k=3,
        embedding_model=embedder.fingerprint,
    )

    distances = [match.distance for match in matches]
    assert distances == sorted(distances)
    assert all(match.score == pytest.approx(1.0 - match.distance) for match in matches)


async def test_score_stays_within_cosine_range_for_a_non_normalised_query(
    session: AsyncSession,
    embedder: HashingEmbeddingClient,
) -> None:
    # Deliberately not unit length: `<=>` normalises internally, which is why
    # the repository uses it rather than deriving cosine from an L2 distance.
    await _store_chunks(session, embedder)
    repository = SqlAlchemyKnowledgeRepository(session)
    raw = [value * 7.5 for value in await embedder.embed_query("parking garage")]

    matches = await repository.search_chunks(raw, top_k=3, embedding_model=embedder.fingerprint)

    assert all(-1.0 <= match.score <= 1.0 for match in matches)
    assert matches[0].chunk_text == CHUNKS[1]


async def test_top_k_limits_the_result_size(session: AsyncSession, embedder: HashingEmbeddingClient) -> None:
    repository = await _store_chunks(session, embedder)

    found = await repository.search_chunks(
        await embedder.embed_query("massage"),
        top_k=1,
        embedding_model=embedder.fingerprint,
    )

    assert len(found) == 1


async def test_search_excludes_chunks_from_another_model(
    session: AsyncSession,
    embedder: HashingEmbeddingClient,
) -> None:
    # The filter has to hold in SQL, not just in the service: this is the query
    # that would otherwise happily compare vectors from two different models.
    repository = await _store_chunks(session, embedder)

    matches = await repository.search_chunks(
        await embedder.embed_query("cancel appointment"),
        top_k=10,
        embedding_model="openai:text-embedding-3-small",
    )

    assert matches == []
    assert sorted(await repository.list_embedding_models()) == [embedder.fingerprint]


async def test_booking_marks_the_slot_taken_in_the_database(session: AsyncSession) -> None:
    slot = BookingSlot(
        resource_type=ResourceType.TABLE,
        slot_date=date(2026, 8, 1),
        slot_time=time(19, 0),
        capacity=4,
    )
    session.add(slot)
    await session.flush()

    bookings = SqlAlchemyBookingRepository(session)
    service = BookingService(bookings)
    await service.create_booking("Dmitri Volkov", slot.id, party_size=2)

    assert (await bookings.list_available_slots(None, None, PaginationParams())).items == []
    with pytest.raises(SlotUnavailableError):
        await service.create_booking("Dmitri Volkov", slot.id, party_size=2)


async def test_the_idempotency_key_is_unique_in_the_database(session: AsyncSession) -> None:
    # The application checks for a replay first, but the unique index is what
    # makes two simultaneous retries impossible rather than merely unlikely.
    slots = [
        BookingSlot(
            resource_type=ResourceType.TABLE,
            slot_date=date(2026, 8, 2),
            slot_time=time(19, index),
            capacity=4,
        )
        for index in range(2)
    ]
    session.add_all(slots)
    await session.flush()
    bookings = SqlAlchemyBookingRepository(session)

    await bookings.create_booking("Dmitri Volkov", slots[0].id, 2, idempotency_key="same-key")
    with pytest.raises(IntegrityError):
        await bookings.create_booking("Dmitri Volkov", slots[1].id, 2, idempotency_key="same-key")


async def test_pagination_counts_the_filtered_set_in_sql(session: AsyncSession) -> None:
    # The COUNT runs over the caller's own statement. If it ever stopped doing
    # that, `total` would report every slot in the table instead of the five
    # that match the filter, and a client would page into nothing.
    session.add_all(
        [
            BookingSlot(
                resource_type=ResourceType.TABLE if index % 2 else ResourceType.MEETING_ROOM,
                slot_date=date(2026, 8, 1),
                slot_time=time(9 + index, 0),
                capacity=4,
            )
            for index in range(10)
        ]
    )
    await session.flush()
    repository = SqlAlchemyBookingRepository(session)

    page = await repository.list_available_slots(
        date(2026, 8, 1),
        ResourceType.TABLE,
        PaginationParams(limit=2, offset=0),
    )
    last = await repository.list_available_slots(
        date(2026, 8, 1),
        ResourceType.TABLE,
        PaginationParams(limit=2, offset=4),
    )

    assert page.total == 5
    assert len(page.items) == 2
    assert page.has_more is True
    assert len(last.items) == 1
    assert last.has_more is False


async def test_customer_search_escapes_sql_wildcards(session: AsyncSession) -> None:
    session.add_all([Customer(name="Anna 100% Wellness"), Customer(name="Marcus Feld")])
    await session.flush()
    repository = SqlAlchemyCustomerRepository(session)

    # A literal '%' must match only the name containing it, not act as a wildcard.
    matched = await repository.search_by_name("100%", PaginationParams(limit=10))

    assert [customer.name for customer in matched.items] == ["Anna 100% Wellness"]


async def test_pricing_lookup_is_case_insensitive(session: AsyncSession) -> None:
    session.add(PricingItem(service_name="Deep Tissue Massage", unit_price=Decimal("120.00")))
    await session.flush()

    found = await SqlAlchemyPricingRepository(session).get_by_service_name("deep tissue massage")

    assert found is not None
    assert found.unit_price == Decimal("120.00")
