"""In-memory implementations of every port.

These are the second implementation that justifies the interfaces: services are
tested against them with no database, no network and no embedding provider.
"""

import math
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.customer import CustomerDTO
from src.app.contracts.enums import BookingStatus, CustomerStatus, ResourceType
from src.app.contracts.knowledge import ChunkMatchDTO, DocumentDTO, NewDocument
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.contracts.pricing import PricingItemDTO
from src.app.interfaces.llm.embedding_client import EmbeddingClient
from src.app.interfaces.repositories.booking_repository import BookingRepository
from src.app.interfaces.repositories.customer_repository import CustomerRepository
from src.app.interfaces.repositories.knowledge_repository import KnowledgeRepository
from src.app.interfaces.repositories.pricing_repository import PricingRepository


def make_customer(name: str = "Anna Petrova", **overrides: object) -> CustomerDTO:
    base = CustomerDTO(
        id=uuid4(),
        name=name,
        status=CustomerStatus.ACTIVE,
        last_contact_at=datetime(2026, 7, 1, tzinfo=UTC),
        notes=None,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def make_slot(**overrides: object) -> BookingSlotDTO:
    base = BookingSlotDTO(
        id=uuid4(),
        resource_type=ResourceType.TABLE,
        slot_date=date(2026, 8, 1),
        slot_time=datetime(2026, 8, 1, 19, 0, tzinfo=UTC).time(),
        capacity=4,
        is_available=True,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _page[T](items: Sequence[T], params: PaginationParams) -> PageDTO[T]:
    """Slice in memory the way the SQL helper slices in the database."""
    return PageDTO(
        items=list(items)[params.offset : params.offset + params.limit],
        total=len(items),
        limit=params.limit,
        offset=params.offset,
    )


class FakeCustomerRepository(CustomerRepository):
    def __init__(self, customers: Sequence[CustomerDTO] = ()) -> None:
        self.customers = list(customers)

    async def get_by_id(self, customer_id: UUID) -> CustomerDTO | None:
        return next((c for c in self.customers if c.id == customer_id), None)

    async def search_by_name(self, query: str, params: PaginationParams) -> PageDTO[CustomerDTO]:
        found = [c for c in self.customers if query.lower() in c.name.lower()]
        return _page(found, params)

    async def list_all(self, params: PaginationParams) -> PageDTO[CustomerDTO]:
        return _page(self.customers, params)

    async def create(self, name: str, status: CustomerStatus, notes: str | None) -> CustomerDTO:
        customer = CustomerDTO(id=uuid4(), name=name, status=status, last_contact_at=None, notes=notes)
        self.customers.append(customer)
        return customer


class FakeBookingRepository(BookingRepository):
    def __init__(self, slots: Sequence[BookingSlotDTO] = ()) -> None:
        self.slots = {slot.id: slot for slot in slots}
        self.bookings: list[BookingDTO] = []
        self.locked: list[UUID] = []
        self.by_key: dict[str, BookingDTO] = {}

    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        params: PaginationParams,
    ) -> PageDTO[BookingSlotDTO]:
        found = [
            slot
            for slot in self.slots.values()
            if slot.is_available
            and (slot_date is None or slot.slot_date == slot_date)
            and (resource_type is None or slot.resource_type == resource_type)
        ]
        return _page(sorted(found, key=lambda slot: (slot.slot_date, slot.slot_time)), params)

    async def lock_slot(self, slot_id: UUID) -> BookingSlotDTO | None:
        self.locked.append(slot_id)
        return self.slots.get(slot_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> BookingDTO | None:
        return self.by_key.get(idempotency_key)

    async def create_booking(
        self,
        guest_name: str,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None = None,
    ) -> BookingDTO:
        booking = BookingDTO(
            id=uuid4(),
            guest_name=guest_name,
            slot_id=slot_id,
            party_size=party_size,
            created_at=datetime(2026, 7, 22, tzinfo=UTC),
        )
        self.bookings.append(booking)
        if idempotency_key is not None:
            self.by_key[idempotency_key] = booking
        return booking

    async def mark_slot_taken(self, slot_id: UUID) -> None:
        self.slots[slot_id] = replace(self.slots[slot_id], is_available=False)

    async def mark_slot_free(self, slot_id: UUID) -> None:
        self.slots[slot_id] = replace(self.slots[slot_id], is_available=True)

    async def get_booking(self, booking_id: UUID) -> BookingDTO | None:
        return next((b for b in self.bookings if b.id == booking_id), None)

    async def list_bookings(
        self,
        guest_name: str | None,
        slot_date: date | None,
        status: BookingStatus | None,
        params: PaginationParams,
    ) -> PageDTO[BookingDTO]:
        found = [
            booking
            for booking in self.bookings
            if (not guest_name or guest_name.lower() in booking.guest_name.lower())
            and (slot_date is None or self.slots[booking.slot_id].slot_date == slot_date)
            and (status is None or booking.status is status)
        ]
        return _page(found, params)

    async def mark_cancelled(self, booking_id: UUID) -> BookingDTO:
        index = next(i for i, b in enumerate(self.bookings) if b.id == booking_id)
        cancelled = replace(
            self.bookings[index],
            status=BookingStatus.CANCELLED,
            cancelled_at=datetime(2026, 7, 23, tzinfo=UTC),
        )
        self.bookings[index] = cancelled
        for key, booking in self.by_key.items():
            if booking.id == booking_id:
                self.by_key[key] = cancelled
        return cancelled


class FakePricingRepository(PricingRepository):
    def __init__(self, items: Sequence[PricingItemDTO] = ()) -> None:
        self.items = list(items)

    async def get_by_service_name(self, service_name: str) -> PricingItemDTO | None:
        return next((i for i in self.items if i.service_name.lower() == service_name.lower()), None)

    async def list_all(self, params: PaginationParams) -> PageDTO[PricingItemDTO]:
        return _page(sorted(self.items, key=lambda item: item.service_name), params)


def make_pricing_item(name: str = "Deep Tissue Massage", price: str = "120.00") -> PricingItemDTO:
    return PricingItemDTO(id=uuid4(), service_name=name, unit_price=Decimal(price), description=None)


@dataclass
class _StoredChunk:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int
    chunk_text: str
    embedding: Sequence[float]
    embedding_model: str


class FakeKnowledgeRepository(KnowledgeRepository):
    def __init__(self) -> None:
        self.documents: list[NewDocument] = []
        self.chunks: list[_StoredChunk] = []

    async def list_embedding_models(self) -> Sequence[str]:
        return sorted({chunk.embedding_model for chunk in self.chunks})

    async def add_document(self, document: NewDocument) -> DocumentDTO:
        self.documents.append(document)
        document_id = uuid4()
        self.chunks.extend(
            _StoredChunk(
                chunk_id=uuid4(),
                document_id=document_id,
                document_title=document.title,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                embedding=chunk.embedding,
                embedding_model=document.embedding_model,
            )
            for chunk in document.chunks
        )
        return DocumentDTO(
            id=document_id,
            title=document.title,
            content=document.content,
            chunk_count=len(document.chunks),
            created_at=datetime(2026, 7, 22, tzinfo=UTC),
        )

    async def search_chunks(
        self,
        embedding: Sequence[float],
        top_k: int,
        embedding_model: str,
    ) -> Sequence[ChunkMatchDTO]:
        candidates = [chunk for chunk in self.chunks if chunk.embedding_model == embedding_model]
        scored = sorted(
            ((_cosine_distance(embedding, chunk.embedding), chunk) for chunk in candidates),
            key=lambda pair: pair[0],
        )
        return [
            ChunkMatchDTO(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                distance=distance,
                score=1.0 - distance,
            )
            for distance, chunk in scored[:top_k]
        ]


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return 1.0 - (dot / norm if norm else 0.0)


@dataclass
class FakeEmbeddingClient(EmbeddingClient):
    """Records what it was asked to embed so tests can assert on batching."""

    dimension: int = 8
    model: str = "v1"
    batches: list[Sequence[str]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def dimensions(self) -> int:
        return self.dimension

    async def embed_query(self, text: str) -> Sequence[float]:
        self.queries.append(text)
        return self._vector(text)

    async def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.batches.append(list(texts))
        return [self._vector(text) for text in texts]

    async def close(self) -> None:
        return None

    def _vector(self, text: str) -> list[float]:
        # Deterministic and word-sensitive enough that "closest chunk" is
        # predictable in assertions.
        vector = [0.0] * self.dimension
        for word in text.lower().split():
            # zlib.crc32, not hash(): str hashing is salted per process, which
            # would make ranking assertions pass or fail run to run.
            vector[zlib.crc32(word.encode()) % self.dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else [1.0] + [0.0] * (self.dimension - 1)
