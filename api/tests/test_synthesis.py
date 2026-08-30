"""The two causes of a blank answer, and the census that counts them.

Two halves, the same split as `test_observability.py` and `test_aggregates.py`. The pure
half pins the classification rules with no database. The live half runs the census over the
runs already recorded and asserts the split the provider-wrapping experiment measured.

Every number below was read out of Postgres, or off a wrapped provider, before it was
written down. The two shapes the rules are built around:

    finish_reason='length', out=1200 of 1200, reasoning=4906 chars, content=0
    finish_reason='stop',   out=14,           reasoning=0 chars,    content=0
"""

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from services.agent import settings
from services.synthesis.census import blank_runs, census, stop_reason_is_persisted
from services.synthesis.verdict import (
    TRUNCATION_REASONS,
    FinalTurn,
    Finding,
    assess,
    retry_would_help,
)

CAP = 1200


def truncated_turn(**over) -> FinalTurn:
    """The measured group-A shape: the whole budget spent thinking, none answering."""
    return FinalTurn(
        **{
            "text": "",
            "output_tokens": 1200,
            "max_output_tokens": CAP,
            "stop_reason": "length",
            "reasoning_chars": 4906,
            **over,
        }
    )


def stopped_turn(**over) -> FinalTurn:
    """The measured group-B shape: fourteen tokens and nothing anywhere."""
    return FinalTurn(
        **{
            "text": None,
            "output_tokens": 14,
            "max_output_tokens": CAP,
            "stop_reason": "stop",
            "reasoning_chars": 0,
            **over,
        }
    )


FINDINGS = (
    Finding(tool="dataset_overview", category="meta"),
    Finding(tool="list_areas", category="sql"),
    Finding(tool="area_price_history", category="sql"),
)


# ═══════════════════════════════════════════════════════════════════════════
# PURE HALF
# ═══════════════════════════════════════════════════════════════════════════

# ── the two causes are distinguished, and by the field that was being dropped


def test_a_truncated_final_turn_is_diagnosed_as_truncation():
    verdict = assess(truncated_turn(), findings=FINDINGS)
    assert verdict.diagnosis == "truncated_before_answering"
    assert verdict.recoverable is True
    assert "ran out of room" in verdict.answer


def test_a_voluntary_stop_is_diagnosed_as_a_stop():
    verdict = assess(stopped_turn(), findings=FINDINGS)
    assert verdict.diagnosis == "stopped_without_answering"
    assert "could not write the summary" in verdict.answer


def test_the_two_causes_do_not_share_wording():
    """They tell an operator to do different things, so they must not read the same."""
    a = assess(truncated_turn(), findings=FINDINGS)
    b = assess(stopped_turn(), findings=FINDINGS)
    assert a.answer != b.answer
    assert a.explanation != b.explanation
    assert a.remedy != b.remedy


@pytest.mark.parametrize("reason", sorted(TRUNCATION_REASONS))
def test_both_providers_truncation_words_are_recognised(reason):
    """Ollama says `length`, the Anthropic SDK says `max_tokens`. A rule that only holds
    on the provider you happened to test with fails on the first day of the other one."""
    turn = truncated_turn(stop_reason=reason, output_tokens=5)
    assert turn.hit_the_cap
    assert assess(turn).diagnosis == "truncated_before_answering"


def test_truncation_is_recognised_from_tokens_alone():
    """The census has nothing else: `finish_reason` is not stored, `output_tokens` is."""
    turn = truncated_turn(stop_reason=None)
    assert turn.hit_the_cap
    assert assess(turn).diagnosis == "truncated_before_answering"


def test_an_unknown_stop_reason_is_not_silently_called_truncation():
    turn = stopped_turn(stop_reason="content_filter")
    assert not turn.hit_the_cap
    assert assess(turn).diagnosis == "stopped_without_answering"
    assert "content_filter" in assess(turn).explanation


def test_a_turn_with_text_is_simply_the_answer():
    verdict = assess(FinalTurn(text="Al Wasl.", output_tokens=9, max_output_tokens=CAP))
    assert verdict.is_answer
    assert verdict.answer == "Al Wasl."


@pytest.mark.parametrize("blank", ["", "   ", "\n\t ", None])
def test_whitespace_is_not_an_answer(blank):
    """The recorded empty body is `null`, not `''` (M-47's own correction), and a body of
    spaces would render as a blank screen just the same."""
    assert not assess(stopped_turn(text=blank)).is_answer


def test_a_turn_that_asked_for_tools_is_not_a_final_turn():
    with pytest.raises(ValueError):
        assess(stopped_turn(tool_calls=2))


# ── rule 3: a retry only helps where the input changes ─────────────────────


def test_retrying_the_same_turn_at_temperature_zero_cannot_help():
    """Plan §12.4 offers 'retry the final synthesis turn'. At temperature 0 with an
    unchanged context the retry is the same call and returns the same empty message --
    30 more seconds to arrive back where it was."""
    assert retry_would_help(stopped_turn(), temperature=0.0) is False


def test_a_truncation_is_the_exception_because_the_retry_is_a_different_call():
    assert retry_would_help(truncated_turn(), temperature=0.0) is True


def test_sampling_makes_a_retry_worth_trying_again():
    assert retry_would_help(stopped_turn(), temperature=0.7) is True


def test_a_turn_that_answered_needs_no_retry():
    assert retry_would_help(FinalTurn("ok", 3, CAP), temperature=0.7) is False


# ── rule 4: the salvage message reports evidence, never a conclusion ────────


def test_the_salvage_message_names_the_tools_and_stops():
    answer = assess(stopped_turn(), findings=FINDINGS).answer
    assert "3 tool result(s)" in answer
    assert "area_price_history" in answer


def test_the_salvage_message_cannot_state_a_finding_of_its_own():
    """A function here that read the payloads and wrote 'Al Wasl grew fastest' would be
    inventing an answer the model never gave -- indistinguishable, in the response, from
    a real one. The structural guarantee is that the payloads never arrive: `Finding`
    carries a tool NAME and nothing a conclusion could be drawn from."""
    import inspect

    from services.synthesis.verdict import assess as assess_fn

    assert set(Finding.__dataclass_fields__) == {"tool", "category", "ok"}
    parameters = set(inspect.signature(assess_fn).parameters)
    assert parameters == {"turn", "findings", "temperature"}
    # And the turn carries the LENGTH of the reasoning, never the reasoning itself.
    assert "reasoning_chars" in FinalTurn.__dataclass_fields__
    assert "reasoning" not in FinalTurn.__dataclass_fields__


def test_failed_tools_are_not_counted_as_gathered_evidence():
    findings = (Finding("resolve_area_name", "meta", ok=False),)
    assert "No tool returned a usable result" in assess(stopped_turn(), findings=findings).answer


def test_a_run_with_no_tools_at_all_says_so_rather_than_claiming_nothing():
    assert "No tool returned a usable result" in assess(stopped_turn()).answer


# ── rule 1: the outcome label is not changed here ───────────────────────────


def test_the_verdict_carries_no_outcome_field():
    """A fifth `agent_runs` outcome would move these rows out of `answered`, and
    `observability.queries` counts `answered_empty` precisely to watch this population.
    Relabelling would zero that metric by moving rows rather than by fixing the bug."""
    verdict = assess(stopped_turn(), findings=FINDINGS)
    assert not hasattr(verdict, "outcome")
    assert verdict.answer is not None


# ═══════════════════════════════════════════════════════════════════════════
# LIVE HALF
# ═══════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def _live_conn():
    from config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            yield conn
    finally:
        await engine.dispose()


async def _skip_unless_runs(conn, minimum: int) -> None:
    n = (await conn.execute(text("SELECT COUNT(*) FROM agent_runs"))).scalar_one()
    if n < minimum:
        pytest.skip(f"agent_runs holds {n} rows, fewer than the {minimum} these assume")


async def test_the_census_reproduces_m47_from_the_recorded_runs():
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, 100)
        result = await census(
            conn, max_output_tokens=settings.AGENT_MAX_OUTPUT_TOKENS
        )
        assert result.blank > 0, "M-47 is supposed to be present in this data"
        assert result.blank_rate == result.blank / result.answered
        # The denominator that matters (M-68): answered runs, not all runs.
        assert result.answered < result.runs


async def test_the_blank_runs_split_into_two_causes_and_neither_is_empty():
    """The finding: it is not one bug. Both populations exist in the recorded data."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, 100)
        result = await census(
            conn, max_output_tokens=settings.AGENT_MAX_OUTPUT_TOKENS
        )
        assert result.truncated + result.stopped + result.unmeasurable == result.blank
        assert result.truncated > 0
        assert result.stopped > 0


async def test_the_truncated_runs_stopped_at_exactly_the_cap():
    """Not near it, at it. That is what makes the inference sound on old rows."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, 100)
        cap = settings.AGENT_MAX_OUTPUT_TOKENS
        runs = await blank_runs(conn)
        capped = [r for r in runs if r.last_output_tokens == cap]
        assert capped, "no truncated blank run in this data"
        for run in capped:
            assert run.turn(cap).hit_the_cap


async def test_the_stopped_runs_are_nowhere_near_the_cap():
    """13, 13, 13 and 20 tokens against a cap of 1200. There is no boundary case here,
    which is why a token-count inference is safe until 0004 is applied."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, 100)
        cap = settings.AGENT_MAX_OUTPUT_TOKENS
        runs = await blank_runs(conn)
        low = [
            r.last_output_tokens
            for r in runs
            if r.last_output_tokens is not None and r.last_output_tokens < cap
        ]
        assert low, "no voluntarily-stopped blank run in this data"
        assert max(low) < cap / 10


async def test_the_census_says_when_it_is_inferring():
    """`stop_reason` is checked at query time, so this reports honestly on both sides of
    migration 0004 without a code change -- the same move observability makes for
    agent_tool_calls."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, 1)
        persisted = await stop_reason_is_persisted(conn)
        result = await census(conn, max_output_tokens=CAP)
        assert result.inferred is not persisted
        if result.inferred:
            assert "migration 0004" in result.caveat
        else:
            assert result.caveat is None


async def test_every_blank_run_did_real_work_before_saying_nothing():
    """This is why it is the worst bug on the page rather than a curiosity: these runs
    are not failures that gave up early. They are the long, expensive, successful ones."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, 100)
        runs = await blank_runs(conn)
        assert runs
        for run in runs:
            assert run.tool_calls >= 1, run.id
            assert run.steps >= 2, run.id


def test_the_truncation_remedy_does_not_claim_a_fix_that_was_not_demonstrated():
    """Raising the cap is the obvious repair and it was tried. At 3,000 tokens the same
    question timed out mid-generation instead of answering, so the remedy names the lever
    and says what it cost -- rather than recommending a change nobody has seen work."""
    remedy = assess(truncated_turn()).remedy
    assert "3,000 tokens" in remedy
    assert "timed out" in remedy
