from fastapi import APIRouter, Query
from sqlalchemy import text

from database import engine
from models.area import (
    AreaDatasetStats,
    AreaHistory,
    AreaHistoryPoint,
    AreaOverview,
    AreaSummary,
)

router = APIRouter()


@router.get("/areas", response_model=list[AreaOverview])
async def list_areas():
    """Return unique areas across all datasets with counts and averages.

    **One row per area NAME**, not per `(area_id, area_name_en)` pair. Two things
    forced that change:

    1. `Mushrif` exists under **two different `area_id`s** in the DLD transaction data
       -- 404 with 33 transactions and 420 with 1. Grouping by the pair emitted two
       rows with the same name (223 rows for 222 distinct names), which React rejected
       as a duplicate key. Both rows also linked to the same `/areas/Mushrif` page,
       which aggregates by name and therefore already showed the combined 34.
       The list now agrees with the detail page instead of contradicting it.
    2. The `FULL OUTER JOIN`s match on name while the subqueries grouped by
       `(area_id, area_name_en)`. That is a latent fan-out: the moment rent contracts
       are loaded, a name carrying two `area_id`s on both sides would produce a
       cartesian product. Grouping by the normalised name removes the possibility.

    Names are normalised with `UPPER(TRIM(...))` before joining because the DLD data
    is not internally consistent about case -- `Abu Hail`, `Al Baraha`, but `AL Athbah`.
    `area_id` is a representative (`MIN`) and is NOT unique for `Mushrif`; the name is
    the key the rest of the API uses.
    """
    query = text("""
        WITH t AS (
            SELECT UPPER(TRIM(area_name_en)) AS norm,
                   MIN(area_name_en) AS area_name_en,
                   MIN(area_id)      AS area_id,
                   COUNT(*)          AS cnt,
                   AVG(actual_worth) AS avg_price
              FROM raw_transactions
             WHERE area_name_en IS NOT NULL
             GROUP BY 1
        ), r AS (
            SELECT UPPER(TRIM(area_name_en)) AS norm,
                   MIN(area_name_en)  AS area_name_en,
                   MIN(area_id)       AS area_id,
                   COUNT(*)           AS cnt,
                   AVG(annual_amount) AS avg_amount
              FROM raw_rent_contracts
             WHERE area_name_en IS NOT NULL
             GROUP BY 1
        ), v AS (
            SELECT UPPER(TRIM(area_name_en)) AS norm,
                   MIN(area_name_en) AS area_name_en,
                   MIN(area_id)      AS area_id,
                   COUNT(*)          AS cnt
              FROM raw_valuations
             WHERE area_name_en IS NOT NULL
             GROUP BY 1
        )
        SELECT
            COALESCE(t.area_id, r.area_id, v.area_id) AS area_id,
            COALESCE(t.area_name_en, r.area_name_en, v.area_name_en) AS area_name_en,
            COALESCE(t.cnt, 0) AS transaction_count,
            COALESCE(r.cnt, 0) AS rent_count,
            COALESCE(v.cnt, 0) AS valuation_count,
            t.avg_price AS avg_transaction_price,
            r.avg_amount AS avg_rent_amount
        FROM t
        FULL OUTER JOIN r ON t.norm = r.norm
        FULL OUTER JOIN v ON COALESCE(t.norm, r.norm) = v.norm
        ORDER BY (COALESCE(t.cnt, 0) + COALESCE(r.cnt, 0) + COALESCE(v.cnt, 0)) DESC
    """)

    async with engine.connect() as conn:
        result = await conn.execute(query)
        rows = result.fetchall()

    return [
        AreaOverview(
            area_id=r[0],
            area_name_en=r[1],
            transaction_count=r[2],
            rent_count=r[3],
            valuation_count=r[4],
            avg_transaction_price=round(r[5], 2) if r[5] else None,
            avg_rent_amount=round(r[6], 2) if r[6] else None,
        )
        for r in rows
    ]


@router.get("/areas/{area_name}/history", response_model=AreaHistory)
async def area_history(area_name: str, from_year: int = Query(2008, ge=1990, le=2100)):
    """Yearly sale and rent history for one area.

    Three deliberate choices:

    **Median, not mean.** `PERCENTILE_CONT(0.5)` throughout. Dubai property prices are
    heavily right-skewed -- one area carries a single 6.75 bn transaction -- and a mean
    per year would be a chart of outliers.

    **Rent divided by `no_of_prop`.** `annual_amount` is the CONTRACT total, and one
    contract can cover hundreds of properties, each getting its own row carrying the full
    portfolio amount. Charting the raw column shows a market where rent exceeds sale price.

    **Partial periods flagged, not hidden.** The current year is incomplete -- data ends
    mid-February -- so its counts sit far below a full year and read as a market collapse.
    Rather than silently dropping it (which hides the most recent data) or plotting it
    unmarked (which lies), `is_partial` is computed by comparing the period end against the
    last date actually present, and the client renders it distinctly.
    """
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
                WITH bounds AS (
                    SELECT MAX(instance_date)::date AS last_sale,
                           (SELECT MAX(contract_start_date) FROM raw_rent_contracts) AS last_rent
                      FROM raw_transactions
                ), sales AS (
                    SELECT EXTRACT(YEAR FROM instance_date)::int AS yr,
                           COUNT(*) AS n,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (
                               ORDER BY meter_sale_price) FILTER (WHERE meter_sale_price > 0
                           ) AS med_sqm,
                           PERCENTILE_CONT(0.5) WITHIN GROUP (
                               ORDER BY actual_worth) FILTER (WHERE actual_worth > 0
                           ) AS med_price
                      FROM raw_transactions
                     WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
                       AND instance_date IS NOT NULL
                     GROUP BY 1
                ), rents AS (
                    SELECT EXTRACT(YEAR FROM contract_start_date)::int AS yr,
                           COUNT(*) AS n,
                           -- per PROPERTY, not per contract; see the docstring
                           PERCENTILE_CONT(0.5) WITHIN GROUP (
                               ORDER BY annual_amount / NULLIF(no_of_prop, 0)
                           ) FILTER (WHERE annual_amount > 0) AS med_rent
                      FROM raw_rent_contracts
                     WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
                       AND contract_start_date IS NOT NULL
                     GROUP BY 1
                )
                SELECT y.yr,
                       COALESCE(s.n, 0), s.med_sqm, s.med_price,
                       COALESCE(r.n, 0), r.med_rent,
                       (make_date(y.yr, 12, 31) > b.last_sale
                        AND make_date(y.yr, 1, 1) <= b.last_sale) AS partial
                  FROM (SELECT generate_series(
                            LEAST((SELECT MIN(yr) FROM sales), (SELECT MIN(yr) FROM rents)),
                            (SELECT EXTRACT(YEAR FROM last_sale)::int FROM bounds)
                        ) AS yr) y
                  CROSS JOIN bounds b
                  LEFT JOIN sales s ON s.yr = y.yr
                  LEFT JOIN rents r ON r.yr = y.yr
                 WHERE y.yr >= :from_year
                 ORDER BY y.yr
            """),
            {"area": area_name, "from_year": from_year},
        )
        points = [
            AreaHistoryPoint(
                period=str(r[0]),
                sale_count=r[1],
                median_price_sqm=round(float(r[2]), 2) if r[2] is not None else None,
                median_price=round(float(r[3]), 2) if r[3] is not None else None,
                rent_count=r[4],
                median_annual_rent=round(float(r[5]), 2) if r[5] is not None else None,
                is_partial=bool(r[6]),
            )
            for r in rows
        ]

        # Is the rent extract a history or a snapshot? Ask the data rather than assume:
        # if every contract was registered inside a single window, it is a snapshot.
        reg = (
            await conn.execute(
                text("""
                    SELECT MIN(load_timestamp)::date, MAX(load_timestamp)::date,
                           COUNT(DISTINCT EXTRACT(YEAR FROM load_timestamp))
                      FROM raw_rent_contracts
                     WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
                """),
                {"area": area_name},
            )
        ).first()

    reg_from, reg_to, reg_years = (reg or (None, None, 0))
    return AreaHistory(
        area_name_en=area_name,
        interval="year",
        points=points,
        sales_are_historical=True,
        rents_are_historical=bool(reg_years and reg_years > 1),
        rent_registered_from=str(reg_from) if reg_from else None,
        rent_registered_to=str(reg_to) if reg_to else None,
    )


@router.get("/areas/{area_name}/summary", response_model=AreaSummary)
async def area_summary(area_name: str):
    """Return cross-dataset stats for a single area.

    Matching is case- and whitespace-insensitive on purpose. The two sources spell
    the same place differently: the DLD transaction CSV has `Al Manara`, while the
    community polygons parsed out of Community.kml have `AL MANARA`. An exact match
    here returned HTTP 200 with every count set to 0 -- indistinguishable from a real
    area that genuinely has no transactions -- so the map's boundary layer opened a
    detail panel full of nothing and reported no error anywhere.

    Note this still cannot distinguish "area exists, no data" from "no such area";
    both are zeros. Normalising the comparison removes the case trap, not that one.
    """
    async with engine.connect() as conn:
        tx = await conn.execute(
            text("""
                SELECT COUNT(*), AVG(actual_worth), MIN(actual_worth),
                       MAX(actual_worth), AVG(procedure_area)
                FROM raw_transactions
                WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
            """),
            {"area": area_name},
        )
        tx_row = tx.fetchone()

        rent = await conn.execute(
            text("""
                SELECT COUNT(*), AVG(annual_amount), MIN(annual_amount),
                       MAX(annual_amount), AVG(actual_area)
                FROM raw_rent_contracts
                WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
            """),
            {"area": area_name},
        )
        rent_row = rent.fetchone()

        val = await conn.execute(
            text("""
                SELECT COUNT(*), AVG(actual_worth), MIN(actual_worth),
                       MAX(actual_worth), AVG(procedure_area)
                FROM raw_valuations
                WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
            """),
            {"area": area_name},
        )
        val_row = val.fetchone()

    def make_stats(row):
        return AreaDatasetStats(
            count=row[0],
            avg_price=round(row[1], 2) if row[1] else None,
            min_price=round(row[2], 2) if row[2] else None,
            max_price=round(row[3], 2) if row[3] else None,
            avg_area_sqm=round(row[4], 2) if row[4] else None,
        )

    return AreaSummary(
        area_name_en=area_name,
        transactions=make_stats(tx_row),
        rents=make_stats(rent_row),
        valuations=make_stats(val_row),
    )
