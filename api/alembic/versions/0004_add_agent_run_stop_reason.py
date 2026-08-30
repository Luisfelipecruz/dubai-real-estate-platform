"""add agent_runs.stop_reason: the discriminator that was already being computed

WHAT THIS FIXES
---------------
M-47 -- 8 of 147 answered runs came back with a null answer -- stood as an open question
for three milestones with the note "nothing here distinguishes them". Something did.
`finish_reason` is on every provider response, is carried as `LLMResponse.stop_reason`, and
is copied onto `AgentStep.stop_reason` for the HTTP response. It is then dropped: neither
`llm_calls` nor `agent_runs` has a column for it, so it survives exactly as long as the
request that produced it.

Wrapping the provider and replaying both populations on 2026-08-30 split the eight runs
cleanly in half on that one field:

    finish_reason='length'  1200 of 1200 output tokens, 4,906 chars reasoning, 0 content
    finish_reason='stop'    14 output tokens,           0 chars reasoning,     0 content

Four runs each. Two different causes, needing two different fixes. With the column in
place, `services/synthesis/census.py` stops inferring the split from the token count and
reads it.

WHY NOT ON llm_calls INSTEAD
-----------------------------
Both would be defensible and `agent_runs` is the one that answers the question being asked.
The question is "why did THIS RUN produce no answer", which is a property of the run's
final turn; putting it on `llm_calls` would mean a DISTINCT ON subquery on every read to
find the last turn, which is exactly what the census has to do today and what this column
exists to remove. `llm_calls` gaining its own copy for per-turn analysis is a reasonable
later change and is not this one.

WHY THERE IS NO BACKFILL
------------------------
Same reason as the agent_tool_calls migration, and the same discipline. The finish reasons for the 213 recorded runs
were never written down, and deriving them from `output_tokens` would turn an inference
into a stored fact that later reads would trust. The census infers the split for old rows
and SAYS it is inferring; a backfilled column could not say anything.

The column is nullable and has no default for that reason: NULL means "recorded before this
migration", and it is distinguishable from every real finish reason.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        # 32 chars matches `agent_runs.outcome`. The longest value either provider
        # currently emits is `max_tokens` at 10.
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
    )
    # Partial: the rows worth finding are the ones that stopped for a reason other than
    # the model finishing normally, and `tool_calls` dominates the table. The same shape
    # as the agent_tool_calls migration's `WHERE NOT ok`.
    op.create_index(
        "idx_agent_runs_stop_reason",
        "agent_runs",
        ["stop_reason"],
        unique=False,
        postgresql_where=sa.text("stop_reason IS NOT NULL AND stop_reason <> 'stop'"),
    )


def downgrade() -> None:
    op.drop_index("idx_agent_runs_stop_reason", table_name="agent_runs")
    op.drop_column("agent_runs", "stop_reason")
