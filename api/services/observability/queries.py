"""The GROUP BY half. One statement per question, and no arithmetic that matters.

Every function here takes an open connection rather than opening its own. That is what lets
a caller run the timeseries and the attribution inside one transaction and get two answers
about the same instant, and it is also what keeps these testable against the live table
without a FastAPI dependency in the way.

No Prometheus, no OpenTelemetry, no metrics sidecar. The data is already in Postgres, the
question is a `date_trunc` and a `GROUP BY`, and a second service would need its own
storage, its own retention and its own reason to be trusted -- the same judgement that kept
the vector search in Postgres rather than in a vector database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from services.observability.shaping import (
    Bucket,
    Trend,
    bucket_span,
    fill_gaps,
    split_categories,
    suppress_thin_percentiles,
    trend,
)

MIGRATION_REMEDY = (
    "agent_runs does not exist -- run `docker compose exec api alembic upgrade head` "
    "(migration 0003)."
)

# The table migration 0005 adds. Nothing writes to it yet: the producer is the per-step
# accounting inside `services/agent/executor.py`. `tool_error_attribution` checks for it at
# query time rather than assuming either state, so the panel tells the truth on both sides
# of the migration without a code change.
TOOL_CALLS_TABLE = "agent_tool_calls"


class ObservabilityUnavailable(RuntimeError):
    """The tables this reads from are not migrated yet.

    Carries the exact command that fixes it. A missing migration is a configuration state
    with a one-line remedy, and answering it with a traceback sends the reader to the wrong
    place -- the same reasoning `/agent/runs` already applies.
    """

    def __init__(self, remedy: str = MIGRATION_REMEDY) -> None:
        super().__init__(remedy)
        self.remedy = remedy


_TIMESERIES = """
    SELECT date_trunc(:unit, created_at)                              AS start,
           COUNT(*)                                                   AS runs,
           COUNT(*) FILTER (WHERE outcome = 'answered')               AS answered,
           COUNT(*) FILTER (WHERE outcome = 'refused')                AS refused,
           COUNT(*) FILTER (WHERE outcome = 'max_steps')              AS max_steps,
           COUNT(*) FILTER (WHERE outcome = 'failed')                 AS failed,
           COUNT(*) FILTER (
               WHERE outcome = 'answered'
                 AND (answer IS NULL OR btrim(answer) = '')
           )                                                          AS answered_empty,
           COALESCE(SUM(tool_calls), 0)                               AS tool_calls,
           COALESCE(SUM(tool_errors), 0)                              AS tool_errors,
           COALESCE(SUM(unverified_numbers), 0)                       AS unverified_numbers,
           PERCENTILE_DISC(0.5)  WITHIN GROUP (ORDER BY latency_ms)   AS p50_ms,
           PERCENTILE_DISC(0.95) WITHIN GROUP (ORDER BY latency_ms)   AS p95_ms,
           SUM(total_cost_usd)                                        AS cost_usd,
           COUNT(*) FILTER (WHERE cost_priced)                        AS cost_priced_runs
      FROM agent_runs
     WHERE created_at >= :since
       AND created_at <  :until
     GROUP BY 1
     ORDER BY 1
"""

# PERCENTILE_DISC, not PERCENTILE_CONT. `/agent/runs` uses CONT, which interpolates between
# two neighbouring runs and returns a latency no run ever had. For a summary line that is
# harmless. For a panel someone compares against a single run's drill-in, "p95 = 38886.4ms"
# next to a list in which no run took 38886ms is a discrepancy that costs an afternoon.
# DISC returns a value that actually occurred.

_BOUNDS = """
    SELECT MIN(created_at) AS first_run, MAX(created_at) AS last_run, COUNT(*) AS runs
      FROM agent_runs
"""

_LIFETIME = """
    SELECT COUNT(*)                                              AS runs,
           COUNT(*) FILTER (WHERE outcome = 'answered')          AS answered,
           COUNT(*) FILTER (WHERE outcome = 'refused')           AS refused,
           COUNT(*) FILTER (WHERE outcome = 'max_steps')         AS max_steps,
           COUNT(*) FILTER (WHERE outcome = 'failed')            AS failed,
           COUNT(*) FILTER (
               WHERE outcome = 'answered'
                 AND (answer IS NULL OR btrim(answer) = '')
           )                                                     AS answered_empty,
           COUNT(*) FILTER (WHERE answer IS NULL OR btrim(answer) = '') AS blank_any_outcome,
           COALESCE(SUM(tool_calls), 0)                          AS tool_calls,
           COALESCE(SUM(tool_errors), 0)                         AS tool_errors,
           COALESCE(SUM(unverified_numbers), 0)                  AS unverified_numbers
      FROM agent_runs
"""

_RUN = """
    SELECT id, created_at, provider, model, question, answer, outcome, steps,
           tool_calls, tool_errors, categories, total_cost_usd, cost_priced,
           input_tokens, output_tokens, latency_ms, tool_ms, unverified_numbers
      FROM agent_runs
     WHERE id = :run_id
"""

_RUN_LLM_CALLS = """
    SELECT id, created_at, endpoint, provider, model, input_tokens, output_tokens,
           cost_usd, cost_priced, latency_ms, retrieve_ms, repair_attempts, answered,
           confidence, citations_total, citations_ok, grounding_warnings, request_id
      FROM llm_calls
     WHERE agent_run_id = :run_id
     ORDER BY created_at, id
"""

_HAS_TOOL_CALLS = "SELECT to_regclass(:qualified) IS NOT NULL AS present"

# Ordered by step, which is the order the loop made the calls and the order the evidence
# trace shows the user. `id` breaks a tie that cannot occur -- step is 1-based and unique
# per run -- and costs nothing to be certain about.
_RUN_TOOL_CALLS = """
    SELECT id, step, tool_name, category, arguments, ok, error, duration_ms, repeated,
           created_at
      FROM agent_tool_calls
     WHERE agent_run_id = :run_id
     ORDER BY step, id
"""


def _fail_if_unmigrated(exc: Exception) -> None:
    if "agent_runs" in str(exc):
        raise ObservabilityUnavailable() from exc


async def bounds(conn: Any) -> dict[str, Any]:
    """First run, last run, and how many there are. The window every default derives from.

    A panel that defaults to "the last 24 hours" against a table whose newest row is three
    days old draws an empty chart and looks broken. Defaulting to the data's own range says
    what is there.
    """
    try:
        row = (await conn.execute(text(_BOUNDS))).one()
    except SQLAlchemyError as exc:
        _fail_if_unmigrated(exc)
        raise
    return dict(row._mapping)


async def timeseries(
    conn: Any,
    *,
    bucket: str = "hour",
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[Bucket]:
    """Runs per interval, gap-filled, with percentiles suppressed where the sample is thin.

    Passing `since`/`until` as `None` uses the table's own range, so the caller gets every
    bucket that has ever existed rather than an arbitrary window. `until` is exclusive in
    the SQL and inclusive of its own bucket after gap filling, which is what includes the
    bucket currently in progress.
    """
    span = bucket_span(bucket)  # validates the name before it reaches the statement

    if since is None or until is None:
        edges = await bounds(conn)
        if not edges["runs"]:
            return []
        since = since or edges["first_run"]
        until = until or edges["last_run"]

    since = _as_utc(since)
    until = _as_utc(until)

    try:
        rows = await conn.execute(
            text(_TIMESERIES),
            # `until` is exclusive, so the last bucket would lose its own final row.
            # Widening by one span and letting `fill_gaps` floor it keeps the boundary
            # bucket whole without a second statement.
            {"unit": bucket, "since": since, "until": until + span},
        )
    except SQLAlchemyError as exc:
        _fail_if_unmigrated(exc)
        raise

    measured = [
        Bucket(
            start=r.start,
            runs=r.runs,
            answered=r.answered,
            refused=r.refused,
            max_steps=r.max_steps,
            failed=r.failed,
            answered_empty=r.answered_empty,
            tool_calls=r.tool_calls,
            tool_errors=r.tool_errors,
            unverified_numbers=r.unverified_numbers,
            p50_ms=r.p50_ms,
            p95_ms=r.p95_ms,
            cost_usd=float(r.cost_usd) if r.cost_usd is not None else None,
            cost_priced_runs=r.cost_priced_runs,
        )
        for r in rows
    ]
    filled = fill_gaps(measured, bucket=bucket, since=since, until=until)
    return [suppress_thin_percentiles(b) for b in filled]


async def lifetime(conn: Any) -> dict[str, Any]:
    """The aggregate over every run, kept for one purpose: to be shown BESIDE the trend.

    This is the number `/agent/runs` already returns, and on its own it is what makes that
    page a log. It is still worth having -- "30.0% of all runs were refused" is a true
    sentence -- but the panel is required to render it with the bucketed series beside it,
    because the series is the part that says whether that is still happening.
    """
    try:
        row = (await conn.execute(text(_LIFETIME))).one()
    except SQLAlchemyError as exc:
        _fail_if_unmigrated(exc)
        raise
    return dict(row._mapping)


async def health(conn: Any, *, bucket: str = "hour") -> dict[str, Any]:
    """The two most recent buckets that contain runs, and the movement between them.

    Deliberately NOT "the last bucket versus the lifetime average": comparing an hour
    against a mean that includes it is how a metric appears to improve simply by being
    measured for longer.

    Empty buckets between the two are skipped and then COUNTED, because "the last two hours
    with traffic were four hours apart" changes what the comparison means and there is no
    way for the renderer to know it otherwise.
    """
    series = await timeseries(conn, bucket=bucket)
    populated = [b for b in series if not b.empty]
    if len(populated) < 2:
        return {
            "bucket": bucket,
            "current": populated[-1] if populated else None,
            "previous": None,
            "gap_buckets": 0,
            "trends": [],
            "comparable": False,
            "reason": (
                "fewer than two buckets contain runs, so there is nothing to compare "
                "this one against"
            ),
        }

    current, previous = populated[-1], populated[-2]
    span = bucket_span(bucket)
    gap = int((current.start - previous.start) / span) - 1

    # Each rate is compared with the denominator it was computed over, so a movement
    # smaller than that denominator's own resolution comes back `indistinguishable`
    # rather than as an alarm. p95 passes no denominator on purpose: it is already blank
    # below 20 runs, so a p95 that exists at all has the sample behind it.
    trends: list[Trend] = [
        trend(
            "refusal_rate",
            current.refusal_rate,
            previous.refusal_rate,
            current_n=current.runs,
            previous_n=previous.runs,
        ),
        trend(
            "tool_error_rate",
            current.tool_error_rate,
            previous.tool_error_rate,
            current_n=current.tool_calls,
            previous_n=previous.tool_calls,
        ),
        trend(
            "empty_answer_rate",
            current.empty_answer_rate,
            previous.empty_answer_rate,
            current_n=current.answered,
            previous_n=previous.answered,
        ),
        trend(
            "cap_rate",
            current.cap_rate,
            previous.cap_rate,
            current_n=current.runs,
            previous_n=previous.runs,
        ),
        trend(
            "p95_ms",
            float(current.p95_ms) if current.p95_ms is not None else None,
            float(previous.p95_ms) if previous.p95_ms is not None else None,
        ),
    ]
    return {
        "bucket": bucket,
        "current": current,
        "previous": previous,
        "gap_buckets": gap,
        "trends": trends,
        "comparable": True,
        "reason": None,
    }


async def tool_error_attribution(conn: Any) -> dict[str, Any]:
    """The tool error rate, and an honest answer about which tool is responsible.

    `agent_runs` stores `tool_calls` and `tool_errors` as integers. The individual
    `ToolInvocation` records -- name, arguments, `ok`, `duration_ms` -- exist in the HTTP
    response and are discarded when the request ends. So the database can say that 10.3% of
    tool calls failed and cannot say whether that is one broken tool or nine flaky ones.

    Returning `attributable: False` with the reason and the remedy is the whole point. A
    per-tool chart built from a table that never received per-tool rows would render as
    "no errors", which is the same pixels as a healthy system.
    """
    try:
        totals = (
            await conn.execute(
                text(
                    "SELECT COALESCE(SUM(tool_calls), 0) AS calls, "
                    "COALESCE(SUM(tool_errors), 0) AS errors, COUNT(*) AS runs "
                    "FROM agent_runs"
                )
            )
        ).one()
        present = (
            await conn.execute(
                text(_HAS_TOOL_CALLS), {"qualified": f"public.{TOOL_CALLS_TABLE}"}
            )
        ).scalar_one()
    except SQLAlchemyError as exc:
        _fail_if_unmigrated(exc)
        raise

    calls, errors = totals.calls, totals.errors
    result: dict[str, Any] = {
        "runs": totals.runs,
        "tool_calls": calls,
        "tool_errors": errors,
        "tool_error_rate": (errors / calls) if calls else None,
        "attributable": False,
        "by_tool": [],
        "reason": (
            f"per-call records are not persisted: agent_runs stores tool_calls and "
            f"tool_errors as integers, and the {TOOL_CALLS_TABLE} table is not present. "
            f"The failing tool cannot be named from stored data."
        ),
        "remedy": (
            "migration 0005 adds agent_tool_calls; the producer is the per-step "
            "accounting in services/agent/executor.py. Attribution begins at that "
            "migration and is not backfilled -- there is no history to backfill from."
        ),
    }
    if not present:
        return result

    rows = await conn.execute(
        text(
            f"""
            SELECT tool_name, category,
                   COUNT(*)                              AS calls,
                   COUNT(*) FILTER (WHERE NOT ok)        AS errors,
                   PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
                   MIN(created_at)                       AS first_seen,
                   MAX(created_at)                       AS last_seen
              FROM {TOOL_CALLS_TABLE}
             GROUP BY 1, 2
             ORDER BY errors DESC, calls DESC
            """
        )
    )
    by_tool = [dict(r._mapping) for r in rows]
    if not by_tool:
        # The table exists and is empty. That is not "no errors" -- it is "no rows since
        # the migration", and the two must not render the same way.
        result["reason"] = (
            f"{TOOL_CALLS_TABLE} exists but has no rows yet. Attribution covers runs "
            f"recorded after migration 0005 only; earlier runs cannot be attributed "
            f"because the per-call records were never stored."
        )
        return result

    for row in by_tool:
        row["error_rate"] = (row["errors"] / row["calls"]) if row["calls"] else None
    result["attributable"] = True
    result["by_tool"] = by_tool
    result["reason"] = None
    result["remedy"] = None
    return result


async def run_detail(conn: Any, run_id: str) -> dict[str, Any] | None:
    """One run, its model turns and the tools it called. `None` when there is no such run.

    THE TWO LISTS ARE DIFFERENT THINGS AND THE FIELDS ARE NAMED TO SAY SO. `llm_calls`
    rows are MODEL TURNS -- one per trip to the provider. `agent_tool_calls` rows are TOOL
    CALLS -- one per tool the model asked for. A six-tool run has as many turns as the loop
    took, which is a different number, and reading one as the other is the mistake this
    drill-in exists to prevent.

    THREE STATES FOR THE TOOL STEPS, and the middle one is why this is not a LEFT JOIN.
    The table may be absent (`tool_steps_available` False); present with rows for this run;
    or present and empty for this run, which splits again -- a run that called no tools has
    nothing to show, while a run whose `tool_calls` count is non-zero and whose steps are
    missing ran BEFORE the producer existed. `tool_steps_recorded` distinguishes those two,
    because "no tools were called" and "the record was never kept" render as the same empty
    list and are opposite facts about the same run.
    """
    try:
        row = (await conn.execute(text(_RUN), {"run_id": run_id})).one_or_none()
    except SQLAlchemyError as exc:
        _fail_if_unmigrated(exc)
        raise
    if row is None:
        return None

    run = dict(row._mapping)
    run["categories"] = split_categories(run.get("categories"))
    if run.get("total_cost_usd") is not None:
        run["total_cost_usd"] = float(run["total_cost_usd"])

    turns = await conn.execute(text(_RUN_LLM_CALLS), {"run_id": run_id})
    model_turns = []
    for turn_row in turns:
        turn = dict(turn_row._mapping)
        if turn.get("cost_usd") is not None:
            turn["cost_usd"] = float(turn["cost_usd"])
        model_turns.append(turn)

    present = (
        await conn.execute(
            text(_HAS_TOOL_CALLS), {"qualified": f"public.{TOOL_CALLS_TABLE}"}
        )
    ).scalar_one()

    tool_steps: list[dict[str, Any]] = []
    if present:
        steps = await conn.execute(text(_RUN_TOOL_CALLS), {"run_id": run_id})
        tool_steps = [dict(step_row._mapping) for step_row in steps]

    # The run's own counter is the check on the drill-in. `agent_runs.tool_calls` was
    # written by the same loop that produced these rows, so a mismatch means the per-step
    # write failed -- and a panel that showed four steps under a run reporting six calls,
    # with nothing saying which number to believe, would be worse than showing neither.
    claimed = run.get("tool_calls") or 0
    recorded = bool(tool_steps) or (present and claimed == 0)

    return {
        "run": run,
        "model_turns": model_turns,
        "model_turn_count": len(model_turns),
        "tool_steps": tool_steps,
        "tool_step_count": len(tool_steps),
        "tool_steps_available": bool(present),
        "tool_steps_recorded": bool(recorded),
        "tool_steps_complete": bool(recorded) and len(tool_steps) == claimed,
        "tool_steps_note": _tool_steps_note(bool(present), tool_steps, claimed),
    }


def _tool_steps_note(present: bool, steps: list[dict[str, Any]], claimed: int) -> str | None:
    """The sentence that goes with an empty or short step list, or None when it agrees.

    Four states, and none of them is "no tools were called" unless the run says so.
    """
    if not present:
        return (
            f"{TOOL_CALLS_TABLE} does not exist -- run `alembic upgrade head` "
            "(migration 0005). This run reports tool_calls and tool_errors as counts only."
        )
    if not steps and claimed:
        return (
            f"This run made {claimed} tool call(s) and none were recorded. Attribution "
            "starts at migration 0005; a run from before it cannot be broken down, and "
            "there is nothing to backfill from."
        )
    if not steps:
        return "This run called no tools. The model answered, refused or capped without one."
    if len(steps) != claimed:
        return (
            f"{len(steps)} step(s) recorded against a run reporting {claimed} tool call(s). "
            "The per-step write is best-effort and does not fail a run, so the run's own "
            "counter is the one to trust."
        )
    return None


def _as_utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
