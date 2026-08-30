"""The five rules, and then the six blocked questions against their own golden SQL.

Two halves, the same split as `test_observability.py` and for the same reason. The pure
half pins every rule without a database, so none of them can be skipped. The live half
proves the thing the pure half cannot: that this module answers the six questions M-44
recorded as declined, with the value `eval/golden/answers.yaml` says is correct.

The live half does NOT assert a literal. It runs each question's own `ground_truth_sql` --
hand-written against the raw tables precisely so that an expected value never comes out of
the code under test -- and compares it to what `aggregates.aggregate` returns. A data
reload moves both together, which is the property `answers.yaml` was designed around.

This repository has shipped a CI workflow that never ran, a WebSocket documenting a frame
it never sent, and a client posting `question` to an endpoint expecting `q`. All three had
passing tests around them. So every number below was read out of Postgres first.
"""

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from services.aggregates import queries, tool
from services.aggregates.spec import (
    DATASETS,
    METRICS,
    MIN_ROWS_FOR_MEDIAN,
    Aggregate,
    AggregateRefused,
    Coverage,
    canonical_filter_value,
    caveats_for,
    dataset_spec,
    measure_for,
    min_rows_for_median,
    period_state,
    share,
    suppression_for,
    year_refusal,
)


def _golden(name: str) -> Path:
    """/app/eval in the container, <repo>/eval from a checkout. Both, deliberately."""
    for parents in (1, 2):
        candidate = Path(__file__).resolve().parents[parents] / "eval" / "golden" / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"eval/golden/{name} not found. Do not fix this by skipping.")


ANSWERS = {
    q["id"]: q
    for q in yaml.safe_load(_golden("answers.yaml").read_text(encoding="utf-8"))[
        "questions"
    ]
}


def coverage_of(
    *,
    dataset: str = "transactions",
    rows: int = 100,
    dated_rows: int | None = None,
    first: date | None = date(2020, 1, 1),
    last: date | None = date(2025, 12, 31),
    heaviest_year: int | None = 2025,
    heaviest_year_rows: int = 10,
    types: tuple[tuple[str, int], ...] = (("Unit", 60), ("Villa", 40)),
) -> Coverage:
    return Coverage(
        dataset=dataset,
        rows=rows,
        dated_rows=rows if dated_rows is None else dated_rows,
        first_date=first,
        last_date=last,
        heaviest_year=heaviest_year,
        heaviest_year_rows=heaviest_year_rows,
        property_types=types,
    )


# ═══════════════════════════════════════════════════════════════════════════
# PURE HALF — no database
# ═══════════════════════════════════════════════════════════════════════════

# ── rule 4: a median needs three rows, and three is arithmetic ──────────────


def test_the_median_floor_is_three_and_it_is_derived():
    """n=1 is an extreme, n=2 is the midrange, n=3 is the first genuine middle row.

    If this is ever "tuned", the tuning has to argue with what PERCENTILE_CONT does. The
    live half re-derives it from `raw_transactions`, where 1977 holds one sale and 1989
    holds two.
    """
    assert min_rows_for_median() == 3
    assert MIN_ROWS_FOR_MEDIAN == 3


@pytest.mark.parametrize("n", [1, 2])
def test_a_median_below_the_floor_is_suppressed_with_its_reason(n):
    reason = suppression_for("median", n)
    assert reason is not None
    assert str(MIN_ROWS_FOR_MEDIAN) in reason


def test_a_median_at_the_floor_is_reported():
    assert suppression_for("median", 3) is None


def test_zero_rows_suppresses_every_metric_including_count():
    """A count of zero over zero matched rows is the one zero that IS honest -- but it is
    still not a value, because the filters that produced it are the answer."""
    for metric in METRICS:
        assert suppression_for(metric, 0) == "no rows matched the filters"


def test_the_floor_applies_to_the_median_only():
    """A maximum over one row is that row, and that is exactly what a maximum means."""
    assert suppression_for("maximum", 1) is None
    assert suppression_for("count", 1) is None
    assert suppression_for("total", 2) is None


# ── rule 1: an unrecognised filter value is a refusal, never a zero ─────────


def test_an_unknown_property_type_is_refused_with_the_values_that_exist():
    with pytest.raises(AggregateRefused) as exc:
        canonical_filter_value(
            "Apartment",
            ("Unit", "Villa", "Land", "Building"),
            dimension="property_type_en",
            dataset="transactions",
        )
    message = str(exc.value)
    assert "Unit" in message and "Villa" in message
    assert "not a count of zero" in message


@pytest.mark.parametrize("spelling", ["villa", "VILLA", " Villa ", "vIlLa"])
def test_case_and_space_are_not_a_different_question(spelling):
    """'villa' resolves to 'Villa'. A spelling difference is not an unknown filter, and
    the canonical value is what gets bound as the parameter."""
    assert (
        canonical_filter_value(
            spelling,
            ("Unit", "Villa"),
            dimension="property_type_en",
            dataset="transactions",
        )
        == "Villa"
    )


def test_an_empty_universe_still_refuses_rather_than_matching():
    with pytest.raises(AggregateRefused):
        canonical_filter_value(
            "Unit", (), dimension="property_type_en", dataset="transactions"
        )


# ── rule 2 and 3: coverage decides whether a year is answerable ─────────────


def test_a_year_outside_coverage_is_outside_coverage_not_empty():
    assert period_state(2024, date(2026, 1, 2), date(2026, 8, 14)) == "outside_coverage"
    assert period_state(2027, date(2026, 1, 2), date(2026, 8, 14)) == "outside_coverage"


def test_a_year_the_data_stops_inside_is_partial():
    """Transactions end 2026-02-17. 2026 is seven weeks, not a year."""
    assert period_state(2026, date(1977, 4, 25), date(2026, 2, 17)) == "partial"


def test_the_first_year_is_partial_from_the_other_end():
    """Coverage begins 1977-04-25, so 1977 is missing a quarter of itself."""
    assert period_state(1977, date(1977, 4, 25), date(2026, 2, 17)) == "partial"


def test_a_fully_covered_year_is_complete():
    assert period_state(2025, date(1977, 4, 25), date(2026, 2, 17)) == "complete"


def test_a_dataset_with_no_dates_covers_no_year():
    assert period_state(2025, None, None) == "outside_coverage"


def test_the_year_refusal_names_the_span_it_does_cover():
    cov = coverage_of(
        dataset="valuations", first=date(2026, 1, 2), last=date(2026, 8, 14)
    )
    message = str(year_refusal(dataset_spec("valuations"), 2024, cov))
    assert "2026 only" in message
    assert "NOT a count of zero" in message


def test_the_year_refusal_names_a_range_when_there_is_one():
    cov = coverage_of(first=date(1977, 4, 25), last=date(2026, 2, 17))
    assert "1977 to 2026" in str(year_refusal(dataset_spec("transactions"), 1900, cov))


# ── rule 5: a result reports what it excluded ───────────────────────────────


def test_undated_rows_are_counted_and_named():
    cov = coverage_of(rows=200001, dated_rows=200000)
    assert cov.undated_rows == 1


def test_concentration_is_none_rather_than_zero_when_nothing_is_dated():
    """The same shape as `observability.shaping.rate`: no denominator, no rate."""
    assert coverage_of(rows=0, dated_rows=0, heaviest_year_rows=0).concentration is None
    assert share(3, 0) is None
    assert share(0, 3) == 0.0


def test_a_dataset_concentrated_in_one_year_is_a_snapshot():
    snapshot = coverage_of(rows=358008, heaviest_year_rows=320400)
    assert snapshot.is_snapshot
    assert snapshot.concentration == pytest.approx(0.895, abs=0.001)
    assert not coverage_of(rows=200000, heaviest_year_rows=32065).is_snapshot


def test_a_snapshot_says_so_beside_a_per_year_figure():
    notes = caveats_for(
        spec=dataset_spec("rent_contracts"),
        metric="count",
        measure=None,
        rows_matched=979,
        rows_excluded_by_measure=0,
        period="complete",
        year=2023,
        coverage=coverage_of(
            dataset="rent_contracts",
            rows=358008,
            heaviest_year=2026,
            heaviest_year_rows=320400,
        ),
    )
    joined = " ".join(notes)
    assert "snapshot, not a history" in joined
    assert "89.5%" in joined
    assert "2023 holds 0.27%" in joined


def test_a_partial_period_says_it_is_not_comparable():
    notes = caveats_for(
        spec=dataset_spec("transactions"),
        metric="count",
        measure=None,
        rows_matched=4223,
        rows_excluded_by_measure=0,
        period="partial",
        year=2026,
        coverage=coverage_of(
            rows=200001,
            dated_rows=200000,
            first=date(1977, 4, 25),
            last=date(2026, 2, 17),
            heaviest_year_rows=32065,
        ),
    )
    joined = " ".join(notes)
    assert "only PARTLY covered" in joined
    assert "not comparable with a full year" in joined
    # And the row that is in COUNT(*) and in no year.
    assert "1 row(s) in transactions have no instance_date" in joined


def test_excluded_rows_are_reported_not_swallowed():
    spec = dataset_spec("transactions")
    notes = caveats_for(
        spec=spec,
        metric="median",
        measure=spec.measures["price_per_sqm"],
        rows_matched=200001,
        rows_excluded_by_measure=2,
        period=None,
        year=None,
        coverage=coverage_of(rows=200001, dated_rows=200000),
    )
    assert any("2 row(s) were excluded" in n for n in notes)


def test_an_extreme_says_it_is_one_row():
    spec = dataset_spec("transactions")
    notes = caveats_for(
        spec=spec,
        metric="maximum",
        measure=spec.measures["sale_price"],
        rows_matched=200001,
        rows_excluded_by_measure=0,
        period=None,
        year=None,
        coverage=coverage_of(rows=200001, dated_rows=200000),
    )
    assert any("describes nothing but itself" in n for n in notes)


# ── the tool surface: one tool, closed dimensions, and no mean ──────────────


def test_there_is_no_mean_and_the_refusal_says_why():
    with pytest.raises(AggregateRefused) as exc:
        measure_for(dataset_spec("transactions"), "mean", "sale_price")
    assert "no mean" in str(exc.value)
    assert "2.9x the median" in str(exc.value)
    assert "mean" not in METRICS


def test_a_measured_metric_without_a_measure_is_refused_with_the_list():
    with pytest.raises(AggregateRefused) as exc:
        measure_for(dataset_spec("transactions"), "median", None)
    message = str(exc.value)
    assert "price_per_sqm" in message and "sale_price" in message


def test_count_needs_no_measure():
    assert measure_for(dataset_spec("transactions"), "count", None) is None


def test_an_unknown_measure_is_refused_with_the_ones_that_exist():
    with pytest.raises(AggregateRefused) as exc:
        measure_for(dataset_spec("transactions"), "median", "rent")
    assert "price_per_sqm" in str(exc.value)


def test_an_unknown_dataset_is_refused_with_the_three_that_exist():
    with pytest.raises(AggregateRefused) as exc:
        dataset_spec("listings")
    for name in DATASETS:
        assert name in str(exc.value)


def test_the_dimension_space_stays_closed():
    """Six blocked questions, one tool. If this list grows past a handful, the design has
    drifted back toward the thirty-three-tool version m15 rejected."""
    assert DATASETS == ("transactions", "rent_contracts", "valuations")
    assert METRICS == ("count", "median", "maximum", "minimum", "total")
    assert queries.BREAKDOWN_DIMENSIONS == ("year", "property_type")


def test_no_measure_expression_contains_a_format_placeholder():
    """Measure expressions are concatenated into SQL. Nothing in them may be substitutable,
    and nothing in them may be caller text."""
    for name in DATASETS:
        for measure in dataset_spec(name).measures.values():
            assert "{" not in measure.expression and "}" not in measure.expression
            assert ";" not in measure.expression


def test_rent_offers_the_per_property_measure_first():
    """The AED 550,010 answer came from the undivided column. Both are available; the
    per-property one is the one whose description says it is usually meant."""
    rent = dataset_spec("rent_contracts").measures
    assert "annual_rent_per_property" in rent
    assert "NULLIF(no_of_prop, 0)" in rent["annual_rent_per_property"].expression
    assert "unless the question is about" in rent["annual_rent_contract"].description


# ═══════════════════════════════════════════════════════════════════════════
# LIVE HALF — against the loaded database
# ═══════════════════════════════════════════════════════════════════════════
#
# A per-test engine with NullPool. The module-level `database.engine` pools connections
# while pytest-asyncio gives each test its own loop, which raises "attached to a different
# loop" on the second test that touches it. Same fix as `test_eval_fixtures.py`.


@asynccontextmanager
async def _live_conn():
    from config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            yield conn
    finally:
        await engine.dispose()


async def _skip_unless_loaded(conn, table: str, minimum: int) -> None:
    n = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
    if n < minimum:
        pytest.skip(f"{table} holds {n} rows, fewer than the {minimum} these assume")


async def _golden_value(conn, question_id: str):
    """Run the question's own hand-written SQL. Never a literal from this file."""
    sql = ANSWERS[question_id]["ground_truth_sql"]
    return (await conn.execute(text(sql))).scalar_one()


#: The six M-44 recorded as declined although the data answers them, each mapped to the
#: single `aggregate()` call that answers it. One tool, six questions.
BLOCKED_QUESTIONS = {
    "A-06": dict(dataset="transactions", metric="count", year=2024),
    "A-11": dict(dataset="transactions", metric="count", property_type="Villa"),
    "A-12": dict(dataset="transactions", metric="count", year=2025),
    "A-18": dict(dataset="transactions", metric="median", measure="price_per_sqm"),
    "A-19": dict(
        dataset="transactions",
        metric="median",
        measure="sale_price",
        property_type="Villa",
    ),
    "A-21": dict(dataset="transactions", metric="maximum", measure="sale_price"),
}


@pytest.mark.parametrize("question_id", sorted(BLOCKED_QUESTIONS))
async def test_a_blocked_question_now_matches_its_own_golden_sql(question_id):
    """The M-44 fix, graded the way `answers.yaml` grades everything else.

    The expected value is the question's `ground_truth_sql`, executed here. A reload moves
    both sides together; a disagreement is a disagreement about the data, which is what
    this file is for.
    """
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        expected = await _golden_value(conn, question_id)
        result = await queries.aggregate(conn, **BLOCKED_QUESTIONS[question_id])
        assert result.value is not None, result.suppressed
        assert float(result.value) == pytest.approx(float(expected), rel=1e-9)


async def test_the_answer_carries_its_unit_even_for_a_count():
    """"26889" and "26889 AED" are not the same sentence, and a bare integer has been
    written as the second one before now."""
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        counted = await queries.aggregate(
            conn, dataset="transactions", metric="count", year=2024
        )
        priced = await queries.aggregate(
            conn, dataset="transactions", metric="median", measure="price_per_sqm"
        )
        assert counted.unit == "registered sale"
        assert priced.unit == "AED/m2"


async def test_the_three_datasets_do_not_cover_the_same_time_and_nothing_said_so():
    """The finding this milestone turned up while fixing something else.

    `dataset_overview` reports three row counts and the transaction date range. It does not
    say that the rent contracts are a snapshot and the valuations are one seven-month
    window, and a model cannot infer either from a row count.
    """
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        await _skip_unless_loaded(conn, "raw_rent_contracts", 1000)
        await _skip_unless_loaded(conn, "raw_valuations", 100)

        sales = await queries.coverage(conn, "transactions")
        rents = await queries.coverage(conn, "rent_contracts")
        values = await queries.coverage(conn, "valuations")

        assert not sales.is_snapshot, "transactions really are a history"
        assert rents.is_snapshot
        assert values.is_snapshot
        assert values.first_date.year == values.last_date.year


async def test_the_row_that_is_in_count_star_and_in_no_year():
    """`COUNT(*)` over raw_transactions is 200,001 and the year buckets sum to 200,000."""
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        cov = await queries.coverage(conn, "transactions")
        assert cov.rows - cov.dated_rows == cov.undated_rows
        assert cov.undated_rows >= 1
        by_year = await queries.breakdown(
            conn, dataset="transactions", metric="count", dimension="year"
        )
        assert sum(g.rows for g in by_year) == cov.dated_rows


async def test_a_year_outside_a_dataset_refuses_instead_of_answering_zero():
    """Valuations cover 2026 only. `WHERE EXTRACT(YEAR ...) = 2024` returns 0, and 0 here
    means "this dataset does not go back that far"."""
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_valuations", 100)
        raw = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM raw_valuations "
                    "WHERE EXTRACT(YEAR FROM instance_date) = 2024"
                )
            )
        ).scalar_one()
        assert raw == 0, "if valuations gained history, this test is the thing to update"
        with pytest.raises(AggregateRefused) as exc:
            await queries.aggregate(
                conn, dataset="valuations", metric="count", year=2024
            )
        assert "NOT a count of zero" in str(exc.value)


async def test_an_unknown_property_type_refuses_against_the_live_universe():
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        raw = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM raw_transactions "
                    "WHERE property_type_en = 'Apartment'"
                )
            )
        ).scalar_one()
        assert raw == 0
        with pytest.raises(AggregateRefused) as exc:
            await queries.aggregate(
                conn,
                dataset="transactions",
                metric="count",
                property_type="Apartment",
            )
        assert "Unit" in str(exc.value)


async def test_the_median_floor_is_confirmed_at_the_boundary_on_live_rows():
    """1977 holds one sale, 1989 holds two, 1991 holds three.

    n=1: the median equals the minimum and the maximum.
    n=2: PERCENTILE_CONT returns (lo + hi) / 2, a value neither sale has.
    n=3: an actual row -- and the midrange of the same three is 4.8x higher.
    """
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        rows = (
            await conn.execute(
                text("""
                    SELECT EXTRACT(YEAR FROM instance_date)::int AS yr,
                           COUNT(*) AS n,
                           MIN(actual_worth) AS lo,
                           MAX(actual_worth) AS hi,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY actual_worth) AS med
                      FROM raw_transactions
                     WHERE EXTRACT(YEAR FROM instance_date) IN (1977, 1989, 1991)
                     GROUP BY 1
                """)
            )
        ).all()
        by_year = {r.yr: r for r in rows}
        if not {1977, 1989, 1991} <= set(by_year):
            pytest.skip("the early years these assume are not loaded")

        one = by_year[1977]
        assert one.n == 1 and one.med == one.lo == one.hi

        two = by_year[1989]
        assert two.n == 2 and float(two.med) == pytest.approx(
            (float(two.lo) + float(two.hi)) / 2
        )

        three = by_year[1991]
        assert three.n == 3
        assert float(three.med) < (float(three.lo) + float(three.hi)) / 2

        suppressed = await queries.breakdown(
            conn, dataset="transactions", metric="median",
            dimension="year", measure="sale_price",
        )
        thin = {g.key: g for g in suppressed if g.key in {"1977", "1989"}}
        assert all(g.value is None and g.suppressed for g in thin.values())


async def test_sale_price_and_price_per_square_metre_disagree_and_both_are_true():
    """The reason `price_per_sqm` is a measure and not a footnote.

    2022 to 2025: the median sale price is flat while the median price per square metre
    rises sharply, because the median floor area falls. A tool offering only the first
    answers "flat" to a question about Dubai property prices, and is not wrong about
    anything except which question it answered.
    """
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 100_000)

        async def series(measure: str) -> dict[str, float]:
            groups = await queries.breakdown(
                conn, dataset="transactions", metric="median",
                dimension="year", measure=measure,
            )
            return {g.key: g.value for g in groups if g.value is not None}

        price = await series("sale_price")
        per_sqm = await series("price_per_sqm")
        area = await series("floor_area")
        if not {"2022", "2025"} <= set(price):
            pytest.skip("2022-2025 are not both loaded")

        price_change = price["2025"] / price["2022"] - 1
        sqm_change = per_sqm["2025"] / per_sqm["2022"] - 1
        area_change = area["2025"] / area["2022"] - 1

        assert abs(price_change) < 0.05, price_change
        assert sqm_change > 0.30, sqm_change
        assert area_change < -0.15, area_change


async def test_the_measure_reports_the_rows_it_could_not_summarise():
    """Two of the 200,001 rows have no usable meter_sale_price. The median is taken over
    199,999 and the result says so rather than reporting a denominator it did not use."""
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        result = await queries.aggregate(
            conn, dataset="transactions", metric="median", measure="price_per_sqm"
        )
        assert isinstance(result, Aggregate)
        assert result.rows_matched == result.rows_in_dataset
        assert result.rows_excluded_by_measure >= 0
        if result.rows_excluded_by_measure:
            assert any("were excluded" in c for c in result.caveats)


async def test_a_partial_year_is_flagged_on_the_live_data():
    """2026 stops on 2026-02-17. Beside 2025 it reads as a market collapse."""
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        cov = await queries.coverage(conn, "transactions")
        result = await queries.aggregate(
            conn, dataset="transactions", metric="count", year=cov.last_date.year
        )
        assert result.period == "partial"
        assert any("not comparable with a full year" in c for c in result.caveats)


async def test_a_breakdown_by_property_type_ranks_without_inventing_a_tool():
    """"Which property type has the highest median sale price?" is the same operation with
    a different dimension. It is not another tool."""
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        groups = await queries.breakdown(
            conn,
            dataset="transactions",
            metric="median",
            dimension="property_type",
            measure="sale_price",
        )
        assert groups
        assert {g.key for g in groups} <= set(
            (await queries.coverage(conn, "transactions")).type_names
        )
        assert all(g.rows > 0 for g in groups)


async def test_an_unknown_breakdown_dimension_is_refused():
    async with _live_conn() as conn:
        with pytest.raises(AggregateRefused) as exc:
            await queries.breakdown(
                conn, dataset="transactions", metric="count", dimension="building"
            )
        assert "year" in str(exc.value)


# ═══════════════════════════════════════════════════════════════════════════
# THE TENTH TOOL — schema and handler, tested before the wiring exists
# ═══════════════════════════════════════════════════════════════════════════
#
# `services/agent/tools.py` is claimed by an uncommitted milestone, so the registration
# cannot be made yet. Everything the registration would carry is here, and tested, so that
# the blocked edit is three lines and none of them is a decision.


def test_the_argument_schema_is_strict_and_self_contained():
    """The same helper that builds /ask's answer schema, on the same terms: no $ref, every
    property required, additionalProperties false. A schema a constrained decoder rejects
    is a tool that never gets called correctly."""
    from services.llm.schema import strict_json_schema

    schema = strict_json_schema(tool.DatasetAggregateArgs)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "$defs" not in schema and "$ref" not in repr(schema)


def _enum_of(prop: dict) -> set[str]:
    """The allowed values of a property, whether or not it is nullable.

    A required `Literal[...]` lands as `{"enum": [...]}`; an optional one lands as
    `{"anyOf": [{"enum": [...]}, {"type": "null"}]}`. Both are closed sets and the test is
    about closedness, not about which branch Pydantic took.
    """
    if "enum" in prop:
        return set(prop["enum"])
    return {v for branch in prop.get("anyOf", []) for v in branch.get("enum", [])}


def test_every_dimension_in_the_schema_is_closed_except_property_type():
    """Constrained decoding cannot emit a dataset, metric, measure or breakdown that does
    not exist. `property_type` is open because its values belong to the data, and that is
    exactly the case rule 1 handles."""
    from services.llm.schema import strict_json_schema

    props = strict_json_schema(tool.DatasetAggregateArgs)["properties"]
    assert _enum_of(props["dataset"]) == set(DATASETS)
    assert _enum_of(props["metric"]) == set(METRICS)
    assert _enum_of(props["measure"]) == set(tool.MEASURE_KEYS)
    assert _enum_of(props["breakdown_by"]) == set(queries.BREAKDOWN_DIMENSIONS)
    assert _enum_of(props["property_type"]) == set()
    assert props["property_type"]["type"] == ["string", "null"]


def test_the_measure_enum_is_exactly_the_measures_that_exist():
    """A hand-written Literal beside a generated set is a drift waiting to happen, so the
    two are compared rather than trusted."""
    from typing import get_args

    assert set(get_args(tool.Measures)) == set(tool.MEASURE_KEYS)


def test_the_description_sends_area_questions_to_the_area_tool():
    """m15's finding: a tool that has to be called once per area burns the step budget.
    The routing rule has to be in the description, because that is what the model reads
    while it is choosing."""
    text_ = tool.DESCRIPTION
    assert "NOT area-scoped" in text_
    assert "area_summary" in text_
    assert "do not call this one per area" in text_


def test_the_description_says_the_mean_is_absent_and_why():
    assert "NO mean" in tool.DatasetAggregateArgs.model_fields["metric"].description


def test_the_registration_is_a_complete_tool_entry():
    """Everything `Tool(...)` needs, so the blocked edit adds no new decision."""
    assert tool.REGISTRATION["name"] == "dataset_aggregate"
    assert tool.REGISTRATION["category"] == "sql"
    assert tool.REGISTRATION["arguments"] is tool.DatasetAggregateArgs
    assert tool.REGISTRATION["handler"] is tool.dataset_aggregate


async def test_the_handler_answers_a_blocked_question_end_to_end():
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        expected = await _golden_value(conn, "A-19")
        payload = await tool.dataset_aggregate(
            conn,
            dataset="transactions",
            metric="median",
            measure="sale_price",
            property_type="villa",
        )
        assert payload["value"] == pytest.approx(float(expected), rel=1e-9)
        assert payload["unit"] == "AED"
        assert payload["filters"]["property_type"] == "Villa"


async def test_the_handler_returns_a_refusal_as_data_not_as_a_traceback():
    """`tools.run` catches `ToolFailed` by name and logs everything else as a bug. This
    module cannot edit that file, so a refusal comes back as a readable payload and the
    tool is correct whether or not the extra except clause is ever added."""
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        payload = await tool.dataset_aggregate(
            conn, dataset="transactions", metric="count", property_type="Apartment"
        )
        assert payload["refused"] is True
        assert "Villa" in payload["reason"]
        assert "NOT a zero" in payload["note"]


async def test_the_handler_serialises_a_breakdown_with_its_row_counts():
    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        payload = await tool.dataset_aggregate(
            conn,
            dataset="transactions",
            metric="median",
            measure="sale_price",
            breakdown_by="property_type",
        )
        assert payload["grouped_by"] == "property_type"
        assert payload["unit"] == "AED"
        assert all({"key", "rows", "value"} <= set(g) for g in payload["groups"])


async def test_every_handler_payload_is_json_serialisable():
    """`tools.run` calls `json.dumps(result, default=str)`. `default=str` will happily turn
    a Decimal into a string that reads like a number and grades as a name -- so the values
    are floats and ints before they leave here, not after."""
    import json

    async with _live_conn() as conn:
        await _skip_unless_loaded(conn, "raw_transactions", 1000)
        for kwargs in (
            dict(dataset="transactions", metric="count", year=2024),
            dict(dataset="transactions", metric="maximum", measure="sale_price"),
            dict(dataset="valuations", metric="count", year=1990),
            dict(
                dataset="transactions",
                metric="median",
                measure="price_per_sqm",
                breakdown_by="year",
            ),
        ):
            payload = await tool.dataset_aggregate(conn, **kwargs)
            round_tripped = json.loads(json.dumps(payload))
            assert round_tripped == payload, kwargs
