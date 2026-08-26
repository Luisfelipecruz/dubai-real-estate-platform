"""Analyst notes — the ORM-managed write path, and the PUT-vs-PATCH demonstration.

Every other router in this API is read-only analytics on SQLAlchemy Core. This one
is deliberately the other half: declarative ORM models, a session from dependency
injection, a parent/child relationship eager-loaded with `selectinload`, and
optimistic concurrency control wired from the HTTP layer (`If-Match`/`ETag`) down
to the database (`version_id_col`).

The PUT/PATCH pair is the part to demo:

    PUT   /notes/{id}   body = NoteCreate  -> full replacement. Omitted fields are
                                             reset to their defaults, so sending the
                                             same request twice leaves the same state.
                                             Idempotent.

    PATCH /notes/{id}   body = NoteUpdate  -> merge patch. Only the keys present in
                                             the request body are touched, via
                                             model_dump(exclude_unset=True).

The difference is visible in one command: PUT without `body` clears the body; PATCH
without `body` leaves it alone.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from database import get_db
from db_models.note import AreaNote, NoteTag
from models.note import NoteCreate, NoteListResponse, NoteOut, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])


def _etag(note: AreaNote) -> str:
    """Weak ETag derived from the row version — the HTTP face of version_id_col."""
    return f'W/"{note.version}"'


def _check_if_match(note: AreaNote, if_match: str | None) -> None:
    """412 if the client is editing a version that is no longer current."""
    if if_match is None:
        return
    candidates = {t.strip() for t in if_match.split(",")}
    if "*" in candidates:
        return
    if _etag(note) not in candidates and f'"{note.version}"' not in candidates:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=f"ETag mismatch: current version is {note.version}",
        )


async def _reload(db: AsyncSession, note_id: int) -> AreaNote:
    """Re-SELECT a note after a write, with everything the response needs loaded.

    This is not defensive padding — it fixes a real failure. `updated_at` carries
    `onupdate=func.now()`, so after an UPDATE its value is computed server-side and
    SQLAlchemy marks the attribute expired. Serialising the object then triggers a
    lazy refresh, and lazy IO from attribute access is exactly what async SQLAlchemy
    cannot do: it raises `MissingGreenlet`. INSERT does not hit this because 2.0
    fetches server defaults with RETURNING.

    `populate_existing=True` forces the identity-mapped instance to take the fresh
    row rather than keeping its stale loaded state.
    """
    result = await db.execute(
        select(AreaNote)
        .options(selectinload(AreaNote.tags))
        .where(AreaNote.id == note_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _get_note_or_404(db: AsyncSession, note_id: int) -> AreaNote:
    """Load a note with its tags eagerly.

    `selectinload` matters here beyond performance: with the default lazy="select",
    touching `note.tags` after the query would need to emit IO from attribute
    access, which async SQLAlchemy cannot do — it raises MissingGreenlet.
    """
    result = await db.execute(
        select(AreaNote).options(selectinload(AreaNote.tags)).where(AreaNote.id == note_id)
    )
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.get("", response_model=NoteListResponse)
async def list_notes(
    area_name: str | None = Query(None, description="Exact area name filter"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List notes.

    One `SELECT` for the notes plus one `SELECT ... WHERE note_id IN (...)` for all
    their tags — two queries regardless of page size. Without `selectinload` this
    would be 1 + N.
    """
    stmt = select(AreaNote).options(selectinload(AreaNote.tags))
    count_stmt = select(func.count()).select_from(AreaNote)

    if area_name:
        stmt = stmt.where(AreaNote.area_name == area_name)
        count_stmt = count_stmt.where(AreaNote.area_name == area_name)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = await db.execute(stmt.order_by(AreaNote.id).limit(limit).offset(offset))

    return NoteListResponse(
        total=total,
        limit=limit,
        offset=offset,
        data=[NoteOut.model_validate(n) for n in rows.scalars().all()],
    )


@router.get("/{note_id}", response_model=NoteOut)
async def get_note(note_id: int, response: Response, db: AsyncSession = Depends(get_db)):
    note = await _get_note_or_404(db, note_id)
    response.headers["ETag"] = _etag(note)
    return NoteOut.model_validate(note)


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate, response: Response, db: AsyncSession = Depends(get_db)
):
    """Create a note. POST is neither safe nor idempotent — call it twice, get two rows."""
    note = AreaNote(
        area_name=payload.area_name,
        title=payload.title,
        body=payload.body,
        author=payload.author,
        tags=[NoteTag(label=label) for label in payload.tags],
    )
    db.add(note)
    await db.flush()  # assign the PK without ending the transaction
    note = await _reload(db, note.id)

    response.headers["ETag"] = _etag(note)
    return NoteOut.model_validate(note)


@router.put("/{note_id}", response_model=NoteOut)
async def replace_note(
    note_id: int,
    payload: NoteCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    if_match: str | None = Header(None, alias="If-Match"),
):
    """Full replacement.

    Every field is overwritten from the payload, including the ones the client left
    out — those go back to their schema defaults. `body` omitted means `body` becomes
    NULL. That is what makes PUT idempotent: the final state depends only on the
    request, never on what was there before.
    """
    note = await _get_note_or_404(db, note_id)
    _check_if_match(note, if_match)

    note.area_name = payload.area_name
    note.title = payload.title
    note.body = payload.body           # None when omitted -> cleared, by design
    note.author = payload.author       # falls back to the "anonymous" default

    note.tags.clear()
    for label in payload.tags:
        note.tags.append(NoteTag(label=label))

    try:
        await db.flush()
    except StaleDataError:
        raise HTTPException(status_code=409, detail="Concurrent update, retry") from None

    note = await _reload(db, note_id)
    response.headers["ETag"] = _etag(note)
    return NoteOut.model_validate(note)


@router.patch("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: int,
    payload: NoteUpdate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    if_match: str | None = Header(None, alias="If-Match"),
):
    """Partial update (RFC 7396-style merge patch).

    `exclude_unset=True` is the entire mechanism. It yields only the keys the client
    actually sent, so:

        {}                  -> rejected by the model validator, nothing to do
        {"title": "x"}      -> title changes, body untouched
        {"body": null}      -> body explicitly cleared

    `exclude_none=True` would be wrong here: it cannot tell the last two apart.
    """
    note = await _get_note_or_404(db, note_id)
    _check_if_match(note, if_match)

    changes = payload.model_dump(exclude_unset=True)

    if "tags" in changes:
        labels = changes.pop("tags") or []
        note.tags.clear()
        for label in labels:
            note.tags.append(NoteTag(label=label))

    for field, value in changes.items():
        setattr(note, field, value)

    try:
        await db.flush()
    except StaleDataError:
        raise HTTPException(status_code=409, detail="Concurrent update, retry") from None

    note = await _reload(db, note_id)
    response.headers["ETag"] = _etag(note)
    return NoteOut.model_validate(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    if_match: str | None = Header(None, alias="If-Match"),
):
    """Delete. Idempotent in effect, though the second call honestly reports 404.

    Tags go with it: `cascade="all, delete-orphan"` handles the ORM side and
    `ON DELETE CASCADE` handles anyone writing SQL directly.
    """
    note = await _get_note_or_404(db, note_id)
    _check_if_match(note, if_match)
    await db.delete(note)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
