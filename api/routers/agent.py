"""Multi-step question answering over tools.

The three copilot endpoints answer three different questions and the separation is the
point:

    GET  /search        which passages match this query
    POST /ask           what do the documents say, with citations that were checked
    POST /agent/query   work it out, using whichever tools are needed

`/agent/query` earns its place on questions the other two cannot reach at all. "Of the
areas bordering Business Bay, which has the highest transaction volume?" is a spatial
predicate joined to an aggregate: it exists in no document at any k in any retrieval
mode, and it has to be computed. That question is R-11 in `eval/golden/routing.yaml` and
it is the gate for this milestone.

It also closes a hole m14 found and could not fix. A false sentence about transaction
volume, written into a public note, produced a high-confidence answer with every
grounding check green -- because the answer was faithful to a corpus that was wrong.
Verification cannot catch that. Routing the question to `COUNT(*)` instead of to prose
can, and `eval/golden/routing.yaml` grades whether it does.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
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
        description="Override LLM_PROVIDER for this run, so m16 can put the same "
        "routing set through both backends without restarting anything.",
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

    **A refusal is a 200**, exactly as with `/ask`, and for the same reason: some
    questions have no answer in this data -- there is no agency column, and no forecast
    of any kind -- and reporting an honest abstention as a 5xx makes the system look
    broken when it is behaving best, while making the refusal rate uncollectable from
    status codes.

    `outcome` carries the distinction a boolean cannot:

        answered   the model produced prose and tools backed it
        refused    it declined, correctly
        max_steps  the cap fired; the answer is PARTIAL and says so
        failed     the provider or the run budget stopped it

    The error codes that ARE errors:

        503  the layer is disabled (LLM_PROVIDER=none), unconfigured, or unreachable
        502  the provider answered with something unusable
        504  the provider did not respond in time

    Latency is measured in seconds, not milliseconds, and the response reports it per
    step. A local 20B answers one turn in 7-21 s depending on host load, and a run is
    several turns -- so a three-step run is a minute on a busy machine. That is a
    property of the model, not of this endpoint, and `timings_ms` splits generation from
    tool time so the two are never confused.
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


@router.get("/agent/tools")
async def list_tools():
    """The tool catalogue, exactly as the model receives it.

    Returns the generated JSON Schema rather than a description of it. The schema is
    prompt content -- it is what the model reads when deciding which tool to call -- so
    reviewing it as prose would be reviewing a paraphrase of the thing that matters.
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

    This is what makes the milestone's claims checkable instead of asserted. Routing
    accuracy, the refusal rate, how often the step cap fires and how many numbers reached
    an answer without appearing in any tool result are all one GROUP BY over this table --
    the same shape `/ask/costs` uses over `llm_calls`, and for the same reason.

    `categories` is the routing evidence: a run that answered R-01 with `rag` alone got
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
            # The table lives in migration 0003. "Not migrated yet" is a configuration
            # state with an exact remedy, and reporting it as a 500 sends whoever hits it
            # to read a traceback instead of running one command.
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
