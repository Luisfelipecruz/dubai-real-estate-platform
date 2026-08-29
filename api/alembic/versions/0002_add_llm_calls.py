"""add llm_calls

One row per generation call: what it cost, how long it took, and whether the answer it
produced survived grounding verification.

WHY A TABLE AND NOT A LOG LINE
------------------------------
Every question m16 has to answer is an aggregate over this table -- cost per question,
cache hit rate, p50 and p95 latency, abstention rate, local 20B against claude-opus-5 on
the same golden set. All of those are one GROUP BY if the data is in Postgres and a
log-scraping script if it is not. The columns are chosen so that none of those questions
needs a schema change to ask.

`cost_usd` is stored as computed at call time rather than derived on read, and
`cost_priced` distinguishes "$0.00 because a local model has no per-token billing" from
"unknown because the model is not in the rate table". A NULL cost and a zero cost are
different facts and collapsing them makes the first look like a bargain.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        # The question, kept. Without it a slow or expensive row cannot be reproduced,
        # and an accounting table nobody can reproduce a row from is a billing summary.
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cache_read_input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "cache_creation_input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # The pre-call estimate, next to the provider's real count. Storing both is what
        # turns "the estimator is roughly right" into a number: one query over this table
        # gives the ratio and its spread, and the input guard is only as trustworthy as
        # that ratio.
        sa.Column(
            "estimated_input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        # Numeric, not float. Money summed over thousands of rows in binary floating
        # point drifts, and the drift is always discovered while reconciling a bill.
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("cost_priced", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieve_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repair_attempts", sa.Integer(), nullable=False, server_default="0"),
        # The grounding outcome, so quality and cost can be read off one row. An eval
        # that has to join answers to costs across two stores stops being run.
        sa.Column("answered", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("citations_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("citations_ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "grounding_warnings", sa.Integer(), nullable=False, server_default="0"
        ),
        # Anthropic's request id. The only handle that means anything in a support
        # conversation about a specific call, and it is unrecoverable after the fact.
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Every m16 aggregate slices by provider and by time. One composite index rather than
    # two single-column ones: the queries always have both.
    op.create_index(
        "idx_llm_calls_provider_created",
        "llm_calls",
        ["provider", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_llm_calls_provider_created", table_name="llm_calls")
    op.drop_table("llm_calls")
