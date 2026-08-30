"""The orchestration loop, driven by a scripted provider.

NO MODEL, NO NETWORK, NO DATABASE in most of this file. The loop's interesting behaviour
-- the step cap, the repeat guard, degrading to partial findings, the number and currency
checks -- are all properties of the executor and none of them needs a 20B model resident
to be pinned exactly. A scripted provider returns a prepared sequence of turns, so the
code under test is the real loop rather than an assertion about what a mock was told.

The one thing scripting cannot cover is whether a real model routes correctly. That is
`eval/golden/routing.yaml` and `scripts/run_routing_eval.py`, and it is a different kind
of claim: this file says the machinery is correct, the fixture says the choices are.
"""

import json

import pytest

from services.agent import executor
from services.llm.base import LLMResponse, ToolCall, Usage


class ScriptedProvider:
    """Returns prepared turns in order. Records what it was asked, so replay is testable."""

    name = "scripted"
    model = "scripted-model"

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = 0
        self.exchanges_seen = []

    async def complete_with_tools(self, *, system, user, tools, exchanges=(), max_tokens, effort="medium"):
        self.exchanges_seen.append(list(exchanges))
        self.calls += 1
        if not self._turns:
            raise AssertionError("the loop asked for more turns than were scripted")
        return self._turns.pop(0)


def turn(text=None, calls=(), latency=10):
    return LLMResponse(
        text=text or "",
        usage=Usage(input_tokens=100, output_tokens=20),
        provider="scripted",
        model="scripted-model",
        latency_ms=latency,
        stop_reason="tool_calls" if calls else "stop",
        tool_calls=tuple(calls),
    )


def call(name, **arguments):
    return ToolCall(id=f"c{abs(hash((name, str(arguments)))) % 9999}", name=name, arguments=arguments)


@pytest.fixture
def scripted(monkeypatch):
    """Install a scripted provider and neuter both accounting writes.

    The database is stubbed rather than mocked away entirely: `_record_turn` and
    `_finalise` are the two places the loop touches Postgres, and replacing exactly those
    keeps every other line of the executor real.
    """
    def _install(turns):
        provider = ScriptedProvider(turns)
        monkeypatch.setattr(executor.registry, "get_provider", lambda name=None: provider)

        async def _noop(*args, **kwargs):
            return None

        monkeypatch.setattr(executor, "_record_turn", _noop)
        monkeypatch.setattr(executor, "_finalise", _noop)
        return provider

    return _install


# ── number verification: the guard §4.4 asked for ───────────────────────────


def test_a_number_present_in_a_tool_result_is_not_flagged():
    payloads = [json.dumps({"areas": [{"area_name": "Business Bay", "transactions": 10669}]})]
    assert executor.verify_numbers("Business Bay recorded 10,669 transactions.", payloads) == []


def test_a_number_in_no_tool_result_is_flagged():
    payloads = [json.dumps({"transactions": 10669})]
    warnings = executor.verify_numbers("There were 99,999 transactions.", payloads)
    assert len(warnings) == 1
    assert "99,999" in warnings[0]


def test_separators_do_not_defeat_the_number_check():
    """"10,669" in prose and 10669 in a JSON payload are the same number.

    Without this the guard would fire on almost every correctly-grounded answer, and a
    guard that is usually wrong gets muted -- which m14 already paid for once, when the
    numeric check had a 30% false-positive rate on its first run.
    """
    assert executor.verify_numbers("10,669 sales", [json.dumps({"n": 10669})]) == []


def test_single_digits_are_not_chased():
    assert executor.verify_numbers("There are 4 neighbours.", ["{}"]) == []


# ── currency verification: from an observed failure, not a prediction ───────


def test_an_invented_currency_is_flagged():
    """The first probe of this layer produced exactly this, and it is the dangerous case.

    Given three AED medians the model returned a table headed "USD" with `$` on every
    figure. Every number was real and every one was wrong by the exchange rate. Nothing
    else in the pipeline catches it: the numbers verify and the arithmetic holds.
    """
    payloads = [json.dumps({"currency": "AED", "median_price": 14210.5})]
    warnings = executor.verify_currency("The median is $14,210.50 USD.", payloads)
    assert len(warnings) == 1
    assert "AED" in warnings[0]


def test_aed_alone_is_not_flagged():
    payloads = [json.dumps({"currency": "AED", "median_price": 14210.5})]
    assert executor.verify_currency("The median is 14,210.50 AED.", payloads) == []


def test_a_currency_the_tool_itself_mentioned_is_not_flagged():
    """If a tool result really does say USD, quoting it is not an invention."""
    payloads = [json.dumps({"currency": "USD", "value": 100})]
    assert executor.verify_currency("That is 100 USD.", payloads) == []


# ── refusal detection ───────────────────────────────────────────────────────


def test_a_refusal_is_recognised():
    assert executor._reads_as_refusal(
        "This platform does not contain any forecast of future prices."
    )


def test_an_answer_that_merely_mentions_a_limit_is_not_a_refusal():
    """The failure this pins: matching anywhere in the text called a real answer a refusal.

    An answer that answers and then notes a caveat is an answer. Getting this wrong
    corrupts the refusal rate, which is one of the few numbers this project claims.
    """
    assert not executor._reads_as_refusal(
        "Burj Khalifa has the highest volume at 11,390 transactions. There is no "
        "forecast available for future years."
    )


# ── the loop ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_turn_with_no_tool_calls_ends_the_run(scripted):
    provider = scripted([turn(text="Burj Khalifa, with 11,390 transactions.")])
    response = await executor.run(None, "which area is busiest?")
    assert response.outcome == "answered"
    assert response.answered is True
    assert provider.calls == 1
    assert response.usage.tool_calls == 0


@pytest.mark.asyncio
async def test_the_step_cap_returns_partial_findings_rather_than_raising(scripted, monkeypatch):
    """Hitting the cap is a labelled outcome, not an exception.

    IMPLEMENTATION-PLAN.md §5.3 says "hard cap at 8 tool calls; return partial findings
    labelled partial". A truncated run presented as a complete one is the failure the cap
    exists to make visible, so the label is the deliverable.
    """
    async def _always_ok(conn, name, arguments, run_id=None):
        return '{"ok": true}', False

    monkeypatch.setattr(executor.tools, "run", _always_ok)
    # Each turn asks for a DIFFERENT area, so the repeat guard does not fire first.
    provider = scripted([turn(calls=[call("area_summary", area_names=[f"A{i}"])]) for i in range(3)])
    response = await executor.run(None, "compare everything", max_steps=3)
    assert response.outcome == "max_steps"
    assert response.answered is False
    assert provider.calls == 3
    assert any("PARTIAL" in w for w in response.grounding_warnings)


@pytest.mark.asyncio
async def test_an_identical_tool_call_is_not_executed_twice(scripted, monkeypatch):
    """The structural half of "abstention has to survive orchestration".

    A prompt can ASK a model not to retry a refusal until it gets a different answer.
    Only the executor can guarantee it. The second identical call is answered from the
    first result with a note, and the tool never runs again -- which also terminates the
    commonest non-termination mode, a two-step cycle.
    """
    ran = []

    async def _counting(conn, name, arguments, run_id=None):
        ran.append((name, arguments))
        return '{"transactions": 1}', False

    monkeypatch.setattr(executor.tools, "run", _counting)
    same = call("area_summary", area_names=["Business Bay"])
    provider = scripted([
        turn(calls=[same]),
        turn(calls=[ToolCall(id="c2", name="area_summary", arguments={"area_names": ["Business Bay"]})]),
        turn(text="1 transaction."),
    ])
    response = await executor.run(None, "how many?")
    assert len(ran) == 1, "the identical second call should never reach the tool"
    repeated = [t for s in response.steps for t in s.tool_calls if t.repeated]
    assert len(repeated) == 1
    assert "already called" in repeated[0].result


@pytest.mark.asyncio
async def test_a_provider_failure_mid_run_keeps_the_completed_steps(scripted, monkeypatch):
    """The case that actually happened, on the very first end-to-end run.

    gpt-oss:20b emitted a structurally invalid tool call five steps in and Ollama
    answered HTTP 500. The first version of this loop re-raised and threw away an area
    resolution, a PostGIS adjacency query and three transaction counts. Work that
    succeeded is still worth returning.
    """
    async def _ok(conn, name, arguments, run_id=None):
        return '{"transactions": 11390}', False

    monkeypatch.setattr(executor.tools, "run", _ok)

    class FailsOnSecond(ScriptedProvider):
        async def complete_with_tools(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return turn(calls=[call("area_summary", area_names=["Burj Khalifa"])])
            raise executor.LLMError("Ollama returned 500: error parsing tool call", 502)

    provider = FailsOnSecond([])
    monkeypatch.setattr(executor.registry, "get_provider", lambda name=None: provider)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(executor, "_record_turn", _noop)
    monkeypatch.setattr(executor, "_finalise", _noop)

    response = await executor.run(None, "which is busiest?")
    assert response.outcome == "failed"
    assert len(response.steps) == 1, "the successful step must survive"
    assert response.usage.tool_calls == 1
    assert any("PARTIAL" in w for w in response.grounding_warnings)


@pytest.mark.asyncio
async def test_a_provider_failure_on_the_FIRST_turn_still_raises(scripted, monkeypatch):
    """Nothing succeeded, so there is nothing to salvage.

    Returning a 200 with an empty answer here would make an outage indistinguishable from
    a hard question, which is the failure the partial-findings path must not introduce.
    """
    class FailsImmediately(ScriptedProvider):
        async def complete_with_tools(self, **kwargs):
            raise executor.LLMError("cannot reach Ollama", 503)

    provider = FailsImmediately([])
    monkeypatch.setattr(executor.registry, "get_provider", lambda name=None: provider)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(executor, "_record_turn", _noop)
    monkeypatch.setattr(executor, "_finalise", _noop)

    with pytest.raises(executor.LLMError):
        await executor.run(None, "anything")


@pytest.mark.asyncio
async def test_parallel_tool_calls_in_one_turn_all_run_and_return_together(scripted, monkeypatch):
    """One turn, three tools, one Exchange.

    Splitting the results of one turn across several messages is legal on both backends
    and teaches the model to stop calling tools in parallel -- which costs an extra round
    trip, 7-21 s here, on every turn thereafter.
    """
    async def _ok(conn, name, arguments, run_id=None):
        return json.dumps({"tool": name}), False

    monkeypatch.setattr(executor.tools, "run", _ok)
    provider = scripted([
        turn(calls=[
            call("area_summary", area_names=["A"]),
            call("area_neighbors", area_name="A", predicate="touches"),
            call("corpus_stats"),
        ]),
        turn(text="done"),
    ])
    response = await executor.run(None, "compare")
    assert response.usage.tool_calls == 3
    assert response.steps[0].tool_calls[0].step == 1
    # All three results reached the model in a single exchange.
    replayed = provider.exchanges_seen[1]
    assert len(replayed) == 1
    assert len(replayed[0].results) == 3


@pytest.mark.asyncio
async def test_categories_record_the_route_actually_taken(scripted, monkeypatch):
    """`categories` is the routing evidence eval/golden/routing.yaml grades against."""
    async def _ok(conn, name, arguments, run_id=None):
        return "{}", False

    monkeypatch.setattr(executor.tools, "run", _ok)
    provider = scripted([
        turn(calls=[call("area_neighbors", area_name="A", predicate="touches")]),
        turn(calls=[call("area_summary", area_names=["A"])]),
        turn(text="done"),
    ])
    response = await executor.run(None, "which neighbour is busiest?")
    assert response.categories == ["geo", "sql"]
    assert "rag" not in response.categories


@pytest.mark.asyncio
async def test_a_failing_tool_does_not_end_the_run(scripted, monkeypatch):
    """A tool that declines is data for the model, not a fault in the system."""
    async def _fails(conn, name, arguments, run_id=None):
        return "No area matches 'Atlantis'. Closest: Palm Jumeirah", True

    monkeypatch.setattr(executor.tools, "run", _fails)
    provider = scripted([
        turn(calls=[call("area_summary", area_names=["Atlantis"])]),
        turn(text="There is no area named Atlantis in this dataset."),
    ])
    response = await executor.run(None, "how many sales in Atlantis?")
    assert response.usage.tool_errors == 1
    assert response.outcome == "refused"


def test_a_space_separated_thousands_group_is_not_two_numbers():
    """Found on the fourth eval run, and it is a false positive of the worst kind.

    The model wrote "AED 550 010" -- a space as the thousands separator -- and the number
    regex saw "550" and "010". Neither is in any tool result, so a correctly grounded
    figure was reported as unverifiable.
    """
    payloads = [json.dumps({"typical_annual_rent_per_property": 550010})]
    assert executor.verify_numbers("About AED 550 010 per year.", payloads) == []


def test_a_space_before_a_non_thousands_group_is_still_two_numbers():
    """The narrow rule earns its place. Collapsing every digit-space-digit would fuse
    "12 areas 34 rows" into 1234 and invent a number nobody wrote."""
    warnings = executor.verify_numbers("There are 12 areas and 34 rows.", ["{}"])
    assert len(warnings) == 2
