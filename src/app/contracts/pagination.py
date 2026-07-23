from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_LIMIT = 20
MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class PaginationParams:
    """How much of a collection to return, and from where.

    Domain-neutral on purpose: one definition travels from the router through
    the service to the repository, so no layer invents its own limit handling.
    """

    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        # Validated here as well as at the HTTP boundary, because the seeding
        # command and the future agent services construct these directly.
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}.")
        if self.offset < 0:
            raise ValueError("offset must not be negative.")


@dataclass(frozen=True, slots=True)
class PageDTO[T]:
    """One slice of a collection, plus what it takes to ask for the next.

    `total` is what makes a truncated result honest: without it a caller cannot
    tell "these are all of them" from "this is the first 20 of 500", which is
    how an agent ends up telling a customer there are no free slots.
    """

    items: Sequence[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total
