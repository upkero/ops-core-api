import enum

from sqlalchemy import Enum
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def pg_enum[E: enum.Enum](enum_cls: type[E], name: str) -> Enum:
    """Postgres ENUM column storing the member *values*, not their Python names.

    SQLAlchemy defaults to the names ("ACTIVE"), which would leak Python casing
    into the API and the database. Declared once here so every enum column in
    models/ is built the same way.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda members: [member.value for member in members],
    )
