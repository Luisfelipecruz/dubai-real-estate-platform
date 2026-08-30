"""add agent_runs, and attribute llm_calls rows to a run

WHY THIS EXTENDS 0002 RATHER THAN EDITING IT
---------------------------------------------
0002 has been applied to the running database. Editing an applied migration means the
schema on disk and the schema in the file disagree for everyone who already ran it, and
the disagreement is silent -- Alembic records the revision, not its contents. So the new
columns arrive as their own revision even though they belong to a table 0002 created.

WHAT A ROW IS
-------------
One `agent_runs` row per `POST /agent/query`. One `llm_calls` row per TURN inside it,
linked by `agent_run_id`. That split is what makes the step budget enforceable from data
rather than from a counter: "has this run spent more than AGENT_MAX_COST_USD_PER_RUN" is
a SUM over llm_calls, and it stays true even if the executor crashes halfway, because the
rows are already committed.

It also fixes an accounting hole that would otherwise open the moment the agent shipped.
The agent's `ask_documents` tool calls the same `services.ask.answer` that `POST /ask`
calls, so without `endpoint` and `agent_run_id` on the row, every nested call would be
indistinguishable from a direct one -- and `GET /ask/costs`, which m14 built to report
/ask's cost and abstention rate, would silently start reporting the agent's traffic as
its own. The abstention rate is the number that would have been corrupted worst: the
agent asks sub-questions that are MEANT to be refused.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        # A client-generated string rather than a serial. The executor needs the id
        # BEFORE the first turn, so that a turn which fails still leaves attributed rows
        # behind; waiting for a database-assigned id would mean the first turn of a run
        # that crashes is orphaned, which is exactly the run worth investigating.
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        # Distinct outcomes, not a boolean. `answered` and `refused` are both successes;
        # `max_steps` and `failed` are not, and collapsing the four into one flag makes
        # the step cap's firing rate uncollectable -- which is the number that says
        # whether AGENT_MAX_STEPS is set anywhere near right.
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_errors", sa.Integer(), nullable=False, server_default="0"),
        # Which tool categories the run actually used, e.g. "sql,geo". This is what
        # eval/golden/routing.yaml grades against: a numeric question served entirely
        # from `rag` is a routing failure even when the prose reads correctly.
        sa.Column("categories", sa.String(length=128), nullable=True),
        sa.Column("total_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("cost_priced", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_ms", sa.Integer(), nullable=False, server_default="0"),
        # Numbers in the final answer that appear in no tool result. The real version of
        # the guard IMPLEMENTATION-PLAN.md §4.4 describes: m14 could only check a number
        # against retrieved prose, because there were no tools to check it against.
        sa.Column(
            "unverified_numbers", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_agent_runs_created", "agent_runs", ["created_at"], unique=False
    )
    op.create_index(
        "idx_agent_runs_outcome", "agent_runs", ["outcome"], unique=False
    )

    # Nullable, with no foreign key. A generation call made by POST /ask belongs to no
    # run and never will, so NOT NULL is wrong; and an FK would make an accounting write
    # able to fail because of an ordering problem, which is the wrong trade -- losing a
    # cost row must never cost a caller their answer.
    op.add_column(
        "llm_calls", sa.Column("agent_run_id", sa.String(length=36), nullable=True)
    )
    op.create_index(
        "idx_llm_calls_agent_run", "llm_calls", ["agent_run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_llm_calls_agent_run", table_name="llm_calls")
    op.drop_column("llm_calls", "agent_run_id")
    op.drop_index("idx_agent_runs_outcome", table_name="agent_runs")
    op.drop_index("idx_agent_runs_created", table_name="agent_runs")
    op.drop_table("agent_runs")
