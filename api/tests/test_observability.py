"""The shaping rules, and then the same rules against the live table.

Two halves, and the split is the point. The pure half needs no database, no migration and
no runs on disk, so every honesty rule is pinned by a test that cannot be skipped. The live
half asserts that the real 213 recorded runs still behave the way the rules assume -- and
it is allowed to skip, because a machine with no agent runs has nothing to be wrong about.

What the live half is really for: this project has shipped a CI workflow that had never
run, a WebSocket documenting a frame it never sent, and a client sending `question` to an
endpoint expecting `q`. All three had passing tests around them. So the numbers below were
read out of Postgres before they were written down here.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from services.observability import queries
from services.observability.shaping import (
    Bucket,
    bucket_floor,
    bucket_span,
    fill_gaps,
    min_sample_for,
    rate,
    resolution_of,
    split_categories,
    suppress_thin_percentiles,
    trend,
)

H = timedelta(hours=1)


def at(hour: int, day: int = 29, month: int = 8) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


# ── rule 3: a percentile needs a sample ─────────────────────────────────────


def test_the_p95_floor_is_arithmetic_not_a_rule_of_thumb():
    """`percentile_disc(0.95)` is the maximum for every n below 20.

    Derived, not chosen: it returns the ceil(q*n)-th ordered value, which is the last one
    while ceil(0.95*n) == n. If this number is ever "tuned", the tuning has to argue with
    the definition of the function.
    """
    assert min_sample_for(0.95) == 20
    assert min_sample_for(0.5) == 2
    assert min_sample_for(0.99) == 100


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.5, 1.5])
def test_a_quantile_outside_the_open_unit_interval_is_refused(bad):
    with pytest.raises(ValueError):
        min_sample_for(bad)


def test_a_thin_bucket_reports_no_p95_at_all():
    """19 runs is one short, and one short means the number would be the maximum."""
    thin = Bucket(start=at(23), runs=19, p50_ms=13829, p95_ms=65949)
    assert suppress_thin_percentiles(thin).p95_ms is None
    assert suppress_thin_percentiles(thin).p50_ms == 13829


def test_at_twenty_runs_the_p95_is_reported():
    wide = Bucket(start=at(20), runs=20, p50_ms=7430, p95_ms=46603)
    assert suppress_thin_percentiles(wide).p95_ms == 46603


def test_a_single_run_reports_neither_percentile():
    one = Bucket(start=at(22), runs=1, p50_ms=2124, p95_ms=2124)
    shaped = suppress_thin_percentiles(one)
    assert shaped.p50_ms is None and shaped.p95_ms is None


# ── rule 2: a gap is a gap ──────────────────────────────────────────────────


def test_an_hour_with_no_runs_is_inserted_rather_than_skipped():
    """The live table has no runs at all in the 19:00 hour.

    Without this the chart joins 18:00 straight to 20:00 and the hour of silence becomes
    invisible -- which is the one shape an operator most needs to see.
    """
    measured = [Bucket(start=at(18), runs=32), Bucket(start=at(20), runs=87)]
    filled = fill_gaps(measured, bucket="hour", since=at(18), until=at(20))
    assert [b.start.hour for b in filled] == [18, 19, 20]
    assert filled[1].runs == 0


def test_an_inserted_bucket_reports_none_and_never_zero_percent():
    """Zero errors out of zero calls is not a zero error rate."""
    filled = fill_gaps(
        [Bucket(start=at(18), runs=32)], bucket="hour", since=at(18), until=at(20)
    )
    gap = filled[1]
    assert gap.empty
    assert gap.tool_error_rate is None
    assert gap.refusal_rate is None
    assert gap.empty_answer_rate is None
    assert gap.p95_ms is None


def test_gap_filling_covers_both_ends_of_the_requested_window():
    filled = fill_gaps([], bucket="hour", since=at(17), until=at(23))
    assert len(filled) == 7
    assert all(b.empty for b in filled)


def test_a_window_that_ends_before_it_starts_is_empty_not_reversed():
    assert fill_gaps([], bucket="hour", since=at(20), until=at(18)) == []


def test_day_buckets_step_by_a_day():
    filled = fill_gaps([], bucket="day", since=at(23, day=29), until=at(1, day=31))
    assert [b.start.day for b in filled] == [29, 30, 31]
    assert all(b.start.hour == 0 for b in filled)


def test_an_unknown_bucket_name_raises_instead_of_defaulting_to_hour():
    with pytest.raises(ValueError, match="unknown bucket"):
        bucket_span("fortnight")


def test_a_naive_timestamp_is_read_as_utc_because_that_is_what_the_column_stores():
    assert bucket_floor(datetime(2026, 8, 29, 20, 41, 3), "hour") == at(20)


# ── rule 5: a rate has a denominator, and the denominator is an argument ────


def test_the_empty_answer_rate_counts_only_runs_that_claim_to_have_answered():
    """The live shape: 147 answered, 8 of them blank, plus two blank for honest reasons.

    A max_steps run and a failed run have no answer because they did not finish. Folding
    them in gives 10/213 = 4.7% and understates the bug that actually exists; the bug is
    8/147 = 5.4%, and it is a bug about runs that reported success.
    """
    b = Bucket(
        start=at(17), runs=213, answered=147, refused=64, max_steps=1, failed=1,
        answered_empty=8,
    )
    assert b.empty_answer_rate == pytest.approx(8 / 147)
    assert b.empty_answer_rate != pytest.approx(10 / 213)


def test_the_tool_error_rate_is_over_calls_not_over_runs():
    b = Bucket(start=at(17), runs=213, tool_calls=301, tool_errors=31)
    assert b.tool_error_rate == pytest.approx(31 / 301)


def test_a_rate_with_nothing_in_the_denominator_is_none():
    assert rate(0, 0) is None
    assert rate(5, 0) is None
    assert rate(0, 5) == 0.0


def test_a_bucket_with_runs_but_no_tool_calls_has_no_tool_error_rate():
    """A run can refuse before calling anything. That is not a clean tool run."""
    assert Bucket(start=at(22), runs=2, refused=2).tool_error_rate is None


def test_a_partly_priced_bucket_is_not_reported_as_a_complete_total():
    assert Bucket(start=at(20), runs=87, cost_priced_runs=87).cost_complete is True
    assert Bucket(start=at(20), runs=87, cost_priced_runs=80).cost_complete is False
    assert Bucket(start=at(19), runs=0, cost_priced_runs=0).cost_complete is False


# ── M-63: one field, two shapes ─────────────────────────────────────────────


def test_a_joined_category_string_becomes_a_list_and_not_a_list_of_letters():
    """The trap: iterating the string gives ['m','e','t','a'] and never raises."""
    assert split_categories("meta,geo,sql") == ["meta", "geo", "sql"]
    assert split_categories("meta") == ["meta"]


def test_a_category_list_survives_unchanged():
    assert split_categories(["meta", "sql"]) == ["meta", "sql"]


def test_no_categories_is_an_empty_list_in_both_shapes():
    assert split_categories(None) == []
    assert split_categories("") == []
    assert split_categories(" , ") == []


# ── rule 1: a lifetime average is not a current state ───────────────────────


def test_a_trend_names_a_direction_only_when_both_sides_exist():
    assert trend("refusal_rate", 0.40, 0.184).direction == "up"
    assert trend("refusal_rate", 0.184, 0.40).direction == "down"
    assert trend("refusal_rate", 0.30, 0.30).direction == "flat"


def test_a_missing_side_makes_the_comparison_unknown_and_not_zero():
    t = trend("p95_ms", None, 38886.0)
    assert t.direction == "unknown"
    assert t.delta is None


def test_the_delta_is_the_difference_and_not_a_percentage_of_a_percentage():
    t = trend("refusal_rate", 0.40, 0.184)
    assert t.delta == pytest.approx(0.216)


def test_a_rate_over_two_runs_resolves_to_fifty_points_and_nothing_finer():
    assert resolution_of(2) == 0.5
    assert resolution_of(3) == pytest.approx(1 / 3)
    assert resolution_of(0) is None
    assert resolution_of(None) is None


def test_a_movement_smaller_than_its_own_denominator_is_indistinguishable():
    """The live trap, and the reason this rule exists.

    The two most recent hours in the table hold three runs and two runs. Compared naively
    they report the refusal rate rising 33 points, the empty-answer rate rising 100 and the
    step cap rate rising 33 -- four alarms from five runs. A rate over two runs moves in
    steps of 50 points; it cannot express a 33-point change, so a 33-point change read off
    it is an artefact of the denominator.
    """
    t = trend("refusal_rate", 1 / 3, 0.0, current_n=3, previous_n=2)
    assert t.direction == "indistinguishable"
    assert t.conclusive is False
    assert t.delta == pytest.approx(1 / 3), "the number is still real; the conclusion is not"
    assert t.resolution == 0.5


def test_two_identical_rates_over_a_sample_that_resolves_nothing_are_not_flat():
    """Found by this file's own live invariant on 2026-08-30, against its own author.

    `empty_answer_rate` came back 1.0 and 1.0 over one run and three, and `trend` reported
    `flat` -- which reads as "the empty-answer rate is stable at 100%". Zero is a movement
    of less than one step, and `flat` is a conclusion just as much as `up` is. The bug was
    the ORDER of two branches: exact equality was tested before the resolution check.
    """
    t = trend("empty_answer_rate", 1.0, 1.0, current_n=3, previous_n=1)
    assert t.direction == "indistinguishable"
    assert t.conclusive is False
    assert t.delta == 0.0, "the number is still real; the conclusion is not"


def test_equality_is_still_flat_when_no_denominator_was_offered():
    """p95 guards its own sample size, so a p95 that exists at all has 20 runs behind it.
    Where there is no resolution to compare against, two equal readings really are flat."""
    assert trend("p95_ms", 38886.0, 38886.0).direction == "flat"
    assert trend("p95_ms", 38886.0, 38886.0).conclusive is True


def test_the_same_movement_over_a_real_sample_is_a_direction():
    """18.4% to 40.0% over 49 and 40 runs. Resolution is 2.5 points; the move is 21.6."""
    t = trend("refusal_rate", 0.400, 0.184, current_n=40, previous_n=49)
    assert t.direction == "up"
    assert t.conclusive is True


def test_a_trend_with_no_denominators_reports_the_direction_as_measured():
    """p95 passes none, because it is already blank below 20 runs."""
    t = trend("p95_ms", 46603.0, 38886.0)
    assert t.direction == "up"
    assert t.resolution is None


def test_an_unknown_direction_is_not_conclusive_either():
    assert trend("cap_rate", None, 0.1, current_n=0, previous_n=10).conclusive is False


# ── the live table ──────────────────────────────────────────────────────────


@asynccontextmanager
async def _live_conn():
    """A connection on a pool that does not outlive the test.

    The module-level `database.engine` keeps pooled connections, and pytest-asyncio's auto
    mode gives each test its own event loop -- so the second live test in a file inherits a
    connection bound to the first test's loop and asyncpg raises "attached to a different
    loop". `NullPool` opens and closes per connection, which is the same fix
    test_eval_fixtures.py already applies for the same reason.
    """
    from config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            yield conn
    finally:
        await engine.dispose()


async def _skip_unless_runs(conn, minimum=1):
    try:
        edges = await queries.bounds(conn)
    except queries.ObservabilityUnavailable as exc:
        pytest.skip(exc.remedy)
    if (edges["runs"] or 0) < minimum:
        pytest.skip(f"agent_runs holds {edges['runs']} rows; need at least {minimum}")
    return edges


@pytest.mark.asyncio
async def test_the_live_series_is_contiguous_even_where_the_traffic_was_not():
    """Every hour between the first and last run gets a bucket, traffic or not."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn)
        series = await queries.timeseries(conn, bucket="hour")

    assert series, "the table has runs, so the series cannot be empty"
    starts = [b.start for b in series]
    assert starts == sorted(starts)
    for earlier, later in zip(starts, starts[1:]):
        assert later - earlier == H, "a contiguous series has no missing hour"


@pytest.mark.asyncio
async def test_every_thin_live_bucket_declines_to_state_a_p95():
    async with _live_conn() as conn:
        await _skip_unless_runs(conn)
        series = await queries.timeseries(conn, bucket="hour")

    for b in series:
        if b.runs < min_sample_for(0.95):
            assert b.p95_ms is None, f"{b.start} has {b.runs} runs and states a p95"


@pytest.mark.asyncio
async def test_the_hourly_refusal_rate_moves_and_the_lifetime_average_hides_it():
    """The claim that justifies this whole milestone, checked against the data.

    If the bucketed rates were flat, `/agent/runs`'s single lifetime figure would be an
    adequate answer and a panel would be decoration. They are not flat.
    """
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, minimum=50)
        series = await queries.timeseries(conn, bucket="hour")
        totals = await queries.lifetime(conn)

    rates = [b.refusal_rate for b in series if b.runs >= 20]
    if len(rates) < 2:
        pytest.skip("fewer than two buckets are wide enough to compare")

    lifetime_rate = totals["refused"] / totals["runs"]
    assert max(rates) - min(rates) > 0.05, (
        "hourly refusal rates are flat; a lifetime average would be honest enough"
    )
    assert min(rates) < lifetime_rate < max(rates), (
        "the lifetime average sits inside a range it never reports"
    )


@pytest.mark.asyncio
async def test_the_live_blank_answers_are_not_all_bugs():
    """Rule 5 against the table: the two denominators give different numbers."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn)
        totals = await queries.lifetime(conn)

    assert totals["blank_any_outcome"] >= totals["answered_empty"]
    if totals["blank_any_outcome"] == totals["answered_empty"]:
        pytest.skip("no unfinished run happens to be blank right now")
    naive = totals["blank_any_outcome"] / totals["runs"]
    honest = totals["answered_empty"] / totals["answered"]
    assert honest > naive, (
        "the correct denominator makes the bug bigger, not smaller; that is why it "
        "matters which one the panel shows"
    )


@pytest.mark.asyncio
async def test_the_tool_error_rate_cannot_name_a_tool_and_says_so():
    """The rate is real. The attribution is not available. Both are reported."""
    async with _live_conn() as conn:
        await _skip_unless_runs(conn)
        attribution = await queries.tool_error_attribution(conn)

    assert attribution["tool_calls"] > 0
    assert attribution["tool_error_rate"] is not None
    if attribution["attributable"]:
        assert attribution["by_tool"], "attributable with an empty breakdown is a lie"
        return
    assert attribution["by_tool"] == []
    assert "agent_tool_calls" in attribution["reason"]
    assert "0005" in attribution["remedy"]


@pytest.mark.asyncio
async def test_health_compares_two_buckets_and_counts_the_silence_between_them():
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, minimum=2)
        snapshot = await queries.health(conn, bucket="hour")

    if not snapshot["comparable"]:
        pytest.skip(snapshot["reason"])
    assert snapshot["current"].start > snapshot["previous"].start
    assert snapshot["gap_buckets"] >= 0
    assert {t.metric for t in snapshot["trends"]} == {
        "refusal_rate",
        "tool_error_rate",
        "empty_answer_rate",
        "cap_rate",
        "p95_ms",
    }
    for t in snapshot["trends"]:
        if t.conclusive and t.resolution is not None:
            assert abs(t.delta) >= t.resolution, (
                f"{t.metric} claims a direction from a movement its own sample "
                f"cannot resolve"
            )


@pytest.mark.asyncio
async def test_the_thin_tail_of_the_live_table_raises_no_conclusive_alarm():
    """The last two hours hold three runs and two. Nothing there is worth paging over.

    This is the assertion the naive implementation failed: it reported four movements as
    directions, three of them over a denominator of two.
    """
    async with _live_conn() as conn:
        await _skip_unless_runs(conn, minimum=2)
        snapshot = await queries.health(conn, bucket="hour")

    if not snapshot["comparable"]:
        pytest.skip(snapshot["reason"])
    if snapshot["current"].runs >= 20 and snapshot["previous"].runs >= 20:
        pytest.skip("both live buckets are wide enough for a conclusion to be fair")
    rate_trends = [t for t in snapshot["trends"] if t.resolution is not None]
    assert rate_trends, "rate trends carry their denominators"
    assert not all(t.conclusive for t in rate_trends), (
        "every rate over a handful of runs was reported as a direction"
    )


@pytest.mark.asyncio
async def test_a_run_drill_in_returns_model_turns_and_admits_they_are_not_tool_calls():
    async with _live_conn() as conn:
        edges = await _skip_unless_runs(conn)
        series = await queries.timeseries(conn, bucket="hour")
        assert series
        row = (
            await conn.execute(
                text("SELECT id FROM agent_runs ORDER BY created_at DESC LIMIT 1")
            )
        ).scalar_one()
        detail = await queries.run_detail(conn, row)

    assert detail is not None
    assert detail["run"]["id"] == row
    assert isinstance(detail["run"]["categories"], list)
    assert detail["model_turn_count"] == len(detail["model_turns"])
    if not detail["tool_steps_available"]:
        assert detail["tool_steps_note"]
    assert edges["runs"] >= 1


@pytest.mark.asyncio
async def test_an_unknown_run_id_is_none_and_not_an_empty_run():
    async with _live_conn() as conn:
        await _skip_unless_runs(conn)
        assert await queries.run_detail(conn, "no-such-run-id") is None
