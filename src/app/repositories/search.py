from sqlalchemy import ColumnElement
from sqlalchemy.orm import InstrumentedAttribute


def contains_text(column: InstrumentedAttribute[str], text: str) -> ColumnElement[bool]:
    """Case-insensitive substring match where `%` and `_` in `text` are literal.

    A customer named "50% off" must not turn into a wildcard search.
    """
    escaped = text.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return column.ilike(f"%{escaped}%", escape="!")
