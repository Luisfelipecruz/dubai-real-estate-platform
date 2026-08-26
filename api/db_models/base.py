"""Declarative base for the ORM-managed tables."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base.

    2.0 style: subclass `DeclarativeBase` rather than calling the old
    `declarative_base()` factory. Combined with `Mapped[...]` annotations this
    gives real static typing — mypy and the IDE know that `AreaNote.title` is a
    `str`, which the 1.x `Column(String)` style could never express.
    """
