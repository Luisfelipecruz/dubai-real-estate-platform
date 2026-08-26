"""Analyst notes attached to a Dubai area — the ORM-managed write path.

Why this exists: the rest of the API is read-only analytics served with SQLAlchemy
Core (`text()` over the async engine), which is the right tool for dynamic-filter
aggregate queries over 200k+ rows. Notes are the opposite shape — small, mutable,
relational records with a parent/child collection — so they use the ORM properly.
Picking per access pattern rather than declaring one allegiance is the point.

Two things here exist specifically to be demonstrated:

* `AreaNote.tags` is a one-to-many collection left at the default `lazy="select"`.
  In async SQLAlchemy an implicit lazy load raises `MissingGreenlet`, because the
  loading would need to issue IO from inside attribute access. The router therefore
  eager-loads with `selectinload`, which emits a second `SELECT ... WHERE note_id IN
  (...)` instead of N queries. Compare with `joinedload`, which uses a LEFT OUTER
  JOIN and duplicates the parent row once per child.

* `version` implements optimistic locking via `__mapper_args__['version_id_col']`.
  SQLAlchemy adds `AND version = :old` to every UPDATE and raises `StaleDataError`
  if no row matched — i.e. somebody else committed first. That is the database half
  of the HTTP `If-Match`/`ETag` story the PATCH endpoint implements.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db_models.base import Base


class AreaNote(Base):
    __tablename__ = "area_notes"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Free text rather than a FK: area_name_en on raw_transactions is denormalised
    # DLD export data with no unique constraint to point at.
    area_name: Mapped[str] = mapped_column(String(200), index=True)

    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(4000), default=None)

    # Mapped[str] is NOT NULL; Mapped[str | None] is nullable. Nullability comes
    # from the type annotation in 2.0, not from a nullable= flag.
    author: Mapped[str] = mapped_column(String(100), default="anonymous")

    version: Mapped[int] = mapped_column(default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tags: Mapped[list["NoteTag"]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # version_id_col makes every UPDATE conditional on the version it read.
    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (Index("idx_area_notes_area_title", "area_name", "title"),)


class NoteTag(Base):
    __tablename__ = "note_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(
        ForeignKey("area_notes.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(50))

    note: Mapped["AreaNote"] = relationship(back_populates="tags")
