"""One statement per question, over the RAW tables.

Every function takes an open connection rather than opening its own, so a caller can read
the coverage and the aggregate inside one transaction and get two answers about the same
data. It is also what lets these be tested against the live tables without a FastAPI
dependency in the way.

WHY THE RAW TABLES AND NOT `services/market.py`
------------------------------------------------
`eval/golden/answers.yaml` grades against hand-written SQL over `raw_transactions`,
`raw_rent_contracts` and `raw_valuations`, deliberately: an expected value produced by
calling `area_summary` would prove only that `area_summary` agrees with itself. This module
is what the six blocked questions will be answered FROM, so it reads the same tables the
golden queries read -- and `test_aggregates.py` runs both and compares, question by
question, rather than asserting a literal.

WHERE THE SQL COMES FROM
-------------------------
Table names, date columns, type columns and measure expressions all come out of
`spec.DatasetSpec`, which is a literal in this repository. The only caller-supplied values
that reach a statement are an integer year and a property type already resolved to a
spelling the table itself returned, and both are bound parameters. No code path here puts
caller text into SQL text.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.aggregates.spec import (
    Aggregate,
    AggregateRefused,
    Coverage,
    DatasetSpec,
    Group,
    Measure,
    canonical_filter_value,
    caveats_for,
    dataset_spec,
    measure_for,
    period_state,
    suppression_for,
    year_refusal,
)

#: How `metric` becomes an aggregate function. `median` is `PERCENTILE_CONT`, which
#: interpolates -- see `spec.min_rows_for_median` for why that is guarded rather than
#: swapped for `PERCENTILE_DISC`. Over tens of thousands of rows the interpolation between
#: two neighbours is invisible; the failure mode is small n, and small n is handled by
#: refusing to report rather than by changing the function.
_AGGREGATE_SQL: dict[str, str] = {
    "count": "COUNT(*)",
    "median": "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {expr})",
    "maximum": "MAX({expr})",
    "minimum": "MIN({expr})",
    "total": "SUM({expr})",
}

BREAKDOWN_DIMENSIONS: tuple[str, ...] = ("year", "property_type")


def _aggregate_expression(metric: str, measure: Measure | None) -> str:
    template = _AGGREGATE_SQL[metric]
    return template if measure is None else template.format(expr=measure.expression)


def _as_date(value: Any) -> date | None:
    """Coerce whatever the driver returned to a calendar date.

    `raw_transactions.instance_date` is a DATE and `raw_valuations.instance_date` is a
    TIMESTAMP, so the same column name comes back as two different Python types from two
    tables. Everything downstream compares days.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


async def coverage(conn: AsyncConnection, dataset: str) -> Coverage:
    """What this dataset spans: rows, dates, the heaviest year, and the type universe.

    Read before any filtered aggregate, because all five rules need it -- the type universe
    to refuse an unknown value, the date bounds to refuse an uncovered year and to mark a
    partial one, the undated count to explain the row that is in `COUNT(*)` and in no year,
    and the concentration to say when a dataset is a snapshot rather than a history.
    """
    spec = dataset_spec(dataset)
    row = (
        await conn.execute(
            text(f"""
                SELECT COUNT(*)                  AS total_rows,
                       COUNT({spec.date_column}) AS dated_rows,
                       MIN({spec.date_column})   AS first_date,
                       MAX({spec.date_column})   AS last_date
                  FROM {spec.table}
            """)
        )
    ).one()

    heaviest = (
        await conn.execute(
            text(f"""
                SELECT EXTRACT(YEAR FROM {spec.date_column})::int AS yr,
                       COUNT(*)                                   AS n
                  FROM {spec.table}
                 WHERE {spec.date_column} IS NOT NULL
                 GROUP BY 1
                 ORDER BY n DESC, yr DESC
                 LIMIT 1
            """)
        )
    ).first()

    types = (
        await conn.execute(
            text(f"""
                SELECT {spec.type_column} AS name, COUNT(*) AS n
                  FROM {spec.table}
                 WHERE {spec.type_column} IS NOT NULL
                 GROUP BY 1
                 ORDER BY n DESC
            """)
        )
    ).all()

    return Coverage(
        dataset=spec.name,
        rows=row.total_rows,
        dated_rows=row.dated_rows,
        first_date=_as_date(row.first_date),
        last_date=_as_date(row.last_date),
        heaviest_year=heaviest.yr if heaviest else None,
        heaviest_year_rows=heaviest.n if heaviest else 0,
        property_types=tuple((r.name, r.n) for r in types),
    )


def _positivity(measure: Measure | None) -> str | None:
    """The predicate that keeps a measure's unusable rows out of its own aggregate.

    Applied as an aggregate `FILTER`, not as a WHERE clause, and the distinction is the
    reason both counts in the result mean what they say. A WHERE would remove the rows from
    the statement entirely and `rows_matched` would silently become `rows_measured`; a
    FILTER leaves them countable, so the result can report that the median of
    `meter_sale_price` was taken over 199,999 of the 200,001 rows the question matched.
    Ordered-set aggregates accept FILTER, so `PERCENTILE_CONT` is not a special case.
    """
    if measure is None or not measure.positive_only:
        return None
    return f"{measure.expression} IS NOT NULL AND {measure.expression} > 0"


def _filtered(expression: str, predicate: str | None) -> str:
    return expression if predicate is None else f"{expression} FILTER (WHERE {predicate})"


def _row_filter(
    spec: DatasetSpec, *, year: int | None, property_type: str | None
) -> tuple[str, dict[str, Any]]:
    """The WHERE fragment for the rows the QUESTION asked for, and its parameters.

    Kept separate from the measure's positivity filter because the two counts mean
    different things and the result reports both: rows the question matched, and rows the
    question matched that the column could actually summarise.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if year is not None:
        clauses.append(f"EXTRACT(YEAR FROM {spec.date_column}) = :year")
        params["year"] = year
    if property_type is not None:
        clauses.append(f"{spec.type_column} = :property_type")
        params["property_type"] = property_type
    return (" AND ".join(clauses) or "TRUE"), params


async def aggregate(
    conn: AsyncConnection,
    *,
    dataset: str,
    metric: str,
    measure: str | None = None,
    year: int | None = None,
    property_type: str | None = None,
) -> Aggregate:
    """One dataset-wide number, with every reason it might be misread attached.

    Raises `AggregateRefused` rather than returning a number when a filter cannot be
    applied, and that is the whole difference from the naive version. `WHERE
    property_type_en = 'Apartment'` over `raw_transactions` and `WHERE EXTRACT(YEAR FROM
    instance_date) = 2024` over `raw_valuations` are both valid SQL returning 0, and both
    zeros are false statements about Dubai.
    """
    spec = dataset_spec(dataset)
    resolved = measure_for(spec, metric, measure)
    cov = await coverage(conn, dataset)

    period = None
    if year is not None:
        period = period_state(year, cov.first_date, cov.last_date)
        if period == "outside_coverage":
            raise year_refusal(spec, year, cov)

    canonical_type = None
    if property_type is not None:
        canonical_type = canonical_filter_value(
            property_type,
            cov.type_names,
            dimension=spec.type_column,
            dataset=spec.name,
        )

    where, params = _row_filter(spec, year=year, property_type=canonical_type)
    predicate = _positivity(resolved)
    row = (
        await conn.execute(
            text(f"""
                SELECT {_filtered(_aggregate_expression(metric, resolved), predicate)}
                                                        AS value,
                       {_filtered("COUNT(*)", predicate)} AS rows_measured,
                       COUNT(*)                           AS rows_matched
                  FROM {spec.table}
                 WHERE {where}
            """),
            params,
        )
    ).one()

    suppressed = suppression_for(metric, row.rows_measured)
    value: float | int | None = None
    if suppressed is None and row.value is not None:
        value = int(row.value) if metric == "count" else float(row.value)

    filters: dict[str, Any] = {}
    if year is not None:
        filters["year"] = year
    if canonical_type is not None:
        filters["property_type"] = canonical_type
    excluded = row.rows_matched - row.rows_measured

    return Aggregate(
        dataset=spec.name,
        metric=metric,
        measure=resolved.key if resolved else None,
        # The unit of a count is the thing counted, which is why this is not None for
        # `count`. "26889 registered sales" and "26889 AED" are not the same sentence, and
        # a model handed a bare integer has written the second one before now.
        unit=resolved.unit if resolved else spec.row_label,
        value=value,
        rows_matched=row.rows_matched,
        rows_in_dataset=cov.rows,
        rows_excluded_by_measure=excluded,
        filters=filters,
        period=period,
        suppressed=suppressed,
        caveats=caveats_for(
            spec=spec,
            metric=metric,
            measure=resolved,
            rows_matched=row.rows_matched,
            rows_excluded_by_measure=excluded,
            period=period,
            year=year,
            coverage=cov,
        ),
    )


async def breakdown(
    conn: AsyncConnection,
    *,
    dataset: str,
    metric: str,
    dimension: str,
    measure: str | None = None,
    limit: int | None = None,
) -> list[Group]:
    """The same metric split by year or by property type, each group carrying its own n.

    This is what turns a fact into a comparison, and it is where the suppression floor earns
    its place: `raw_transactions` holds one sale in 1977 and two in 1989, and without the
    floor those years report a median that is an extreme and a midrange respectively --
    sitting in the same column as a median over 32,065 rows and looking exactly like it.

    It is also what makes the divergence visible. Split by year, the median SALE PRICE of a
    Dubai property is flat from 2022 to 2025 (-1.3%) while the median PRICE PER SQUARE
    METRE is up 43%, because the median floor area fell from 118.5 m2 to 90.1 m2. Both are
    true, both come from this table, and a tool offering only the first answers "flat" to a
    question about prices.
    """
    spec = dataset_spec(dataset)
    resolved = measure_for(spec, metric, measure)
    if dimension not in BREAKDOWN_DIMENSIONS:
        raise AggregateRefused(
            f"No dimension named {dimension!r}. "
            f"Available: {', '.join(BREAKDOWN_DIMENSIONS)}."
        )

    if dimension == "year":
        key_sql = f"EXTRACT(YEAR FROM {spec.date_column})::int"
        not_null = f"{spec.date_column} IS NOT NULL"
        order = "bucket_key ASC"
    else:
        key_sql = spec.type_column
        not_null = f"{spec.type_column} IS NOT NULL"
        order = "n DESC"

    limit_sql = "LIMIT :limit" if limit else ""
    predicate = _positivity(resolved)
    rows = (
        await conn.execute(
            text(f"""
                SELECT {key_sql}                          AS bucket_key,
                       {_filtered("COUNT(*)", predicate)} AS n,
                       {_filtered(_aggregate_expression(metric, resolved), predicate)}
                                                          AS value
                  FROM {spec.table}
                 WHERE {not_null}
                 GROUP BY 1
                 ORDER BY {order}
                 {limit_sql}
            """),
            {"limit": limit} if limit else {},
        )
    ).all()

    groups: list[Group] = []
    for r in rows:
        suppressed = suppression_for(metric, r.n)
        value: float | None = None
        if suppressed is None and r.value is not None:
            value = float(r.value)
        groups.append(
            Group(key=str(r.bucket_key), rows=r.n, value=value, suppressed=suppressed)
        )
    return groups
