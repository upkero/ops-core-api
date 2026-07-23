from collections.abc import Callable

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.pagination import PageDTO, PaginationParams


async def paginate[Row, Item](
    session: AsyncSession,
    statement: Select[tuple[Row]],
    params: PaginationParams,
    to_contract: Callable[[Row], Item],
) -> PageDTO[Item]:
    """Turn any filtered query into one page of contracts.

    The single implementation every collection shares: each repository supplies
    its own `select()` with its own filters and ordering, and this counts and
    slices it. Counting the caller's own statement — rather than a
    hand-written second query per repository — is what stops `total` from
    drifting away from the filters that produced `items`.
    """
    # ORDER BY is meaningless inside a COUNT and Postgres would sort for
    # nothing, so it is stripped before wrapping the query as a subquery.
    counted = statement.order_by(None).subquery()
    total = await session.scalar(select(func.count()).select_from(counted)) or 0

    rows = await session.scalars(statement.limit(params.limit).offset(params.offset))
    return PageDTO(
        items=[to_contract(row) for row in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )
