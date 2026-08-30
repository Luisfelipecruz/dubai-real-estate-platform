"""add agent_tool_calls: the per-call record the platform currently throws away

WHAT THIS FIXES
---------------
`agent_runs` stores `tool_calls` and `tool_errors` as INTEGERS. The individual
`ToolInvocation` records -- name, category, arguments, `ok`, `duration_ms` -- are built by
the executor, returned in the HTTP response, rendered once by the evidence trace, and then
discarded when the request ends.

The consequence is exact and it is the reason m20 opens here: across 213 recorded runs,
31 of 301 tool calls failed. The database can state that 10.3% rate and cannot say whether
it is one broken tool or nine flaky ones, because the name of the failing tool was never
written down. Every other number on the observability panel can be recovered with a GROUP
BY over data that already exists. This one cannot be recovered at all.

WHY THERE IS NO BACKFILL
------------------------
There is nothing to backfill FROM. The per-call records for those 213 runs are gone, and
inventing plausible ones -- distributing the 31 failures across tools by frequency, say --
would produce a chart that looks like evidence and is fiction. Attribution therefore starts
at this migration, and the panel is required to say so: "since migration 0005", not "all
time". A run recorded before this table existed is not attributable and reports itself that
way.

WHY IT IS A SEPARATE TABLE AND NOT JSONB ON agent_runs
------------------------------------------------------
The question this exists to answer is "which tool fails most often", which is a GROUP BY
over rows. A JSONB column would answer it with `jsonb_array_elements` unnested on every
query, over a column that also carries the arguments and the results -- so the cheap
aggregate would drag the expensive payload through memory each time. Rows are also what
makes a partial index on failures possible, which is the query the panel runs first.

WHAT IS NOT STORED, ON PURPOSE
------------------------------
Not the tool RESULT. A result can be a truncated 8 KB SQL payload, and 301 of them is a
table that grows faster than the runs it describes while answering no question the panel
asks -- the full result is already in the run's HTTP response and the evidence trace. The
arguments ARE stored, because "resolve_area_name failed on which name?" is the first
question after "which tool failed", and arguments are small and bounded.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # No foreign key to agent_runs, and for the reason 0003 already gives about
        # llm_calls: the accounting write must never be able to fail a caller's request
        # because of an ordering problem. The run row is written at the END of the loop,
        # after the tool calls it describes, so an FK here would be violated by design.
        sa.Column("agent_run_id", sa.String(length=36), nullable=False),
        # The position of this call within its run, 1-based, matching ToolInvocation.step
        # and therefore matching what the evidence trace shows the user. A drill-in that
        # numbered its steps differently from the trace beside it would be worse than no
        # drill-in.
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        # sql | rag | geo | meta. Denormalised from the tool registry deliberately: the
        # category of a tool can change between releases, and the panel must report what
        # the category WAS when the call ran, not what it is now.
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column(
            "arguments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # False when the tool declined or raised. The run continues either way, which is
        # why this is not an error column on the run.
        sa.Column("ok", sa.Boolean(), nullable=False),
        # Present only when ok is false. The message the model was shown, truncated by the
        # executor -- so the panel reports what the model actually read.
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        # The repeat guard fired: this tool was called with these exact arguments earlier
        # in the same run. A high repeat rate is a routing problem, not a tool problem,
        # and the two must not be summed into one error rate.
        sa.Column("repeated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # The drill-in: every call of one run, in order.
    op.create_index(
        "idx_agent_tool_calls_run",
        "agent_tool_calls",
        ["agent_run_id", "step"],
        unique=False,
    )
    # The panel's first query: error rate by tool over a window.
    op.create_index(
        "idx_agent_tool_calls_tool_time",
        "agent_tool_calls",
        ["tool_name", "created_at"],
        unique=False,
    )
    # Partial, because the failures are the minority and the interesting set. At the
    # observed 10.3% rate this index covers roughly a tenth of the rows.
    op.create_index(
        "idx_agent_tool_calls_failures",
        "agent_tool_calls",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("NOT ok"),
    )


def downgrade() -> None:
    op.drop_index("idx_agent_tool_calls_failures", table_name="agent_tool_calls")
    op.drop_index("idx_agent_tool_calls_tool_time", table_name="agent_tool_calls")
    op.drop_index("idx_agent_tool_calls_run", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
