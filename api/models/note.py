"""Pydantic V2 schemas for area notes.

Three schemas, not one, and the reason is the PUT/PATCH distinction:

* `NoteCreate`  — POST and PUT. Every meaningful field is required, because PUT
  *replaces* a resource: anything the client omits must fall back to the default,
  not to the previous value. That is what makes PUT idempotent.

* `NoteUpdate`  — PATCH. Every field is optional. The endpoint applies
  `model_dump(exclude_unset=True)`, which is the whole trick: it returns only the
  keys the client actually sent, so `{"body": null}` (explicitly clear it) is
  distinguishable from `{}` (don't touch it). A plain `exclude_none=True` would
  collapse those two cases and silently ignore a deliberate null.

* `NoteOut`     — the response. `from_attributes=True` lets it read straight off
  the ORM object instead of requiring a dict.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NoteTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str


class NoteCreate(BaseModel):
    """Full representation — used by POST (create) and PUT (replace)."""

    area_name: str = Field(..., min_length=1, max_length=200)
    title: str = Field(..., min_length=1, max_length=200)
    body: str | None = Field(None, max_length=4000)
    author: str = Field("anonymous", min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("area_name", "title", "author")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("tags")
    @classmethod
    def normalise_tags(cls, tags: list[str]) -> list[str]:
        seen: list[str] = []
        for raw in tags:
            tag = raw.strip().lower()
            if tag and tag not in seen:
                seen.append(tag)
        return seen


class NoteUpdate(BaseModel):
    """Partial representation — used by PATCH. Every field optional by design."""

    area_name: str | None = Field(None, min_length=1, max_length=200)
    title: str | None = Field(None, min_length=1, max_length=200)
    body: str | None = Field(None, max_length=4000)
    author: str | None = Field(None, min_length=1, max_length=100)
    tags: list[str] | None = Field(None, max_length=20)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "NoteUpdate":
        # model_fields_set is the set of keys actually present in the request body,
        # which is precisely what makes a merge-patch implementable.
        if not self.model_fields_set:
            raise ValueError("PATCH body must contain at least one field")
        return self


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    area_name: str
    title: str
    body: str | None
    author: str
    version: int
    created_at: datetime
    updated_at: datetime
    tags: list[NoteTagOut] = Field(default_factory=list)


class NoteListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    data: list[NoteOut]
