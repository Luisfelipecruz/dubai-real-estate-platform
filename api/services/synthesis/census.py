"""How often the final turn produced nothing, and which of the two causes it was.

Plan §12.4 asks for the rate to be measurable from the table before and after a fix. This
is that measurement. It reads `agent_runs` and the last `llm_calls` row of each run, and it
is deliberately runnable on data recorded long before any of this existed.

WHY THE CLASSIFICATION IS INFERRED, AND WHAT WOULD STOP IT BEING
-----------------------------------------------------------------
`finish_reason` is the exact discriminator and nothing stores it. For the runs already on
disk the only surviving signal is the last turn's `output_tokens`: a truncated turn stops
at exactly the per-turn cap, and a turn that stopped voluntarily is far below it. On every
run measured on 2026-08-30 the two signals agreed -- four runs at exactly 1200 with
`finish_reason='length'`, four at 13-20 with `finish_reason='stop'` -- so the inference is
sound on this data and is still an inference.

Migration `0004` adds `agent_runs.stop_reason`. `stop_reason_is_persisted()` checks for the
column at query time rather than assuming either state, so this reports honestly on both
sides of the migration without a code change -- the same move `observability.queries` makes
for `agent_tool_calls`, and for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.synthesis.verdict import FinalTurn

_HAS_STOP_REASON = """
    SELECT COUNT(*) > 0 AS present
      FROM information_schema.columns
     WHERE table_name = 'agent_runs' AND column_name = 'stop_reason'
"""

#: The last turn of each run, which is the one the executor treated as the answer.
_LAST_TURN = """
    SELECT DISTINCT ON (agent_run_id)
           agent_run_id, output_tokens, input_tokens, latency_ms
      FROM llm_calls
     WHERE agent_run_id IS NOT NULL
     ORDER BY agent_run_id, id DESC
"""

_CENSUS = f"""
    WITH last_turn AS ({_LAST_TURN})
    SELECT r.id,
           r.outcome,
           r.steps,
           r.tool_calls,
           r.latency_ms,
           r.question,
           t.output_tokens AS last_output_tokens
      FROM agent_runs r
      LEFT JOIN last_turn t ON t.agent_run_id = r.id
     WHERE r.outcome = 'answered'
       AND (r.answer IS NULL OR btrim(r.answer) = '')
     ORDER BY r.created_at
"""

_TOTALS = """
    SELECT COUNT(*)                                                       AS runs,
           COUNT(*) FILTER (WHERE outcome = 'answered')                   AS answered,
           COUNT(*) FILTER (WHERE outcome = 'answered'
                              AND (answer IS NULL OR btrim(answer) = '')) AS blank
      FROM agent_runs
"""


async def stop_reason_is_persisted(conn: AsyncConnection) -> bool:
    return bool((await conn.execute(text(_HAS_STOP_REASON))).scalar_one())


@dataclass(frozen=True)
class BlankRun:
    id: str
    question: str
    steps: int
    tool_calls: int
    latency_ms: int
    last_output_tokens: int | None

    def turn(self, max_output_tokens: int) -> FinalTurn:
        """The final turn as far as the database can reconstruct it.

        `reasoning_chars` is zero because it was never stored -- and that is the honest
        value, not a guess. `hit_the_cap` does not need it.
        """
        return FinalTurn(
            text=None,
            output_tokens=self.last_output_tokens or 0,
            max_output_tokens=max_output_tokens,
            stop_reason=None,
            reasoning_chars=0,
        )


@dataclass(frozen=True)
class Census:
    runs: int
    answered: int
    blank: int
    truncated: int
    stopped: int
    unmeasurable: int
    max_output_tokens: int
    inferred: bool

    @property
    def blank_rate(self) -> float | None:
        """Blank runs as a share of ANSWERED runs, not of all runs.

        M-68: 8 of 147 answered = 5.4%, against 10 of 213 all-outcomes = 4.7%. The two
        extra rows in the naive figure are a `max_steps` run and a `failed` run, blank for
        reasons that are not this bug. The correct denominator makes the bug bigger.
        """
        if not self.answered:
            return None
        return self.blank / self.answered

    @property
    def caveat(self) -> str | None:
        if not self.inferred:
            return None
        return (
            "The split between truncated and stopped is INFERRED from the last turn's "
            f"output_tokens against a cap of {self.max_output_tokens}, because "
            "agent_runs has no stop_reason column. Run migration 0004 to record the "
            "exact reason."
        )


async def blank_runs(conn: AsyncConnection) -> list[BlankRun]:
    rows = (await conn.execute(text(_CENSUS))).all()
    return [
        BlankRun(
            id=r.id,
            question=r.question,
            steps=r.steps,
            tool_calls=r.tool_calls,
            latency_ms=r.latency_ms,
            last_output_tokens=r.last_output_tokens,
        )
        for r in rows
    ]


async def census(conn: AsyncConnection, *, max_output_tokens: int) -> Census:
    totals = (await conn.execute(text(_TOTALS))).one()
    blanks = await blank_runs(conn)

    truncated = stopped = unmeasurable = 0
    for run in blanks:
        if run.last_output_tokens is None:
            # A blank run with no surviving llm_calls row. `_record_turn` swallows a
            # write failure so the run still answers, so this is a state that can really
            # occur -- and it is counted rather than folded into either cause.
            unmeasurable += 1
        elif run.turn(max_output_tokens).hit_the_cap:
            truncated += 1
        else:
            stopped += 1

    return Census(
        runs=totals.runs,
        answered=totals.answered,
        blank=totals.blank,
        truncated=truncated,
        stopped=stopped,
        unmeasurable=unmeasurable,
        max_output_tokens=max_output_tokens,
        inferred=not await stop_reason_is_persisted(conn),
    )
