"""add eval_results: one row per recorded evaluation run

WHAT THIS TABLE HOLDS
---------------------
The result of a full pass of the evaluation harness: the rates it measured, the counts
behind them, and enough context to say what the measurement was made against.

Without it a score exists only in the terminal that produced it. `eval/thresholds.yaml`
holds the floors and `scripts/run_eval.py` produces the values, and the two never meet:
nothing can be asked, over HTTP, whether this deployment currently passes its own gate.

WHY POSTGRES AND NOT A JSON FILE ON DISK
----------------------------------------
`eval/` is mounted read-only into the api container, deliberately -- a container that can
rewrite its own fixtures can turn a failing evaluation into a passing one. Results would
therefore need a second, writable mount beside the read-only one, and a reader has to
work out every time which of the two is which.

The stronger reason is that "the latest score" is the wrong shape for the question this
gets asked. One number with no history cannot say whether the system is improving, and a
rate that moved sharply within a day is invisible in any single reading of it. Rows with
timestamps make that comparison available without a second storage system.

WHY THE PAYLOAD IS JSONB AND THE REST IS COLUMNS
------------------------------------------------
The measurement is a document whose keys depend on which suites ran, so a column per
metric would need a migration every time a fixture gains a section.

What is NOT in the JSONB is everything a query filters or orders by: when the run
happened, which suite, which provider, whether the gate passed. Those are columns, and
indexed, because "the most recent run of this suite" is the query the endpoint issues.

WHAT IS DELIBERATELY NOT STORED
-------------------------------
The per-question responses. A run carries one model answer per question, some of them
thousands of characters, and keeping them here would make this table grow faster than
`agent_runs` while answering no question the endpoint asks. They are written to the
harness's `--out` file instead, which is what re-grading reads.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eval_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # When the RUN finished, set by the harness rather than by the database. A run
        # takes tens of minutes, so `now()` at insert time would date the measurement to
        # whenever the row happened to be written -- close enough to look right, and wrong
        # in the way that is hardest to notice later.
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        # truths | retrieval | agent | all. The endpoint must never present a partial
        # suite as though it were a full one: an agent-only run measures no retrieval
        # metric, and the difference between "0.0" and "not measured" is the whole point
        # of the three-state rendering this table exists to feed.
        sa.Column("suite", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=False, server_default="0"),
        # Whether the gate ran, and separately whether it passed. The two are kept
        # apart because a run with no gate is not a run whose gate passed, and collapsing
        # them into one boolean is how a green dashboard gets drawn from an ungated run.
        sa.Column("gate_applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("gate_passed", sa.Boolean(), nullable=True),
        # The {section: {metric: value}} document the gate compares against the floors.
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Everything needed to say what this score was measured AGAINST: fixture sizes,
        # the registered tool names, the raw pass/fail counts behind each rate, the base
        # URL. The tool list is the load-bearing part. A score measured against nine tools
        # is not a current statement about a system that registers ten, and nothing else
        # in the record would reveal the difference.
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # The endpoint's only query: newest first, usually with a suite filter.
    op.create_index(
        "idx_eval_results_recorded",
        "eval_results",
        ["suite", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_eval_results_recorded", table_name="eval_results")
    op.drop_table("eval_results")
