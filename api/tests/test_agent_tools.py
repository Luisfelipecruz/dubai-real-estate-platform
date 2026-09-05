"""The tool layer: schemas, argument validation, and the promise that nothing escapes.

The contract `services/agent/executor.py` depends on is that `tools.run` NEVER raises.
A `tool_use` block with no matching result is a malformed request on both backends and
fails the whole turn rather than the one tool, so every outcome -- unknown tool, rejected
arguments, a handler that blew up -- has to come back as a readable result. Several tests
here exist only to hold that line.

The database-backed tests are marked and skipped when Postgres is absent, so the schema
and validation half of this file runs in a bare venv.
"""

import json

import pytest
from pydantic import BaseModel

from services.agent import tools
from services.llm.base import ToolSpec


# ── the catalogue ───────────────────────────────────────────────────────────


def test_every_tool_has_a_unique_name():
    names = [tool.name for tool in tools.TOOLS]
    assert len(names) == len(set(names))
    assert set(names) == set(tools.BY_NAME)


def test_every_tool_declares_a_category_the_routing_fixture_grades():
    """`eval/golden/routing.yaml` grades a run by the categories it used.

    A tool with a category outside this set would be invisible to that grading, which
    would make a routing failure look like a pass.
    """
    assert {tool.category for tool in tools.TOOLS} <= {"sql", "rag", "geo", "meta"}


def test_every_schema_is_strict():
    """Strict means every property required and no extras.

    Both backends constrain generation against this schema, so strictness is what turns
    argument validation from a defensive parse into a guarantee. A schema that allows
    additional properties lets a model invent a filter that is then silently ignored --
    the worst failure shape, because the answer looks like it honoured the filter.
    """
    for tool in tools.TOOLS:
        schema = tool.spec().parameters
        assert schema["type"] == "object", tool.name
        assert schema.get("additionalProperties") is False, tool.name
        assert set(schema.get("required", [])) == set(schema.get("properties", {})), tool.name


def test_a_tool_with_no_arguments_still_gets_an_object_schema():
    """Omitting the schema entirely is accepted by one backend and rejected by the other."""
    schema = tools.BY_NAME["corpus_stats"].spec().parameters
    assert schema["type"] == "object"
    assert schema["properties"] == {}


def test_specs_are_the_neutral_type_not_a_provider_dialect():
    specs = tools.specs()
    assert len(specs) == len(tools.TOOLS)
    assert all(isinstance(spec, ToolSpec) for spec in specs)


def test_the_numeric_tools_tell_the_model_to_prefer_them_over_prose():
    """Routing is enforced in the DESCRIPTIONS, so this asserts the descriptions.

    The injection finding is the reason: a false sentence about transaction
    volume, written into a public note, produced a fully-verified answer because the
    answer was faithful to a corpus that was wrong. Nothing downstream catches that. The
    sentence below is what keeps the question away from prose in the first place, and a
    refactor that quietly drops it would remove the mitigation while every test still
    passed.
    """
    for name in ("area_summary", "area_price_history"):
        assert "PREFER THIS OVER RETRIEVED TEXT" in tools.BY_NAME[name].description


def test_the_history_tool_denies_forecasting_in_its_description():
    """R-12 asks for a 2027 price. The refusal has to start here, not in the prompt."""
    assert "forecast" in tools.BY_NAME["area_price_history"].description.lower()


# ── argument validation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unknown_tool_returns_a_result_rather_than_raising():
    payload, is_error = await tools.run(None, "definitely_not_a_tool", {})
    assert is_error is True
    assert "No tool named" in payload
    # The available names are listed, because a model that guessed once will guess again
    # unless it is told what actually exists.
    assert "area_summary" in payload


@pytest.mark.asyncio
async def test_bad_arguments_come_back_as_a_readable_error():
    payload, is_error = await tools.run(None, "area_summary", {"wrong_field": 1})
    assert is_error is True
    assert "rejected" in payload


@pytest.mark.asyncio
async def test_a_handler_that_raises_is_reported_not_propagated():
    """The contract the executor depends on. A traceback here would fail the whole turn."""
    async def _explodes(conn, **kwargs):
        raise RuntimeError("boom")

    exploding = tools.Tool(
        name="explodes",
        description="x",
        category="meta",
        arguments=tools.NoArgs,
        handler=_explodes,
    )
    tools.BY_NAME["explodes"] = exploding
    try:
        payload, is_error = await tools.run(None, "explodes", {})
    finally:
        del tools.BY_NAME["explodes"]
    assert is_error is True
    assert "RuntimeError" in payload and "boom" in payload


@pytest.mark.asyncio
async def test_area_summary_requires_at_least_one_name():
    payload, is_error = await tools.run(None, "area_summary", {"area_names": []})
    assert is_error is True


@pytest.mark.asyncio
async def test_area_summary_caps_the_batch():
    """Ten is the ceiling. An unbounded list is an unbounded tool result, and a tool
    result is carried in the context of every later turn."""
    payload, is_error = await tools.run(
        None, "area_summary", {"area_names": [f"A{i}" for i in range(20)]}
    )
    assert is_error is True


# ── truncation ──────────────────────────────────────────────────────────────


def test_a_short_result_is_untouched():
    payload, was_cut = tools.truncate("small", limit=100)
    assert payload == "small" and was_cut is False


def test_a_long_result_is_cut_and_says_so():
    """Truncating silently is worse than truncating.

    A model reasoning over what looks like a complete list will state a maximum that was
    really the cut-off, and nothing downstream can tell.
    """
    payload, was_cut = tools.truncate("x" * 500, limit=100)
    assert was_cut is True
    assert len(payload) <= 100
    assert "TRUNCATED" in payload and "INCOMPLETE" in payload


# ── against the database ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_area_name_finds_the_master_project_alias(client):
    """'Dubai Marina' is not in the data. The DLD files it as 'Marsa Dubai'.

    The single most likely question this platform will ever be asked, and the naive path
    answers it with a confident zero and an HTTP 200.
    """
    response = await client.get("/areas/resolve", params={"name": "Dubai Marina"})
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] == "Marsa Dubai"
    assert body["method"] == "project_alias"


@pytest.mark.asyncio
async def test_resolve_area_name_handles_a_typo(client):
    response = await client.get("/areas/resolve", params={"name": "Bussiness Bay"})
    body = response.json()
    assert body["resolved"] == "Business Bay"
    assert body["method"] == "fuzzy"


@pytest.mark.asyncio
async def test_an_unresolvable_name_returns_candidates_rather_than_a_guess(client):
    """Below the fuzzy floor, `resolved` is null.

    Measured, not assumed: scored against all 221 area names, "Dubai Marina" ranks the
    CORRECT answer first at 0.37 and a wrong one second at 0.34. Any threshold that
    accepts the right one also accepts the wrong one, so nothing in that band is
    accepted at all. A tool that guesses an area name produces a confident answer about
    the wrong place, and nothing downstream can detect it.
    """
    response = await client.get("/areas/resolve", params={"name": "Zzzz Nowhere"})
    body = response.json()
    assert body["resolved"] is None
    assert body["method"] == "none"
    assert body["candidates"], "candidates are the recovery path; without them the model guesses"


@pytest.mark.asyncio
async def test_the_agent_tool_and_the_rest_endpoint_report_the_same_count(client):
    """The reason services/market.py exists, asserted rather than trusted.

    If the tool's count and the endpoint's count could differ, the platform would state
    two different exact numbers for one question -- and the entire argument for routing
    numeric questions to SQL instead of to prose would be worthless.
    """
    from database import engine

    endpoint = (await client.get("/areas/Business Bay/summary")).json()
    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            conn, "area_summary", {"area_names": ["Business Bay"]}
        )
    assert is_error is False
    tool_result = json.loads(payload)
    assert tool_result["areas"][0]["transactions"] == endpoint["transactions"]["count"]


@pytest.mark.asyncio
async def test_a_batch_survives_one_bad_name(client):
    """One unknown area out of several must not cost the others.

    A model told "that one is unknown, here are the other two" can finish the job. One
    told only "error" starts over, which costs a full round trip on a model that takes
    7-21 s per turn.
    """
    from database import engine

    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            conn,
            "area_summary",
            {"area_names": ["Business Bay", "Zzzz Nowhere", "Burj Khalifa"]},
        )
    assert is_error is False
    result = json.loads(payload)
    assert len(result["areas"]) == 2
    assert len(result["unresolved"]) == 1
    assert result["unresolved"][0]["requested"] == "Zzzz Nowhere"


@pytest.mark.asyncio
async def test_all_names_unknown_is_a_declined_tool_not_an_empty_success(client):
    """Returning an empty list would let the model report zero as a fact."""
    from database import engine

    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            None if False else conn, "area_summary", {"area_names": ["Zzzz Nowhere"]}
        )
    assert is_error is True
    assert "Do not guess" in payload


@pytest.mark.asyncio
async def test_neighbours_of_an_area_with_no_polygon_declines_clearly(client):
    """Only 106 of the 222 polygons match a transaction area name.

    An area can have transaction data and no boundary, so this is a frequent real outcome
    and the message has to say why rather than reading as a bug.
    """
    from database import engine

    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            conn, "area_neighbors", {"area_name": "Zzzz Nowhere", "predicate": "touches"}
        )
    assert is_error is True
    assert "106 of the 222" in payload


# ── The two routing defects found by auditioning natural questions (2026-08-30) ──


@pytest.mark.asyncio
async def test_borders_defaults_to_intersects_and_finds_marsa_dubai_neighbours(client):
    """The one-square-metre bug.

    Asked "Which areas border Dubai Marina?", the agent answered that it borders no other
    community. True under `ST_Touches` and false in every sense a reader cares about:
    Marsa Dubai OVERLAPS all four of its neighbours by 1.08, 0.20, 0.02 and 0.01 square
    metres -- surveyor slivers against a 9 km2 polygon -- which puts every one of them in
    the `overlaps` set and none in `touches`.
    """
    from database import engine

    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            conn, "area_neighbors", {"area_name": "Marsa Dubai"}
        )
    assert is_error is False
    # The default must be the complete predicate, not the strict one.
    assert '"predicate": "intersects"' in payload.replace("'", '"')
    assert "AL THANYAH FIFTH" in payload
    assert '"total": 0' not in payload.replace("'", '"')


@pytest.mark.asyncio
async def test_the_strict_predicate_is_still_reachable_by_name(client):
    """The DE-9IM distinction is real and the endpoint still teaches it. Changing the
    DEFAULT is not the same as removing the option, and this pins that."""
    from database import engine

    async with engine.connect() as conn:
        payload, _ = await tools.run(
            conn,
            "area_neighbors",
            {"area_name": "Marsa Dubai", "predicate": "touches"},
        )
    assert "THE QUERY SUCCEEDED AND THE ANSWER IS NONE" in payload


@pytest.mark.asyncio
async def test_a_per_area_breakdown_is_routed_to_list_areas_not_rejected(client):
    """Asked "Which areas had the most transactions in 2024?" the model sent
    breakdown_by="area_name" -- the correct instinct -- and the closed Literal answered
    "Input should be 'year' or 'property_type'", which names no alternative. The run gave
    up. A decline has to carry the recovery path."""
    from database import engine

    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            conn,
            "dataset_aggregate",
            {
                "dataset": "transactions",
                "metric": "count",
                "breakdown_by": "area_name",
                "year": 2024,
            },
        )
    # Not a schema rejection any more: the argument parses and the answer is a route.
    assert is_error is False
    assert "list_areas" in payload
    assert "Input should be" not in payload


@pytest.mark.asyncio
async def test_list_areas_ranks_within_one_year_when_asked(client):
    """The other half of that fix. Routing to `list_areas` is only correct if it can
    answer the question that was asked, and the question named a year -- without the
    filter it would rank 1977-2026 and the model would present it as 2024.

    Ground truth, straight from raw_transactions: 2024's busiest area is Al Barsha South
    Fourth with 2,478, ahead of Business Bay on 1,453.
    """
    from database import engine

    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            conn, "list_areas", {"year": 2024, "limit": 3}
        )
    assert is_error is False
    assert "Al Barsha South Fourth" in payload
    assert "2478" in payload
    # ...and it is genuinely a different ranking from the lifetime one, whose leader is
    # Marsa Dubai. A year argument that changed nothing would be worse than none.
    async with engine.connect() as conn:
        lifetime, _ = await tools.run(conn, "list_areas", {"limit": 3})
    assert "Marsa Dubai" in lifetime


@pytest.mark.asyncio
async def test_a_year_with_no_rows_is_refused_rather_than_ranked_as_zeroes(client):
    """The coverage rule, applied here: valuations cover a few months of 2026, so ranking areas
    by valuations in 2024 has a correct answer of 222 zeroes that reads as "nothing was
    valued anywhere in Dubai". It is also an arbitrary order, since every key is equal."""
    from database import engine

    async with engine.connect() as conn:
        payload, is_error = await tools.run(
            conn, "list_areas", {"year": 2024, "order_by": "valuations"}
        )
    assert is_error is False
    assert "refused" in payload
    assert "coverage gap" in payload
    assert "dataset_overview" in payload
