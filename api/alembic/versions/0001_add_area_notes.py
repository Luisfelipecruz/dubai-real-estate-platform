"""add area_notes and note_tags

The ORM-managed write path. Everything else in this database is created by
infra/postgres/init.sql; these two tables are the ones under migration control.

Revision ID: 0001
Revises:
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "area_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("area_name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=True),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_area_notes_area_name", "area_notes", ["area_name"])
    op.create_index("idx_area_notes_area_title", "area_notes", ["area_name", "title"])

    op.create_table(
        "note_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["area_notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_note_tags_note_id", "note_tags", ["note_id"])


def downgrade() -> None:
    op.drop_index("ix_note_tags_note_id", table_name="note_tags")
    op.drop_table("note_tags")
    op.drop_index("idx_area_notes_area_title", table_name="area_notes")
    op.drop_index("ix_area_notes_area_name", table_name="area_notes")
    op.drop_table("area_notes")
