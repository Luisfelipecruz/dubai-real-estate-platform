"""The tool layer: what the agent can actually do, and how it is told to choose.

WHY NINE TOOLS AND NOT THIRTY-THREE
------------------------------------
The platform serves 33 REST operations. Exposing all of them would be the obvious move
and would be wrong twice. Every tool description is input tokens on EVERY turn of every
run, so thirty-three descriptions is a standing tax paid whether or not any of them is
used; and a model choosing between thirty-three near-identical options chooses badly.
Operations that differ only by filter parameters collapse into one tool that takes those
parameters.

Nine tools, in four categories. The category is not decoration -- `eval/golden/routing.yaml`
grades a question by which category answered it, so a numeric question served from prose
is a measurable failure rather than an impression.

WHERE ROUTING IS ACTUALLY ENFORCED
-----------------------------------
In the DESCRIPTIONS, not in the system prompt. The sentence "prefer this over retrieved
text for any number" sits on the tools that produce numbers, which is the moment the
model is deciding. A system prompt describing all nine tools at once is read before the
question is understood and competes with everything else in the prompt.

This matters more than style. m14 pushed three prompt injections through the public
`POST /notes` endpoint (M-20). Two were ignored. The third wrote a false sentence about
transaction volume as ordinary prose and the system answered from it with every grounding
check green -- because the answer was faithful to a corpus that was wrong. Verification
cannot catch that. Keeping the question away from prose in the first place can, and that
is what these descriptions are for.

THE ARGUMENTS ARE VALIDATED, NOT TRUSTED
-----------------------------------------
Each tool's parameters are a Pydantic model, and the JSON Schema handed to the provider
is generated from that same model by `strict_json_schema` -- the identical helper that
builds /ask's answer schema. Both backends constrain generation against it, and the model
is then re-validated on the way in. Constrained decoding makes bad arguments rare; it is
not a guarantee, and a tool that trusts its inputs because the schema was strict is one
`json.loads` away from a 500.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from services import market, retrieval
from services.llm.base import ToolSpec
from services.llm.schema import strict_json_schema

from . import settings

logger = logging.getLogger(__name__)

Category = Literal["sql", "rag", "geo", "meta"]


class ToolFailed(RuntimeError):
    """A tool could not answer. Carries text meant for the MODEL, not for a log.

    The message is the recovery path: it goes back as a `tool_result` with
    `is_error: true`, and it is the only thing the model has to work out what to do
    differently. "Unknown area 'Dubai Marina'. Did you mean: Marsa Dubai" is a message a
    model can act on. "KeyError" is not.
    """


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    category: Category
    arguments: type[BaseModel]
    handler: Callable[..., Awaitable[Any]]
    # Handlers that make their own LLM call need the run id so their cost lands on the
    # right run. Only `ask_documents` does. Without it those rows carried endpoint
    # "/agent/query" but a NULL agent_run_id -- correctly excluded from /ask's abstention
    # rate, and invisible to the run cost ceiling, which is the half that matters: an
    # agent calling ask_documents five times spends real money the budget cannot see.
    wants_run_id: bool = False

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=strict_json_schema(self.arguments),
        )


# ── argument models ─────────────────────────────────────────────────────────
#
# The field descriptions ship to the model inside the schema. They are prompt text, and
# they are written to be read by the thing filling them in.


class AreaArg(BaseModel):
    """A LIST, not a single name, and the reason is measured.

    The first version took one `area_name`. Asked "of the areas bordering Business Bay,
    which has the highest transaction volume?", the model called it once per neighbour --
    four separate turns for four areas, each a full round trip at 7-21 s. A six-neighbour
    area would have exceeded AGENT_MAX_STEPS before reaching an answer, and the run
    genuinely did die on turn 6 (see docs/agent-orchestration.md).

    Batching is the same principle the tool count already follows -- operations that
    differ only by a parameter collapse into one tool -- applied to the parameter itself.
    A tool that has to be called N times to answer one question is N-1 avoidable round
    trips, and on a local model a round trip is the dominant cost of the whole system.
    """

    area_names: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="One or more area names as recorded by the Dubai Land Department, "
        "e.g. ['Business Bay'] or ['Burj Khalifa', 'Al Wasl', 'Al Qouz First']. "
        "Case-insensitive. PASS THEM ALL AT ONCE when comparing areas -- do not call "
        "this tool repeatedly. If the user gave a popular name such as 'Dubai Marina' or "
        "'Downtown Dubai', call resolve_area_name FIRST: those are not DLD area names "
        "and match nothing here.",
    )


class HistoryArgs(BaseModel):
    area_name: str = Field(
        ...,
        description="DLD area name. Resolve popular names with resolve_area_name first.",
    )
    from_year: int = Field(
        2008,
        ge=1990,
        le=2100,
        description="First year to include, inclusive. Sale data begins in 1977 but is "
        "sparse before 2008.",
    )


class ResolveArgs(BaseModel):
    name: str = Field(
        ...,
        description="Any name a person might use for a Dubai district -- a DLD area "
        "name, a master-project name like 'Dubai Marina', or a misspelling.",
    )


class NeighborArgs(BaseModel):
    area_name: str = Field(..., description="DLD area name to find the neighbours of.")
    predicate: Literal["touches", "intersects", "overlaps"] = Field(
        "touches",
        description="touches = boundaries meet (use this for 'borders'); intersects = "
        "any shared point; overlaps = interiors intersect.",
    )


class ListAreasArgs(BaseModel):
    limit: int = Field(
        10, ge=1, le=50, description="How many areas to return, most active first."
    )
    order_by: Literal["transactions", "rents", "valuations"] = Field(
        "transactions", description="Which count to rank by."
    )


class SearchArgs(BaseModel):
    query: str = Field(
        ...,
        description="What to look for in the platform's design and methodology "
        "documents. A natural-language phrase works better than keywords.",
    )
    k: int = Field(5, ge=1, le=10, description="How many passages to return.")


class AskArgs(BaseModel):
    question: str = Field(
        ...,
        description="A question about how this platform works, why a decision was made, "
        "or what a measurement showed. Answered from the documents with verified "
        "citations, and it will refuse rather than guess when the documents do not "
        "cover it.",
    )


class NoArgs(BaseModel):
    """Deliberately empty, and it still gets a schema.

    A tool with no parameters still needs `{"type": "object", "properties": {},
    "additionalProperties": false}`. Omitting the schema entirely is accepted by one
    backend and rejected by the other.
    """


# ── handlers ────────────────────────────────────────────────────────────────


async def _resolve_area_name(conn: AsyncConnection, name: str) -> dict:
    match = await market.resolve_area_name(conn, name)
    if match.resolved is None:
        raise ToolFailed(
            f"No Dubai area matches {name!r}. The closest names that DO exist are: "
            f"{', '.join(match.candidates) or '(none)'}. Do not guess -- ask the user "
            f"which they meant, or say the area is not in this dataset."
        )
    return {
        "requested": match.requested,
        "resolved": match.resolved,
        "method": match.method,
        "confidence": match.confidence,
        "note": (
            f"{match.requested!r} is a master-project name, not a DLD area name. The "
            f"data files it under {match.resolved!r}. Use that name for every other "
            f"tool, and tell the user which name was used."
            if match.method == "project_alias"
            else f"matched by {match.method}"
        ),
    }


async def _area_summary(conn: AsyncConnection, area_names: list[str]) -> dict:
    """Counts for one or more areas, in one call.

    An area that does not resolve is reported IN the result rather than raising. With a
    batch, one bad name out of four must not cost the other three -- and a model told
    "that one is unknown, here are the other three" can finish the job, where one told
    only "error" starts over.
    """
    areas, unresolved = [], []
    for name in area_names:
        match = await market.resolve_area_name(conn, name)
        if match.resolved is None:
            unresolved.append({"requested": name, "candidates": match.candidates})
            continue
        summary = await market.area_summary(conn, match.resolved)
        areas.append(
            {
                "area_name": summary.area_name_en,
                "resolved_from": match.requested
                if match.method != "exact"
                else None,
                "transactions": summary.transactions.count,
                "avg_transaction_price": summary.transactions.avg_price,
                "rent_contracts": summary.rents.count,
                # THE FIELD NAME IS THE FIX. This used to be `avg_annual_rent`, and the
                # agent quoted it as a typical rent -- AED 550,010 for a Dubai Marina
                # apartment, against a true per-property median of AED 120,000. It is
                # the mean of a CONTRACT total, and one contract in that area covers 232
                # properties. A name that describes the column honestly is what stops a
                # reasonable reader from misreading it.
                "avg_contract_annual_amount": summary.rents.avg_price,
                "typical_annual_rent_per_property": await market.typical_annual_rent(
                    conn, match.resolved
                ),
                "valuations": summary.valuations.count,
            }
        )
    if not areas and unresolved:
        raise ToolFailed(
            "None of those names is a Dubai Land Department area. "
            + "; ".join(
                f"{u['requested']!r} -> closest existing names: "
                f"{', '.join(u['candidates']) or '(none)'}"
                for u in unresolved
            )
            + ". Do not guess -- say which names are not in this dataset."
        )
    return {
        "currency": "AED",
        "areas": areas,
        "unresolved": unresolved,
        "note": "Counts are exact COUNT(*) over indexed columns. "
        "`avg_transaction_price` is a MEAN and Dubai prices are heavily right-skewed -- "
        "one area carries a single 6.75 bn sale -- so use area_price_history for a "
        "typical sale price. "
        "FOR RENT, QUOTE `typical_annual_rent_per_property` AND NOTHING ELSE. "
        "`avg_contract_annual_amount` is the mean of a CONTRACT total, and one contract "
        "can cover hundreds of properties (232 in Marsa Dubai) each carrying the full "
        "portfolio amount on its own row. Quoting it as a rent overstates it several "
        "times over.",
    }


async def _area_price_history(
    conn: AsyncConnection, area_name: str, from_year: int = 2008
) -> dict:
    match = await market.require_area(conn, area_name)
    history = await market.area_history(conn, match.resolved, from_year)
    points = [
        {
            "year": p.period,
            "sales": p.sale_count,
            "median_price_sqm": p.median_price_sqm,
            "median_price": p.median_price,
            "rents": p.rent_count,
            "median_annual_rent": p.median_annual_rent,
            **({"partial_year": True} if p.is_partial else {}),
        }
        # Years with no activity at all are dropped rather than sent as nulls. They are
        # ~40% of the rows for a quiet area and they cost context on every later turn.
        for p in history.points
        if p.sale_count or p.rent_count
    ]
    return {
        "area_name": history.area_name_en,
        "resolved_from": match.requested if match.method != "exact" else None,
        "currency": "AED",
        "points": points,
        "rents_are_historical": history.rents_are_historical,
        "note": (
            "Prices are MEDIANS (PERCENTILE_CONT), not means. Rent is per PROPERTY: the "
            "raw contract amount covers all properties on the contract and using it "
            "produces gross yields above 200%."
            + (
                ""
                if history.rents_are_historical
                else " RENT COUNTS ARE NOT A TIME SERIES -- every contract in this "
                "extract was registered inside one window, so it is a snapshot of "
                "active contracts. Do not describe a rent trend over years."
            )
        ),
    }


async def _list_areas(
    conn: AsyncConnection, limit: int = 10, order_by: str = "transactions"
) -> dict:
    areas = await market.list_areas(conn)
    key = {
        "transactions": lambda a: a.transaction_count,
        "rents": lambda a: a.rent_count,
        "valuations": lambda a: a.valuation_count,
    }[order_by]
    top = sorted(areas, key=key, reverse=True)[:limit]
    return {
        "ordered_by": order_by,
        "total_areas": len(areas),
        "currency": "AED",
        "areas": [
            {
                "area_name": a.area_name_en,
                "transactions": a.transaction_count,
                "rents": a.rent_count,
                "valuations": a.valuation_count,
            }
            for a in top
        ],
    }


async def _area_neighbors(
    conn: AsyncConnection, area_name: str, predicate: str = "touches"
) -> dict:
    result, candidates = await market.community_neighbors_by_name(
        conn, area_name, predicate
    )
    if result is None:
        raise ToolFailed(
            f"No boundary polygon is named {area_name!r}. The boundary table uses its "
            f"own vocabulary, often transliterated from Arabic -- Palm Jumeirah is filed "
            f"as 'NAKHLAT JUMEIRA', for instance. The closest polygon names that DO "
            f"exist are: {', '.join(candidates) or '(none)'}. If one of those is clearly "
            f"the same place, call this tool again with that exact name. If none is, say "
            f"the boundary data does not cover this area -- only 106 of the 222 polygons "
            f"match a transaction area name -- and do not guess which areas border it."
        )
    if result.total == 0:
        # ZERO IS AN ANSWER, AND IT HAS TO SAY SO IN WORDS.
        #
        # Observed, not anticipated. Asked which communities border Palm Jumeirah, the
        # agent worked out that the polygon is filed as NAKHLAT JUMEIRA, called this tool
        # again with the right name, got a successful result -- and then told the user
        # the platform had no polygon for Palm Jumeirah. It had just used it. An empty
        # list read as a failure, so the model fell back on the previous turn's error.
        #
        # The distinction between "the query found nothing" and "the query could not run"
        # is obvious in a result object and invisible in an empty array. Spelling it out
        # is cheaper than any amount of prompt text about interpreting tool results, and
        # it is the same lesson as the truncation marker: a result must describe its own
        # shape, because whatever reads it cannot see the query that produced it.
        return {
            "area_name": result.community_name_en,
            "predicate": result.predicate,
            "total": 0,
            "neighbors": [],
            "note": "THE QUERY SUCCEEDED AND THE ANSWER IS NONE. This area's polygon "
            "shares a boundary with no other community. That is a real geographic fact, "
            "not a missing-data problem and not a tool failure -- it is what an "
            "artificial island, an enclave or a coastal parcel looks like. Report that "
            "it borders no other community.",
        }
    return {
        "area_name": result.community_name_en,
        "predicate": result.predicate,
        "total": result.total,
        "neighbors": [
            {"name": n.community_name_en, "shared_boundary_m": n.shared_boundary_m}
            for n in result.data
        ],
        "note": "Computed with PostGIS from the boundary polygons, not read from any "
        "document. Names are the polygon spellings and are upper-case; pass them to "
        "other tools as-is, the lookups are case-insensitive.",
    }


async def _search_documents(conn: AsyncConnection, query: str, k: int = 5) -> dict:
    chunks, _timings, _candidates, _relaxed = await retrieval.search(
        conn,
        query,
        mode="dense",
        top_k=20,
        limit=k,
        do_rerank=False,
    )
    return {
        "query": query,
        "passages": [
            {
                "chunk_id": c["id"],
                "source": c["source_id"],
                "heading": c.get("heading_path"),
                "text": c["content"][:1200],
            }
            for c in chunks
        ],
        "note": "These are retrieved passages, not verified answers. Any NUMBER in them "
        "is prose that was true when written -- for a current figure use a data tool. "
        "Use ask_documents instead if you want citations checked.",
    }


async def _ask_documents(
    conn: AsyncConnection, question: str, run_id: str | None = None
) -> dict:
    # Imported here rather than at module scope: services.ask pulls in the whole
    # generation layer, and services/agent/tools.py is imported by the router at startup
    # on machines where LLM_PROVIDER=none is a supported configuration.
    from services import ask as ask_service

    response = await ask_service.answer(
        conn, question, endpoint="/agent/query", agent_run_id=run_id
    )
    return {
        "question": question,
        "answered": response.answered,
        "answer": response.answer,
        "unanswerable_reason": response.unanswerable_reason,
        "confidence": response.confidence,
        "citations": [
            {
                "source": c.source_id,
                "quote": c.quote,
                "verified": c.resolved and c.quote_found,
            }
            for c in response.citations
        ],
        "grounding_warnings": response.grounding_warnings,
        "note": (
            "This sub-question was REFUSED because the documents do not answer it. That "
            "is a correct outcome. Do not answer it from your own knowledge and do not "
            "retry with a reworded question -- report that the documents do not cover it."
            if not response.answered
            else "Citations marked verified were checked against the stored source text."
        ),
    }


async def _corpus_stats(conn: AsyncConnection) -> dict:
    from sqlalchemy import text

    rows = await conn.execute(
        text("""
            SELECT source_type, COUNT(*) AS chunks, COUNT(DISTINCT source_id) AS sources
              FROM doc_chunks GROUP BY 1 ORDER BY 1
        """)
    )
    by_source = [
        {"source_type": r[0], "chunks": r[1], "sources": r[2]} for r in rows
    ]
    return {
        "total_chunks": sum(s["chunks"] for s in by_source),
        "by_source": by_source,
        "note": "This is the size of the SEARCH INDEX, not of the property data. It "
        "changes whenever the documentation changes -- the documents describing this "
        "system are themselves in the corpus -- so a figure quoted in a document may be "
        "out of date while this one is current.",
    }


async def _dataset_overview(conn: AsyncConnection) -> dict:
    return await market.dataset_overview(conn)


# ── the registry ────────────────────────────────────────────────────────────

TOOLS: tuple[Tool, ...] = (
    Tool(
        name="resolve_area_name",
        description=(
            "Turn any Dubai district name a person might use into the name the Land "
            "Department data actually contains. CALL THIS FIRST whenever the user names "
            "an area and you are not certain it is a DLD area name. 'Dubai Marina', "
            "'Downtown Dubai' and 'Jumeirah Lakes Towers' are master-project names and "
            "match NOTHING in the transaction table -- the data files them as 'Marsa "
            "Dubai', 'Burj Khalifa' and 'Al Thanyah Fifth'. Skipping this step returns a "
            "confident zero for the busiest area in the city."
        ),
        category="meta",
        arguments=ResolveArgs,
        handler=_resolve_area_name,
    ),
    Tool(
        name="area_summary",
        description=(
            "Exact transaction, rent and valuation counts and average prices for ONE OR "
            "MORE areas. Use this for ANY question about how many, how much in total, or "
            "how big -- the counts are COUNT(*) over an indexed column and are exact. "
            "PREFER THIS OVER RETRIEVED TEXT FOR ANY NUMBER: a figure quoted in a "
            "document was true when it was written, and a figure from here is true now. "
            "When comparing several areas, pass ALL their names in one call -- calling "
            "this once per area wastes a slow round trip each time and can exhaust the "
            "step budget before you reach an answer."
        ),
        category="sql",
        arguments=AreaArg,
        handler=_area_summary,
    ),
    Tool(
        name="area_price_history",
        description=(
            "Year-by-year MEDIAN sale price, median price per square metre, and sale "
            "counts for one area. Use this for anything about how prices moved, what a "
            "typical property costs, or trends over time. Medians, not averages -- one "
            "area carries a single 6.75 billion transaction and an average would report "
            "it as the market. PREFER THIS OVER RETRIEVED TEXT FOR ANY NUMBER. It "
            "reports history, NOT forecasts: it returns only what was RECORDED, and there "
            "is no projection of any kind in this platform. Call dataset_overview "
            "for the exact period the data covers rather than assuming one."
        ),
        category="sql",
        arguments=HistoryArgs,
        handler=_area_price_history,
    ),
    Tool(
        name="list_areas",
        description=(
            "Rank Dubai areas by how much activity they have -- transactions, rent "
            "contracts or valuations. Use this for 'which areas are busiest', 'where are "
            "most sales', or any question comparing areas across the whole city rather "
            "than asking about one."
        ),
        category="sql",
        arguments=ListAreasArgs,
        handler=_list_areas,
    ),
    Tool(
        name="area_neighbors",
        description=(
            "Which communities physically border a given area, computed from boundary "
            "polygons with PostGIS. Use this for anything about adjacency, bordering, "
            "surrounding or nearby districts. This is a geometric fact and cannot be "
            "answered from documents -- do not search for it."
        ),
        category="geo",
        arguments=NeighborArgs,
        handler=_area_neighbors,
    ),
    Tool(
        name="ask_documents",
        description=(
            "Ask the platform's own design and methodology documents a question and get "
            "an answer with citations that have been checked against the source text. "
            "Use this for HOW and WHY questions about the system: how data is "
            "deduplicated, why a column is transformed, what a measurement showed. It "
            "REFUSES when the documents do not answer -- treat a refusal as the answer, "
            "not as a reason to try again. Never use it for a current number about "
            "property data; use the data tools for those."
        ),
        category="rag",
        arguments=AskArgs,
        handler=_ask_documents,
        wants_run_id=True,
    ),
    Tool(
        name="search_documents",
        description=(
            "Retrieve raw passages from the design documents without synthesising an "
            "answer. Use this when you want to read the source yourself, or to combine "
            "documentation with figures from the data tools. For a straightforward "
            "question about how the platform works, ask_documents is better -- it checks "
            "its citations."
        ),
        category="rag",
        arguments=SearchArgs,
        handler=_search_documents,
    ),
    Tool(
        name="corpus_stats",
        description=(
            "How large the searchable document corpus is: chunk and document counts by "
            "source. Use this for questions about the SEARCH INDEX itself. Note this is "
            "not property data -- 'how many chunks' is about documents, 'how many "
            "transactions' is about real estate and belongs to area_summary."
        ),
        category="meta",
        arguments=NoArgs,
        handler=_corpus_stats,
    ),
    Tool(
        name="dataset_overview",
        description=(
            "What data exists at all: row counts per dataset, the date range covered, "
            "the property types available, and an explicit list of fields this platform "
            "does NOT have. Call this when a question might be unanswerable, so you can "
            "say what is missing instead of guessing."
        ),
        category="meta",
        arguments=NoArgs,
        handler=_dataset_overview,
    ),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def specs() -> list[ToolSpec]:
    return [tool.spec() for tool in TOOLS]


def truncate(payload: str, limit: int | None = None) -> tuple[str, bool]:
    """Cap a serialised tool result, and SAY SO inside the result when it is capped.

    A tool result is carried in the context of every subsequent turn, so an oversized one
    is not paid once -- it is paid on each remaining step. Truncating silently is worse
    than truncating: the model reasons over what looks like a complete list and states a
    maximum that was really the cut-off.
    """
    limit = limit or settings.AGENT_MAX_TOOL_RESULT_CHARS
    if len(payload) <= limit:
        return payload, False
    marker = (
        f"\n... TRUNCATED at {limit} characters. This result is INCOMPLETE -- do not "
        f"treat the last entry as the last one that exists."
    )
    # `max(0, ...)` rather than bare subtraction. The first version sliced with
    # `payload[: limit - len(marker)]`, and for any limit SHORTER than the marker that
    # index goes negative -- so `payload[:-10]` returned almost the whole string and the
    # "truncated" result came back six times longer than the cap. Harmless at the
    # production limit of 6,000 and completely wrong at 100, which is exactly the kind of
    # bug that survives until someone lowers a setting.
    keep = max(0, limit - len(marker))
    return (payload[:keep] + marker)[:limit] if keep else marker[:limit], True


async def run(
    conn: AsyncConnection,
    name: str,
    arguments: dict[str, Any],
    run_id: str | None = None,
) -> tuple[str, bool]:
    """Validate, dispatch, serialise. Returns (payload, is_error).

    NEVER RAISES for a tool-level failure, and that is the contract the executor depends
    on. Every outcome -- unknown tool, bad arguments, a handler that blew up -- comes back
    as a result the model can read, because a `tool_use` block with no matching result is
    a malformed request that fails the whole turn rather than the one tool. The step is
    still counted and still logged; it just is not fatal.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        return (
            f"No tool named {name!r}. Available tools: {', '.join(sorted(BY_NAME))}.",
            True,
        )

    try:
        parsed = tool.arguments.model_validate(arguments)
    except ValidationError as exc:
        return (
            f"Arguments for {name} were rejected: {exc.errors(include_url=False)}. "
            f"Send exactly the fields in the schema.",
            True,
        )

    extra = {"run_id": run_id} if tool.wants_run_id else {}
    try:
        result = await tool.handler(conn, **parsed.model_dump(), **extra)
    except ToolFailed as exc:
        # Expected, and written for the model. Not an error in the system.
        logger.info("tool %s declined: %s", name, exc)
        return str(exc), True
    except market.UnknownArea as exc:
        return str(exc), True
    except Exception as exc:
        # Unexpected. Logged with a traceback because it is a bug here, not a bad
        # question -- but still returned as a result so the run can continue or refuse.
        logger.error("tool %s raised", name, exc_info=True)
        return f"{type(exc).__name__} while running {name}: {exc}", True

    payload, _truncated = truncate(json.dumps(result, default=str))
    return payload, False
