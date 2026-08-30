"""The half with no database: what a dataset-wide number is allowed to say.

Everything here is a pure function over a spec and a count. `queries.py` produces numbers;
this module decides which of them may be reported and what has to be said beside them.

WHY ONE TOOL AND NOT SIX
-------------------------
`SESSION-HANDOFF.md` asks it directly: adding one tool closes M-44, but is that the first
step toward the thirty-three-tool design m15 rejected on purpose? The answer is the rule
m15 already wrote down -- *operations that differ only by filter parameters collapse into
one tool*. Six questions ("how many in 2024", "how many villas", "the median per square
metre", "the largest sale") are one operation over a closed product of dimensions:
`metric x dataset x measure x filters`. Every dimension here is an enum or an integer, so
adding a question adds no tool and no tokens. The tool count goes from nine to ten and
stops there.

WHAT IS DELIBERATELY NOT A DIMENSION
-------------------------------------
`area_name`. `area_summary` and `area_price_history` already take one, and a second tool
that answers the same question is precisely the routing failure `eval/golden/routing.yaml`
grades. This tool is dataset-wide; its description says so and names the other tool.

NO MEAN, AND THE REASON IS A NUMBER
------------------------------------
`METRICS` has no `mean`. Over all 200,001 transactions the mean sale price is AED
3,881,668 and the median is AED 1,356,000 -- the mean is 2.9x the median, because the
distribution carries a single AED 13.79 bn row. Omitting the metric is not enough on its
own: the reason ships to the model inside the metric's field description, which is where
routing is actually enforced (`services/agent/tools.py`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

# ── metrics ─────────────────────────────────────────────────────────────────

Metric = Literal["count", "median", "maximum", "minimum", "total"]

METRICS: tuple[str, ...] = ("count", "median", "maximum", "minimum", "total")

#: Metrics that summarise a column and therefore need one named.
MEASURED_METRICS: frozenset[str] = frozenset({"median", "maximum", "minimum", "total"})


def min_rows_for_median() -> int:
    """The smallest n at which `PERCENTILE_CONT(0.5)` returns a middle observation.

    This is the same shape of argument as `observability.shaping.min_sample_for`, and it is
    equally exact -- it is a property of the aggregate, not a convention.

    * n = 1: the median is the only value, which is also the minimum and the maximum. It is
      an extreme wearing the name of a centre.
    * n = 2: `PERCENTILE_CONT` interpolates, so it returns `(lo + hi) / 2` -- the midrange,
      a value no row has and the most outlier-sensitive statistic there is.
    * n = 3: the middle row, which is what "median" means.

    The live table demonstrates all three. In `raw_transactions`, 1977 holds one sale and
    reports median = min = max = AED 1,500,000. 1989 holds two and reports AED 5,751,230.50,
    which is exactly (4,500,000 + 7,002,461) / 2 and belongs to neither sale. 1991 holds
    three and reports AED 800,000, an actual row -- where the midrange of the same three
    rows would have been AED 3,875,000, or 4.8x too high.

    Below this floor the value is suppressed and the reason is carried on the result. It is
    NOT rounded up to a comfortable number: three is where the definition starts holding,
    and anything above it is taste dressed as arithmetic.
    """
    return 3


MIN_ROWS_FOR_MEDIAN: int = min_rows_for_median()


class AggregateRefused(ValueError):
    """This aggregate will not be computed, and the message says what to send instead.

    Written for the MODEL, in the same spirit as `services.agent.tools.ToolFailed`: the
    message is the recovery path, so it names the values that WOULD work. A different
    exception type rather than an import from the agent package, because these two modules
    are staged in different commits and a cross-import would order them.
    """


# ── measures ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Measure:
    """One summarisable column, and everything the caller may not choose.

    `expression` is SQL, and it is the ONLY place SQL text is assembled. It never contains
    caller input: a measure is selected out of this table by key, and a key that is not in
    the table is refused before any statement is built.
    """

    key: str
    expression: str
    unit: str
    description: str
    #: Non-positive values are excluded. Every money and area column here is a quantity
    #: that cannot meaningfully be zero, and a zero in one is a missing value that was
    #: loaded as a number. The count of what this excluded is reported, never swallowed.
    positive_only: bool = True


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    table: str
    date_column: str
    type_column: str
    #: What one row is, in words, for a message a model has to read.
    row_label: str
    measures: Mapping[str, Measure]


_TRANSACTIONS = DatasetSpec(
    name="transactions",
    table="raw_transactions",
    date_column="instance_date",
    type_column="property_type_en",
    row_label="registered sale",
    measures={
        "sale_price": Measure(
            key="sale_price",
            expression="actual_worth",
            unit="AED",
            description="the registered transaction value of the whole property",
        ),
        "price_per_sqm": Measure(
            key="price_per_sqm",
            expression="meter_sale_price",
            unit="AED/m2",
            description="price per square metre, which moves independently of sale price "
            "because the size of the median unit changes",
        ),
        "floor_area": Measure(
            key="floor_area",
            expression="procedure_area",
            unit="m2",
            description="the area the sale was registered against",
        ),
    },
)

_RENT_CONTRACTS = DatasetSpec(
    name="rent_contracts",
    table="raw_rent_contracts",
    date_column="contract_start_date",
    type_column="ejari_property_type_en",
    row_label="registered rent contract",
    measures={
        # The per-property figure first, because it is the one that is usually meant. A
        # contract can cover a whole building: dividing is the difference between "a
        # typical Dubai Marina rent is AED 120,000" and the AED 550,010 the system once
        # answered from the undivided column.
        "annual_rent_per_property": Measure(
            key="annual_rent_per_property",
            expression="(annual_amount / NULLIF(no_of_prop, 0))",
            unit="AED",
            description="annual rent divided by the number of properties on the contract "
            "-- what one home costs, and the figure a person asking about rent means",
        ),
        "annual_rent_contract": Measure(
            key="annual_rent_contract",
            expression="annual_amount",
            unit="AED",
            description="annual rent for the WHOLE contract, which may cover many "
            "properties. Use annual_rent_per_property unless the question is about "
            "contracts rather than homes",
        ),
        "floor_area": Measure(
            key="floor_area",
            expression="actual_area",
            unit="m2",
            description="the area recorded on the contract",
        ),
    },
)

_VALUATIONS = DatasetSpec(
    name="valuations",
    table="raw_valuations",
    date_column="instance_date",
    type_column="property_type_en",
    row_label="recorded valuation",
    measures={
        "valued_amount": Measure(
            key="valued_amount",
            expression="actual_worth",
            unit="AED",
            description="the valuation placed on the property",
        ),
        "floor_area": Measure(
            key="floor_area",
            expression="actual_area",
            unit="m2",
            description="the area the valuation was carried out against",
        ),
    },
)

_SPECS: Mapping[str, DatasetSpec] = {
    _TRANSACTIONS.name: _TRANSACTIONS,
    _RENT_CONTRACTS.name: _RENT_CONTRACTS,
    _VALUATIONS.name: _VALUATIONS,
}

DATASETS: tuple[str, ...] = tuple(_SPECS)


def dataset_spec(name: str) -> DatasetSpec:
    spec = _SPECS.get(name)
    if spec is None:
        raise AggregateRefused(
            f"No dataset named {name!r}. Available: {', '.join(DATASETS)}."
        )
    return spec


def measure_for(spec: DatasetSpec, metric: str, measure: str | None) -> Measure | None:
    """Which column this metric summarises, or None for `count`.

    A metric that needs a measure and did not get one is refused WITH THE LIST, because the
    list is the whole answer -- a model that asked for a median of nothing needs to know
    that `price_per_sqm` exists, not that a field was missing.
    """
    if metric not in METRICS:
        raise AggregateRefused(
            f"No metric named {metric!r}. Available: {', '.join(METRICS)}. "
            f"There is deliberately no mean: over all transactions the mean sale price is "
            f"2.9x the median, because one row is AED 13.79 bn."
        )
    if metric not in MEASURED_METRICS:
        return None
    available = ", ".join(sorted(spec.measures))
    if measure is None:
        raise AggregateRefused(
            f"metric={metric!r} summarises a column, so it needs a measure. "
            f"For {spec.name} the choices are: {available}."
        )
    found = spec.measures.get(measure)
    if found is None:
        raise AggregateRefused(
            f"No measure named {measure!r} on {spec.name}. Available: {available}."
        )
    return found


# ── filter values ───────────────────────────────────────────────────────────


def canonical_filter_value(
    value: str, universe: Sequence[str], *, dimension: str, dataset: str
) -> str:
    """Resolve a filter value against the closed set the data actually holds.

    THIS IS THE RULE THE WHOLE MODULE EXISTS FOR. `WHERE property_type_en = 'Apartment'`
    is valid SQL over `raw_transactions` and returns zero rows, and zero is a number: it
    renders as "there are no apartment sales in Dubai", which is false, and nothing about
    the response distinguishes it from a genuine absence. So the value is matched against
    the live universe first, and a miss is refused with the four values that exist.

    A difference of case or surrounding space is NOT a different question, so 'villa' and
    ' Villa ' both resolve to 'Villa'. The canonical spelling is what gets bound as the
    query parameter -- the caller's string is never interpolated into SQL.
    """
    wanted = value.strip().casefold()
    for candidate in universe:
        if candidate.strip().casefold() == wanted:
            return candidate
    listed = ", ".join(repr(c) for c in universe) or "(none recorded)"
    raise AggregateRefused(
        f"{dimension}={value!r} does not exist in {dataset}. "
        f"The recorded values are: {listed}. Nothing matches {value!r}, so this is not a "
        f"count of zero -- it is a filter that cannot be applied."
    )


# ── periods ─────────────────────────────────────────────────────────────────

PeriodState = Literal["complete", "partial", "outside_coverage"]


def period_state(
    year: int, first: date | None, last: date | None
) -> PeriodState:
    """Whether a calendar year lies wholly inside the dataset's coverage.

    Three states, and the middle one is why this exists. `raw_transactions` ends on
    2026-02-17: a count for 2026 is 4,223 against 32,065 for 2025, and read beside it that
    is an 87% collapse in the Dubai property market. It is seven weeks of data. The first
    year is partial for the same reason from the other end -- coverage begins 1977-04-25.

    `outside_coverage` is the refusal case, and it is not hypothetical: every one of the
    3,106 valuations falls in 2026, so `dataset=valuations, year=2024` has a correct SQL
    answer of 0 that means "this dataset does not go back that far".
    """
    if first is None or last is None:
        return "outside_coverage"
    if year < first.year or year > last.year:
        return "outside_coverage"
    if date(year, 1, 1) < first or date(year, 12, 31) > last:
        return "partial"
    return "complete"


def share(numerator: int, denominator: int) -> float | None:
    """A proportion, or None when there is nothing to be a proportion of.

    Deliberately a local four-line function rather than an import from
    `services.observability.shaping.rate`, which is the same idea. The two packages are
    staged in different commits and a cross-import would force an order between them for
    no benefit. The duplication is four lines; the coupling would be permanent.
    """
    if not denominator:
        return None
    return numerator / denominator


# ── results ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Coverage:
    """What a dataset actually spans, which nothing in the system reported before.

    `dataset_overview` reports three row counts and the transaction date range. It does not
    say that the rent contracts are a snapshot and the valuations are seven months, and a
    model cannot infer either from a row count.
    """

    dataset: str
    rows: int
    dated_rows: int
    first_date: date | None
    last_date: date | None
    heaviest_year: int | None
    heaviest_year_rows: int
    property_types: tuple[tuple[str, int], ...] = ()

    @property
    def undated_rows(self) -> int:
        """Rows the date column cannot place. `raw_transactions` has exactly one.

        It is why `COUNT(*)` over the table is 200,001 while the year buckets sum to
        200,000, and a panel that shows both without this line looks like it lost a row.
        """
        return self.rows - self.dated_rows

    @property
    def concentration(self) -> float | None:
        """The share of dated rows in the single heaviest year.

        For `raw_rent_contracts` this is 0.895. A dataset that is 89.5% one year is a
        snapshot of what is registered now, and a per-year count over it is not a history
        however much it looks like one.
        """
        return share(self.heaviest_year_rows, self.dated_rows)

    @property
    def is_snapshot(self) -> bool:
        c = self.concentration
        return c is not None and c >= 0.5

    @property
    def type_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.property_types)


@dataclass(frozen=True)
class Group:
    """One row of a breakdown, carrying its own n so the value can be judged.

    `rows` is the number the VALUE was computed over -- rows the measure could summarise,
    not rows in the group. That is what the suppression floor has to be applied against: a
    year holding 400 sales of which two have a price is a two-row median.
    """

    key: str
    rows: int
    value: float | None
    suppressed: str | None = None


@dataclass(frozen=True)
class Aggregate:
    dataset: str
    metric: str
    measure: str | None
    unit: str | None
    value: float | int | None
    rows_matched: int
    rows_in_dataset: int
    rows_excluded_by_measure: int
    filters: Mapping[str, Any] = field(default_factory=dict)
    period: PeriodState | None = None
    suppressed: str | None = None
    caveats: tuple[str, ...] = ()

    @property
    def matched_share(self) -> float | None:
        return share(self.rows_matched, self.rows_in_dataset)


def year_refusal(spec: DatasetSpec, year: int, coverage: Coverage) -> AggregateRefused:
    """The refusal for a year the dataset does not reach, carrying the range it does.

    A function of its own because the message IS the fix. "0" and "this dataset covers 2026
    only" are the same query result and completely different answers, and only the second
    lets a model say something true. Pure, so the wording is unit-tested rather than
    reviewed once.
    """
    if coverage.first_date is None or coverage.last_date is None:
        span = "no dated rows at all"
    elif coverage.first_date.year == coverage.last_date.year:
        span = (
            f"{coverage.first_date.year} only "
            f"({coverage.first_date} to {coverage.last_date})"
        )
    else:
        span = f"{coverage.first_date.year} to {coverage.last_date.year}"
    return AggregateRefused(
        f"{spec.name} holds no rows dated {year}: it covers {span}. This is a gap in "
        f"coverage, NOT a count of zero -- do not report it as 'no {spec.row_label}s "
        f"in {year}'."
    )


def suppression_for(metric: str, rows: int) -> str | None:
    """Why this metric may not be reported over this many rows, or None."""
    if rows == 0:
        return "no rows matched the filters"
    if metric == "median" and rows < MIN_ROWS_FOR_MEDIAN:
        return (
            f"a median over {rows} row{'s' if rows != 1 else ''} is an extreme or a "
            f"midrange, not a middle value; {MIN_ROWS_FOR_MEDIAN} is the floor"
        )
    return None


def caveats_for(
    *,
    spec: DatasetSpec,
    metric: str,
    measure: Measure | None,
    rows_matched: int,
    rows_excluded_by_measure: int,
    period: PeriodState | None,
    year: int | None,
    coverage: Coverage,
) -> tuple[str, ...]:
    """Everything that has to be said beside the number, in the order it matters.

    Returned as text rather than as flags because the consumer is a language model reading
    a tool result, and a flag named `period_complete: false` is one the model may or may
    not mention. A sentence in the payload is one it has to read.
    """
    notes: list[str] = []

    if period == "partial" and year is not None:
        notes.append(
            f"{year} is only PARTLY covered by {spec.name}: the data runs "
            f"{coverage.first_date} to {coverage.last_date}. This figure is not "
            f"comparable with a full year."
        )

    if coverage.is_snapshot and coverage.heaviest_year is not None:
        pct = coverage.concentration
        note = (
            f"{spec.name} is a snapshot, not a history: "
            f"{pct:.1%} of its rows fall in {coverage.heaviest_year}. "
            f"A per-year figure from it describes what is registered, not what happened."
        )
        if year is not None and year != coverage.heaviest_year:
            matched = share(rows_matched, coverage.rows)
            if matched is not None:
                note += f" {year} holds {matched:.2%} of the dataset."
        notes.append(note)

    if rows_excluded_by_measure and measure is not None:
        notes.append(
            f"{rows_excluded_by_measure} row(s) were excluded because "
            f"{measure.expression} was null or not positive."
        )

    if coverage.undated_rows and year is not None:
        notes.append(
            f"{coverage.undated_rows} row(s) in {spec.name} have no "
            f"{spec.date_column} and cannot fall in any year."
        )

    if metric == "total" and measure is not None:
        notes.append(
            "A total is dominated by its largest rows: one sale in raw_transactions is "
            "AED 13.79 bn, 1.78% of the value of all 200,001. Compare medians, not totals."
        )

    if rows_matched and metric in {"maximum", "minimum"}:
        notes.append(
            f"An extreme is one {spec.row_label} and describes nothing but itself. "
            f"It is not a summary of the {rows_matched} rows it was drawn from."
        )

    return tuple(notes)
