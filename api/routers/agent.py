"""Multi-step question answering over tools.

Three copilot endpoints answer three different questions:

    GET  /search        which passages match this query
    POST /ask           what the documents say, with citations that were checked
    POST /agent/query   work it out, using whichever tools are needed

`/agent/query` earns its place on questions the other two cannot reach. "Of the areas
bordering Business Bay, which has the highest transaction volume?" is a spatial predicate
joined to an aggregate: it exists in no document at any k in any retrieval mode, and has
to be computed.

It also keeps numeric questions away from prose. Verification can prove an answer is
faithful to the corpus and cannot prove the corpus is right, so a false sentence written
into an indexed note produces a confident answer with every grounding check green.
Routing a count to `COUNT(*)` instead of to retrieved text is the mitigation, and the
routing fixture grades whether it holds.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import engine
from models.agent import AgentResponse
from services.agent import executor, settings, tools
from services.llm import registry
from services.llm.base import LLMError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent"])


class AgentRequest(BaseModel):
    q: str = Field(..., min_length=2, max_length=2000, description="The question.")
    provider: str | None = Field(
        None,
        pattern="^(local|anthropic)$",
        description="Override LLM_PROVIDER for this run, so the same question can go "
        "through either backend without restarting anything.",
    )
    max_steps: int | None = Field(
        None,
        ge=1,
        le=16,
        description="Cap on tool-calling turns. Defaults to AGENT_MAX_STEPS (8). "
        "Lowering it is the cheap way to see what a run does under pressure.",
    )


@router.post("/agent/query", response_model=AgentResponse)
async def agent_query(request: AgentRequest):
    """Answer a question by planning over tools, and report every step.

    **A refusal is a 200.** Some questions have no answer in this data -- there is no
    agency column and no forecast of any kind -- and reporting an honest abstention as a
    5xx makes the system look broken when it is behaving best, while putting the refusal
    rate out of reach of anything that reads status codes.

    `outcome` carries the distinction a status code cannot:

        answered   the model produced prose and tools backed it
        refused    it declined, correctly
        max_steps  the cap fired; the answer is PARTIAL and says so
        failed     the provider or the run budget stopped it

    The codes that ARE errors:

        503  the layer is disabled (LLM_PROVIDER=none), unconfigured, or unreachable
        502  the provider answered with something unusable
        504  the provider did not respond in time

    Latency here is seconds, not milliseconds: a local 20B takes 7-21 s per turn and a
    run is several turns. `timings_ms` splits generation from tool time so the two are
    never confused.
    """
    async with engine.connect() as conn:
        try:
            return await executor.run(
                conn,
                request.q,
                provider_name=request.provider,
                max_steps=request.max_steps,
            )
        except LLMError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _sse(name: str, payload: dict) -> bytes:
    """One Server-Sent Event frame.

    `event:`, then `data:`, then a BLANK LINE -- and the blank line is the whole protocol.
    A frame without it is buffered by the client forever and looks like a hung run.

    `json.dumps` emits no newlines, because a data field spanning lines needs every
    continuation prefixed with `data:`. The client handles that correctly; there is no
    reason to make it.
    """
    return f"event: {name}\ndata: {json.dumps(payload, default=str)}\n\n".encode()


@router.get("/agent/stream")
async def agent_stream(
    q: str = Query(..., min_length=2, max_length=2000),
    provider: str | None = Query(None, pattern="^(local|anthropic)$"),
    max_steps: int | None = Query(None, ge=1, le=16),
):
    """The same run as `POST /agent/query`, reported as it happens.

    **This exists because of a measurement.** A run on the local 20B is 7-21 seconds per
    turn and several turns, with a worst case of 66 seconds. The fix is not a faster
    model -- it is to stop the page being blank while it works.

    **GET, not POST**, with the question as a query parameter, because `EventSource` only
    issues GETs.

    **The event names and payload keys are the client's contract**, parsed and unit-tested
    in `frontend/src/lib/stream.ts`: `step`, `result`, `done`, `error`.

    **`done` is always sent**, including on failure. The client throws if the body closes
    without it, because a truncated stream and a finished run are otherwise identical.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def sink(name: str, payload: dict) -> None:
        await queue.put(_sse(name, payload))

    async def pump():
        # The run and the reader are separate tasks so a slow client cannot stall the
        # executor, and a slow executor cannot make the client think the stream died.
        async with engine.connect() as conn:
            try:
                result = await executor.run(
                    conn, q, provider_name=provider, max_steps=max_steps,
                    on_event=sink,
                )
                await queue.put(_sse("done", {
                    "run_id": result.run_id,
                    "outcome": result.outcome,
                    "answer": result.answer,
                    "categories": result.categories,
                    "grounding_warnings": result.grounding_warnings,
                    # The COMPLETE per-step record, identical to what POST /agent/query
                    # returns. Without it the streaming page has no trace to reveal and
                    # reports "no steps recorded" under a status list naming the step that
                    # just ran.
                    #
                    # It cannot be rebuilt from the `step` and `result` events: those carry
                    # the TOOL's duration, while a step's `latency_ms` is the model turn
                    # that chose it. Deriving one from the other puts a wrong number in the
                    # panel, which is worse than an absent one.
                    "steps": [s.model_dump() for s in result.steps],
                    "timings_ms": result.timings_ms.model_dump(),
                    "usage": {
                        "steps": result.usage.steps,
                        "tool_calls": result.usage.tool_calls,
                        "tool_errors": result.usage.tool_errors,
                        "cost_usd": result.usage.cost_usd,
                        "cost_priced": result.usage.cost_priced,
                    },
                }))
            except LLMError as exc:
                # A provider failure is an `error` event AND a `done`, not a 502: the
                # status line has already gone out, so there is no code left to change,
                # and a stream that stops without `done` cannot be told from a dropped
                # connection.
                logger.warning("stream run failed: %s", exc)
                await queue.put(_sse("error", {"message": str(exc)}))
                await queue.put(_sse("done", {
                    "run_id": None, "outcome": "failed", "answer": None,
                    "categories": [], "grounding_warnings": [str(exc)],
                    "timings_ms": {"generate": 0, "tools": 0, "total": 0},
                    "usage": {"steps": 0, "tool_calls": 0, "tool_errors": 0,
                              "cost_usd": None, "cost_priced": False},
                }))
            finally:
                await queue.put(None)

    async def body():
        task = asyncio.create_task(pump())
        try:
            while (frame := await queue.get()) is not None:
                yield frame
        finally:
            # A client that disconnects cancels this generator. The run itself is NOT
            # cancelled: it is most of a minute of real work and still has an `agent_runs`
            # row to write. The event sink already swallows the failed put.
            if not task.done():
                await task

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # nginx and friends buffer text/event-stream by default, turning a live
            # stream into one response delivered at the end -- the exact failure this
            # endpoint exists to prevent, and invisible when testing without a proxy.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agent/tools")
async def list_tools():
    """The tool catalogue, exactly as the model receives it.

    Returns the generated JSON Schema rather than a description of it. The schema is prompt
    content -- it is what the model reads when choosing a tool -- so reviewing a prose
    summary would mean reviewing a paraphrase of the thing that matters.
    """
    return {
        "provider": registry.configured_provider(),
        "enabled": registry.is_enabled(),
        "max_steps": settings.AGENT_MAX_STEPS,
        "max_cost_usd_per_run": settings.AGENT_MAX_COST_USD_PER_RUN,
        "total": len(tools.TOOLS),
        "tools": [
            {
                "name": tool.name,
                "category": tool.category,
                "description": tool.description,
                "parameters": tool.spec().parameters,
            }
            for tool in tools.TOOLS
        ],
    }


@router.get("/agent/runs")
async def list_runs(
    limit: int = Query(20, ge=1, le=200),
    outcome: str | None = Query(
        None, pattern="^(answered|refused|max_steps|failed)$"
    ),
):
    """Recent runs, plus aggregates over `agent_runs`.

    Routing accuracy, the refusal rate, how often the step cap fires, and how many numbers
    reached an answer without appearing in any tool result are all one GROUP BY over this
    table.

    `categories` is the routing evidence: a numeric question answered from `rag` alone got
    the right shape of answer from the wrong place.
    """
    where = "WHERE outcome = :outcome" if outcome else ""
    params = {"outcome": outcome} if outcome else {}

    async with engine.connect() as conn:
        try:
            summary = (
                await conn.execute(
                    text(f"""
                    SELECT COUNT(*)                                        AS runs,
                           COUNT(*) FILTER (WHERE outcome = 'answered')    AS answered,
                           COUNT(*) FILTER (WHERE outcome = 'refused')     AS refused,
                           COUNT(*) FILTER (WHERE outcome = 'max_steps')   AS hit_cap,
                           COUNT(*) FILTER (WHERE outcome = 'failed')      AS failed,
                           COALESCE(SUM(tool_calls), 0)                    AS tool_calls,
                           COALESCE(SUM(tool_errors), 0)                   AS tool_errors,
                           COALESCE(SUM(unverified_numbers), 0)            AS unverified_numbers,
                           COALESCE(SUM(total_cost_usd), 0)                AS total_cost_usd,
                           AVG(steps)                                      AS avg_steps,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms)  AS p50_ms,
                           PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY tool_ms)     AS tool_p50_ms
                      FROM agent_runs {where}
                """),
                    params,
                )
            ).one()

            recent = await conn.execute(
                text(f"""
                    SELECT id, created_at, provider, model, question, outcome, steps,
                           tool_calls, tool_errors, categories, total_cost_usd,
                           cost_priced, latency_ms, tool_ms, unverified_numbers
                      FROM agent_runs {where}
                     ORDER BY created_at DESC
                     LIMIT :limit
                """),
                {**params, "limit": limit},
            )
        except Exception as exc:
            # "Not migrated yet" is a configuration state with an exact remedy. Reporting
            # it as a 500 sends whoever hits it to read a traceback instead of running one
            # command.
            if "agent_runs" in str(exc):
                raise HTTPException(
                    status_code=503,
                    detail="agent_runs does not exist -- run `docker compose exec api "
                    "alembic upgrade head` (migration 0003).",
                ) from exc
            raise

    row = dict(summary._mapping)
    total = row["runs"] or 0
    row["refusal_rate"] = float(row["refused"]) / total if total else None
    row["cap_rate"] = float(row["hit_cap"]) / total if total else None
    row["tool_error_rate"] = (
        float(row["tool_errors"]) / row["tool_calls"] if row["tool_calls"] else None
    )
    return {
        "outcome_filter": outcome,
        "summary": row,
        "recent": [dict(r._mapping) for r in recent],
    }


# ── observability ───────────────────────────────────────────────────────────
#
# These handlers are thin on purpose. Every rate is defined once, in
# `services/observability/`, which has its own tests against the live table. A router that
# computed one would be a second place rates are defined, and the two would drift.


@router.get("/agent/runs/timeseries")
async def runs_timeseries(
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    hours: int = Query(24, ge=1, le=720, description="How far back to look."),
):
    """Rates over time, with the gaps left as gaps.

    A lifetime figure is the mean of a line that moves, and it can be true at no point in
    the period it covers: a refusal rate that doubles within a day barely shifts it. Rates
    per interval are what make that visible.

    An interval with no runs reports `null`, never `0%`. A percentile over fewer than 20
    runs also reports `null`, because `percentile_disc(0.95)` returns the maximum below
    that sample size, and publishing a maximum under the name p95 is the lie the floor
    exists to prevent.
    """
    from datetime import UTC, datetime, timedelta

    from services.observability import queries as obs

    until = datetime.now(UTC)
    since = until - timedelta(hours=hours)
    async with engine.connect() as conn:
        try:
            buckets = await obs.timeseries(conn, bucket=bucket, since=since, until=until)
        except obs.ObservabilityUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.remedy) from exc
    return {
        "bucket": bucket,
        "since": since,
        "until": until,
        "buckets": [
            {
                "start": b.start,
                "runs": b.runs,
                "answered": b.answered,
                "refused": b.refused,
                "failed": b.failed,
                "max_steps": b.max_steps,
                "answered_empty": b.answered_empty,
                "tool_calls": b.tool_calls,
                "tool_errors": b.tool_errors,
                "unverified_numbers": b.unverified_numbers,
                "refusal_rate": b.refusal_rate,
                "tool_error_rate": b.tool_error_rate,
                "empty_answer_rate": b.empty_answer_rate,
                "cap_rate": b.cap_rate,
                "failure_rate": b.failure_rate,
                "p50_ms": b.p50_ms,
                "p95_ms": b.p95_ms,
                "cost_usd": b.cost_usd,
                "cost_complete": b.cost_complete,
                "empty": b.empty,
            }
            for b in buckets
        ],
    }


@router.get("/agent/health")
async def agent_health(bucket: str = Query("hour", pattern="^(hour|day)$")):
    """The two most recent populated buckets, compared -- with the denominators.

    Every trend carries `current_n`, `previous_n` and `resolution`. A movement smaller than
    the coarser sample's own resolution reports `indistinguishable` rather than a
    direction, because at n=3 the finest change expressible is 33 points and any arrow
    drawn from it is noise given a name.
    """
    from services.observability import queries as obs

    async with engine.connect() as conn:
        try:
            snapshot = await obs.health(conn, bucket=bucket)
        except obs.ObservabilityUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.remedy) from exc

    def _bucket(b):
        if b is None:
            return None
        return {"start": b.start, "runs": b.runs, "refusal_rate": b.refusal_rate,
                "tool_error_rate": b.tool_error_rate, "p95_ms": b.p95_ms}

    return {
        "comparable": snapshot["comparable"],
        "reason": snapshot.get("reason"),
        "gap_buckets": snapshot.get("gap_buckets"),
        "current": _bucket(snapshot.get("current")),
        "previous": _bucket(snapshot.get("previous")),
        "trends": [
            {
                "metric": t.metric,
                "current": t.current,
                "previous": t.previous,
                "delta": t.delta,
                "direction": t.direction,
                "current_n": t.current_n,
                "previous_n": t.previous_n,
                "resolution": t.resolution,
                "conclusive": t.conclusive,
            }
            for t in snapshot.get("trends", [])
        ],
    }


@router.get("/agent/tools/stats")
async def tool_stats():
    """Which tool owns the failures -- or an honest statement that nothing can say yet.

    THREE STATES, and the middle one is why this is not just a GROUP BY. The table may be
    absent, or present and empty, or populated. "Exists and empty" is not "no errors", and
    the two render as the same empty chart unless something says which one it is.
    """
    from services.observability import queries as obs

    async with engine.connect() as conn:
        return await obs.tool_error_attribution(conn)


# THIS HANDLER MUST STAY BELOW `/agent/runs/timeseries`. FastAPI matches routes in
# declaration order, so a path parameter declared first would swallow the literal segment
# and answer `/agent/runs/timeseries` with a 404 for a run called "timeseries".
@router.get("/agent/runs/{run_id}")
async def run_detail(run_id: str):
    """One run, opened up: its model turns and the tools it actually called.

    The list page reports `6 tool calls (2 failed)` and cannot say which two. That number
    is an integer on `agent_runs`; the names behind it live in `agent_tool_calls`, and
    until this endpoint existed nothing read them back for a single run.

    A missing run is a 404 rather than an empty body -- an id that was mistyped and an id
    whose run made no tool calls are different states, and both would render as a blank
    panel.
    """
    from services.observability import queries as obs

    async with engine.connect() as conn:
        try:
            detail = await obs.run_detail(conn, run_id)
        except obs.ObservabilityUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.remedy) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no agent run with id {run_id}")
    return detail
