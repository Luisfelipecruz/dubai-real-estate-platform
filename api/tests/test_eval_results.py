"""The evaluation endpoint's arithmetic, and then the same thing against the live table.

Two halves. The pure half needs no database and pins every rendering rule with tests that
cannot skip; the live half is allowed to skip, because a machine that has never run the
suite has nothing to be wrong about.

WHAT THESE TESTS ARE GUARDING
-----------------------------
Not "does the endpoint return JSON". The failure this can actually produce is a green score
describing a system that no longer exists -- a tool added after the run answers questions
the agent used to decline, every rate derived from them moves, and nothing in the stored
result says so. The staleness rules therefore get more tests than the happy path does, and
`not_measured` gets its own.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from services.evaluation import results

RECORDED = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

THRESHOLDS = {
    "available": True,
    "recorded": "2026-08-30",
    "floors": {
        "agent.answer_accuracy": 0.70,
        "agent.route_accuracy": 0.77,
        "retrieval.dense_mrr": 0.75,
    },
    "targets": {"agent.answer_accuracy": 0.90},
}


def row(**over):
    base = {
        "id": 1,
        "recorded_at": RECORDED,
        "suite": "all",
        "provider": "local",
        "duration_s": 1800,
        "gate_applied": True,
        "gate_passed": True,
        "metrics": {"agent": {"answer_accuracy": 0.80, "route_accuracy": 0.90}},
        "context": {"tools": ["area_summary", "dataset_aggregate"]},
    }
    return {**base, **over}


# ── the three states, which are the whole point ────────────────────────────


def test_a_floor_the_run_did_not_measure_is_not_a_pass_and_not_a_failure():
    """An agent-only run measures nothing under `retrieval.`.

    The endpoint must report that rather than picking whichever neighbour is more
    convenient. Rendering an unmeasured floor as
    passing publishes a green gate nobody ran; rendering it as failing makes a partial
    suite look like a broken system, and the fix people reach for is to stop looking.
    """
    got = results.assess(row(), THRESHOLDS, live_tools=["area_summary", "dataset_aggregate"])
    states = {c["key"]: c["state"] for c in got["floors"]}
    assert states["agent.answer_accuracy"] == "ok"
    assert states["agent.route_accuracy"] == "ok"
    assert states["retrieval.dense_mrr"] == "not_measured"
    assert got["summary"] == {"checked": 3, "ok": 2, "failing": 0, "not_measured": 1}


def test_a_value_below_its_floor_fails_and_carries_the_distance():
    got = results.assess(
        row(metrics={"agent": {"answer_accuracy": 0.62, "route_accuracy": 0.90}}),
        THRESHOLDS,
        live_tools=["area_summary", "dataset_aggregate"],
    )
    check = next(c for c in got["floors"] if c["key"] == "agent.answer_accuracy")
    assert check["state"] == "fail"
    # The margin is signed, so "how far under" is readable in a template without any
    # arithmetic being done there.
    assert check["margin"] == pytest.approx(-0.08)
    assert got["summary"]["failing"] == 1


def test_a_value_exactly_on_its_floor_passes():
    """`>=`, matching the harness. A gate that is exactly satisfied is a gate that passes.

    Whether a floor should ever be SET at the observed value is a separate question, argued
    in the thresholds file itself; it is not this comparison's business."""
    got = results.assess(
        row(metrics={"agent": {"answer_accuracy": 0.70}}), THRESHOLDS, live_tools=[]
    )
    assert next(c for c in got["floors"] if c["key"] == "agent.answer_accuracy")["state"] == "ok"


# ── staleness: the field a reader should reach before the score ────────────


def test_a_tool_registered_since_the_run_makes_the_score_stale_and_names_it():
    """Nine tools measured, ten registered -- and no other field in the record reveals it.

    The timestamp is the trap: a result a few days old sounds fresh, and says nothing about
    a tool layer that changed underneath it an hour after the run."""
    got = results.assess(
        row(context={"tools": ["area_summary"]}),
        THRESHOLDS,
        live_tools=["area_summary", "dataset_aggregate"],
    )
    assert got["registry"]["stale"] is True
    assert got["registry"]["added_since"] == ["dataset_aggregate"]
    assert got["registry"]["removed_since"] == []


def test_a_removed_tool_is_reported_as_removed_not_as_added():
    got = results.assess(
        row(context={"tools": ["area_summary", "gone"]}),
        THRESHOLDS,
        live_tools=["area_summary"],
    )
    assert got["registry"]["removed_since"] == ["gone"]
    assert got["registry"]["added_since"] == []
    assert got["registry"]["stale"] is True


def test_an_unchanged_registry_is_not_stale():
    got = results.assess(row(), THRESHOLDS, live_tools=["dataset_aggregate", "area_summary"])
    assert got["registry"]["stale"] is False
    assert got["registry"]["known"] is True


def test_an_unknown_registry_reports_unknown_rather_than_fresh():
    """`live_tools=None` means the agent layer is not installed; a result stored without a
    fingerprint has `tools: None`. Neither can support a claim about drift in either
    direction, and `stale: False` would be exactly such a claim."""
    assert results.assess(row(), THRESHOLDS, live_tools=None)["registry"]["known"] is False
    assert results.assess(row(), THRESHOLDS, live_tools=None)["registry"]["stale"] is None
    unknown = results.assess(row(context={}), THRESHOLDS, live_tools=["a"])
    assert unknown["registry"]["known"] is False


def test_an_empty_live_registry_is_not_treated_as_unknown():
    """An empty list is a real reading -- every tool removed -- and must not be silently
    upgraded to "cannot say". This is the case the router's `_live_tool_names` returns
    None for instead, so the two never collide; this asserts the distinction survives."""
    got = results.assess(row(), THRESHOLDS, live_tools=[])
    assert got["registry"]["known"] is True
    assert got["registry"]["removed_since"] == ["area_summary", "dataset_aggregate"]


# ── flattening: what may and may not be compared against a floor ───────────


def test_non_numeric_sections_never_reach_the_gate():
    """A run summary carries its graded responses alongside its rates. Comparing that list
    to a float raises; coercing it lies. It is skipped here, and stripped before the
    write."""
    flat = results._flatten(
        {"agent": {"answer_accuracy": 0.8, "notes": "fine"}, "_agent_results": [1, 2]}
    )
    assert flat == {"agent.answer_accuracy": 0.8}


def test_a_boolean_is_not_a_rate():
    """`True >= 0.77` is True in Python. A boolean silently satisfying a floor is a green
    gate produced by a type, so booleans are excluded rather than compared."""
    assert results._flatten({"agent": {"enabled": True, "route_accuracy": 0.9}}) == {
        "agent.route_accuracy": 0.9
    }


# ── the empty state, which is a 200 ────────────────────────────────────────


def test_nothing_recorded_yet_is_an_answer_and_still_lists_the_floors():
    """A fresh checkout has never run the suite. The page must still be able to show WHAT
    would be measured -- the floors and their arguments exist independently of any run."""
    got = results.assess(None, THRESHOLDS)
    assert got["available"] is False
    assert "make eval" in got["reason"]
    assert [c["state"] for c in got["floors"]] == ["not_measured"] * 3


def test_age_is_computed_against_an_injected_clock():
    got = results.assess(
        row(), THRESHOLDS, live_tools=[], now=RECORDED + timedelta(hours=6)
    )
    assert got["age_seconds"] == 6 * 3600


# ── the thresholds file, read from disk ────────────────────────────────────


def test_the_real_thresholds_file_parses_and_every_floor_is_a_number():
    loaded = results.load_thresholds()
    if not loaded["available"]:
        pytest.skip("eval/ is not mounted in this environment")
    assert loaded["floors"], "thresholds.yaml has no floors"
    for key, floor in loaded["floors"].items():
        assert isinstance(floor, (int, float)), key
        assert "." in key, f"{key} must be section.metric for the gate to partition it"


def test_every_floor_key_names_a_section_the_harness_can_produce():
    """A floor whose section no suite emits reports `not_measured` forever, which is
    indistinguishable on the page from a gate somebody switched off."""
    loaded = results.load_thresholds()
    if not loaded["available"]:
        pytest.skip("eval/ is not mounted in this environment")
    sections = {key.split(".", 1)[0] for key in loaded["floors"]}
    assert sections <= {"agent", "retrieval", "truths"}, sections


# ── live: the table, the round trip and the endpoint ───────────────────────


@pytest.mark.asyncio
async def test_record_then_read_back_the_latest():
    from config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            try:
                await conn.execute(text("SELECT 1 FROM eval_results LIMIT 1"))
            except Exception:
                pytest.skip("eval_results does not exist; run alembic upgrade head")

            marker = datetime.now(UTC) + timedelta(days=3650)  # far future: wins ORDER BY
            new_id = await results.record(
                conn,
                recorded_at=marker,
                suite="agent",
                provider="local",
                duration_s=42,
                gate_applied=True,
                gate_passed=False,
                metrics={"agent": {"answer_accuracy": 0.5}},
                context={"tools": ["a", "b"], "fixtures": {"answers": 41}},
            )
            got = await results.latest(conn)
            assert got is not None and got["id"] == new_id
            assert got["metrics"]["agent"]["answer_accuracy"] == 0.5
            assert got["context"]["fixtures"]["answers"] == 41
            assert got["gate_passed"] is False

            # Suite filtering, and then rolled back: this test must not leave a row that
            # a later `GET /evals/latest` would serve as the deployment's real score.
            assert (await results.latest(conn, suite="agent"))["id"] == new_id
            assert await results.latest(conn, suite="truths") != got
            await conn.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_endpoint_is_registered_and_answers(client):
    response = await client.get("/evals/latest")
    assert response.status_code == 200
    body = response.json()
    assert "floors" in body and "available" in body
    # Whether or not a run has been recorded, the floors are always enumerable.
    assert body["floors"], "the floors come from the file, not from a run"


@pytest.mark.asyncio
async def test_an_unknown_suite_is_rejected_rather_than_ignored(client):
    """A typo'd filter that silently returns the newest result of any suite would answer a
    question nobody asked, with a number that looks like the one they wanted."""
    assert (await client.get("/evals/latest?suite=nonsense")).status_code == 422


# ── the harness's own guard, tested where it can run without a model ───────


def _load_run_eval():
    """Match the directory that CONTAINS the module, not one with the right name.

    `api/scripts/` exists on the host as an empty artefact of the container's nested bind
    mount, so a lookup keyed on the directory name alone finds it first and imports
    nothing."""
    import sys
    from pathlib import Path as _Path

    scripts = next(
        (
            p
            for p in (_Path(__file__).resolve().parents[i] / "scripts" for i in (1, 2))
            if (p / "run_eval.py").is_file()
        ),
        None,
    )
    if scripts is None:  # pragma: no cover - neither layout present
        pytest.fail("scripts/run_eval.py not found in either layout.")
    sys.path.insert(0, str(scripts))
    import run_eval  # noqa: PLC0415

    return run_eval


def test_a_partial_run_refuses_to_become_the_published_score(monkeypatch):
    """Recording a single-question run stores a rate of 1.000 over a denominator of one.

    The refusal is the whole protection and it has to happen BEFORE the run: once the row
    exists, the denominator is a number in a database and no rendering can undo it. It
    also has to happen before any model call, which is why this test needs no database, no
    API and no model to assert it.
    """
    import sys

    run_eval = _load_run_eval()
    monkeypatch.setattr(
        sys, "argv",
        ["run_eval.py", "--suite", "agent", "--only", "A-01", "--record"],
    )
    with pytest.raises(SystemExit) as raised:
        run_eval.main()
    assert "REFUSING" in str(raised.value)


def test_the_registry_fingerprint_degrades_to_none_rather_than_empty(monkeypatch):
    """Returning `[]` for an unreachable API would make every recorded tool look REMOVED.
    It returns None instead, which the staleness check reports as "cannot say"."""
    run_eval = _load_run_eval()
    assert run_eval.registered_tools("http://127.0.0.1:1", timeout=1.0) is None
