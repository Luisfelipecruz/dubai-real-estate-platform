"""Grounded question answering over the document corpus.

`GET /search` returns chunks. `POST /ask` returns an answer, the evidence it rests on,
and an explicit account of which grounding checks held. The two are separate endpoints on
purpose: when an answer is wrong, the first question is always whether the retriever
found the wrong thing or the model ignored the right thing, and only separate endpoints
can tell you.

Three operations, and the second two exist because §4.5 requires cost and latency to be
observable rather than described:

    POST /ask            ask a question, get a checked answer or a refusal
    GET  /ask/providers  what is configured, and whether it is reachable
    GET  /ask/costs      aggregates over llm_calls -- cost, cache hit rate, abstention

WHAT THIS ENDPOINT WILL NOT DO
------------------------------
It will not answer questions about numbers, and neither will /search. "Median price per
m2 in Dubai Marina in 2024" is a PERCENTILE_CONT over an indexed column: exact, fast, and
already served by `GET /areas/{name}/history`. Routing it through a 384-dimensional
vector index and then through a language model can only make it wrong, and wrong
fluently. The routing table is in docs/rag-corpus-design.md.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import engine
from models.ask import AskResponse
from services import ask as ask_service
from services import retrieval
from services.llm import pricing, registry, settings
from services.llm.base import LLMError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    """POST rather than GET, and the reason is the question itself.

    A question can be long, can contain characters that need escaping, and ends up in
    access logs and browser history when it travels in a query string. /search takes a
    short keyword-ish query on GET; /ask takes a natural-language question in a body.
    """

    q: str = Field(..., min_length=2, max_length=2000, description="The question.")
    k: int | None = Field(
        None,
        ge=1,
        le=20,
        description="Contexts to retrieve. Defaults to 5, which is measured: dense "
        "recall@1 is 8/10 and recall@5 is 9/10 on the golden set.",
    )
    provider: str | None = Field(
        None,
        pattern="^(local|anthropic)$",
        description="Override LLM_PROVIDER for this request. Exists so m16 can run the "
        "same golden set through both backends without restarting anything.",
    )
    source_type: str | None = Field(
        None,
        pattern="^(doc|area_sheet|note)$",
        description="Restrict retrieval to one corpus source.",
    )
    effort: str = Field(
        "high",
        pattern="^(low|medium|high|xhigh|max)$",
        description="Anthropic only; the local provider has no equivalent knob and logs "
        "that it ignored this rather than pretending the two are interchangeable.",
    )


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest):
    """Answer a question from the corpus, or refuse.

    **A refusal is a 200.** `answered: false` with an `unanswerable_reason` is the
    correct outcome when the retrieved context does not support an answer, and two of the
    ten golden questions are exactly that case at every k in every retrieval mode.
    Reporting an honest abstention as a 5xx would make the system look broken precisely
    when it is behaving best, and would make the abstention rate -- which m16 measures --
    impossible to collect from status codes.

    The error codes that ARE errors:

        422  a guard refused before spending anything: prompt over the token ceiling,
             or worst-case cost over the per-request budget
        502  the provider answered and the answer was unusable (invalid JSON after the
             capped repair loop, or a truncated object)
        503  the layer is disabled (LLM_PROVIDER=none), unconfigured (no API key), or
             the provider is unreachable
        504  the provider did not respond in time

    On 502/503/504 the response body still carries the retrieved contexts. Retrieval
    already succeeded in ~67 ms and throwing that away because generation failed turns a
    partial outage into a total one.
    """
    async with engine.connect() as conn:
        try:
            return await ask_service.answer(
                conn,
                request.q,
                k=request.k,
                provider_name=request.provider,
                source_type=request.source_type,
                effort=request.effort,
            )
        except ask_service.GuardRefusal as exc:
            logger.info("guard %s refused a request: %s", exc.guard, exc)
            raise HTTPException(
                status_code=422, detail={"guard": exc.guard, "message": str(exc)}
            ) from exc
        except ask_service.GenerationFailed as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={
                    "message": str(exc),
                    "degraded_to": "retrieval",
                    "retrieval": exc.retrieval.model_dump(),
                    "contexts": [c.model_dump() for c in exc.contexts],
                },
            ) from exc
        except retrieval.RetrievalError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/ask/providers")
async def providers(
    probe: bool = Query(
        False,
        description="Actually call the provider with a trivial prompt. Costs a request; "
        "off by default so a health check is free.",
    ),
):
    """What the generation layer is configured to do, and optionally whether it can.

    `configured` is read from the environment and always available. `reachable` is null
    unless `probe=true`, because a health endpoint that spends money or wakes a 13 GB
    model every time a dashboard refreshes is one nobody leaves enabled.
    """
    configured = registry.configured_provider()
    result = {
        "configured": configured,
        "enabled": registry.is_enabled(),
        "supported": list(registry.SUPPORTED),
        "model": None,
        "reachable": None,
        "detail": None,
        "rate_table": None,
    }
    if not registry.is_enabled():
        result["detail"] = (
            "LLM_PROVIDER=none. /ask reports 503; /search and the platform's other "
            "operations are unaffected. This is a supported configuration."
        )
        return result

    try:
        provider = registry.get_provider()
    except LLMError as exc:
        result["detail"] = str(exc)
        result["reachable"] = False
        return result

    result["model"] = provider.model
    rate = pricing.rate_for(provider.model)
    if rate is not None:
        result["rate_table"] = {
            "input_per_mtok": rate.input,
            "output_per_mtok": rate.output,
            "cache_read_per_mtok": rate.cache_read,
            "cache_write_per_mtok": rate.cache_write,
            "source": rate.source,
        }

    if probe:
        try:
            response = await provider.complete(
                system="Reply with the single word: ok",
                user="ok",
                max_tokens=16,
                effort="low",
            )
            result["reachable"] = True
            result["detail"] = f"probe returned in {response.latency_ms} ms"
        except LLMError as exc:
            result["reachable"] = False
            result["detail"] = str(exc)
    return result


@router.get("/ask/costs")
async def costs(
    provider: str | None = Query(None, pattern="^(local|anthropic)$"),
    limit: int = Query(20, ge=1, le=200, description="Recent calls to list."),
):
    """Aggregates over llm_calls, plus the most recent calls.

    This is the endpoint that makes §4.5's claim checkable. Cost per question, cache hit
    rate, abstention rate and the p50/p95 latency split between retrieval and generation
    are all read off one table, and m16's provider comparison is this query with a
    GROUP BY.

    `estimated_vs_actual` is the ratio of the pre-call WordPiece estimate to the token
    count the provider reported. The input guard is denominated in the estimate, so this
    ratio is what says whether an 8,000-token ceiling means 8,000 tokens.
    """
    where = "WHERE provider = :provider" if provider else ""
    params = {"provider": provider} if provider else {}

    async with engine.connect() as conn:
        try:
            summary = (
                await conn.execute(
                    text(f"""
                    SELECT COUNT(*)                                     AS calls,
                           COALESCE(SUM(cost_usd), 0)                   AS total_cost_usd,
                           COUNT(*) FILTER (WHERE NOT cost_priced)      AS unpriced_calls,
                           COALESCE(SUM(input_tokens), 0)               AS input_tokens,
                           COALESCE(SUM(output_tokens), 0)              AS output_tokens,
                           COALESCE(SUM(cache_read_input_tokens), 0)    AS cache_read_tokens,
                           COUNT(*) FILTER (WHERE answered)             AS answered,
                           COUNT(*) FILTER (WHERE NOT answered)         AS refused,
                           COUNT(*) FILTER (WHERE grounding_warnings > 0) AS with_warnings,
                           COALESCE(SUM(repair_attempts), 0)            AS repair_attempts,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms)  AS generate_p50_ms,
                           PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS generate_p95_ms,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY retrieve_ms) AS retrieve_p50_ms,
                           CASE WHEN SUM(input_tokens) > 0
                                THEN ROUND(SUM(estimated_input_tokens)::numeric
                                           / SUM(input_tokens), 3)
                           END                                          AS estimated_vs_actual
                      FROM llm_calls {where}
                """),
                    params,
                )
            ).one()

            recent = await conn.execute(
                text(f"""
                    SELECT id, created_at, provider, model, endpoint, query,
                           input_tokens, output_tokens, cache_read_input_tokens,
                           estimated_input_tokens, cost_usd, cost_priced,
                           latency_ms, retrieve_ms, repair_attempts,
                           answered, confidence, citations_total, citations_ok,
                           grounding_warnings, request_id
                      FROM llm_calls {where}
                     ORDER BY id DESC
                     LIMIT :limit
                """),
                    {**params, "limit": limit},
                )
        except Exception as exc:
            # The table lives in migration 0002. "Not migrated yet" is a configuration
            # state with an exact remedy, and reporting it as a 500 sends whoever hits it
            # to read a traceback instead of running one command.
            if "llm_calls" in str(exc):
                raise HTTPException(
                    status_code=503,
                    detail="llm_calls does not exist -- run `docker compose exec api "
                    "alembic upgrade head` (migration 0002).",
                ) from exc
            raise

    summary_row = dict(summary._mapping)
    total = summary_row["calls"] or 0
    summary_row["cost_per_call_usd"] = (
        float(summary_row["total_cost_usd"]) / total if total else None
    )
    # Cached tokens over all input tokens the model was billed to read. Zero on a local
    # provider, which has no cache, and zero on Anthropic when the system prefix is
    # shorter than the minimum cacheable length -- two very different reasons for the
    # same number, which is why the provider is reported next to it.
    billed_input = (summary_row["input_tokens"] or 0) + (
        summary_row["cache_read_tokens"] or 0
    )
    summary_row["cache_hit_rate"] = (
        float(summary_row["cache_read_tokens"]) / billed_input if billed_input else None
    )
    summary_row["abstention_rate"] = (
        float(summary_row["refused"]) / total if total else None
    )

    return {
        "provider_filter": provider,
        "max_cost_usd_per_request": settings.LLM_MAX_COST_USD_PER_REQUEST,
        "max_input_tokens": settings.LLM_MAX_INPUT_TOKENS,
        "summary": summary_row,
        "recent": [dict(r._mapping) for r in recent],
    }
