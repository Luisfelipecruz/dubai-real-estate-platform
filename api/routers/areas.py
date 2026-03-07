from fastapi import APIRouter
from sqlalchemy import text

from database import engine
from models.area import AreaOverview, AreaSummary, AreaDatasetStats

router = APIRouter()


@router.get("/areas", response_model=list[AreaOverview])
async def list_areas():
    """Return unique areas across all datasets with counts and averages."""
    query = text("""
        SELECT
            COALESCE(t.area_id, r.area_id, v.area_id) AS area_id,
            COALESCE(t.area_name_en, r.area_name_en, v.area_name_en) AS area_name_en,
            COALESCE(t.cnt, 0) AS transaction_count,
            COALESCE(r.cnt, 0) AS rent_count,
            COALESCE(v.cnt, 0) AS valuation_count,
            t.avg_price AS avg_transaction_price,
            r.avg_amount AS avg_rent_amount
        FROM
            (SELECT area_id, area_name_en, COUNT(*) AS cnt, AVG(actual_worth) AS avg_price
             FROM raw_transactions GROUP BY area_id, area_name_en) t
        FULL OUTER JOIN
            (SELECT area_id, area_name_en, COUNT(*) AS cnt, AVG(annual_amount) AS avg_amount
             FROM raw_rent_contracts GROUP BY area_id, area_name_en) r
            ON t.area_name_en = r.area_name_en
        FULL OUTER JOIN
            (SELECT area_id, area_name_en, COUNT(*) AS cnt
             FROM raw_valuations GROUP BY area_id, area_name_en) v
            ON COALESCE(t.area_name_en, r.area_name_en) = v.area_name_en
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


@router.get("/areas/{area_name}/summary", response_model=AreaSummary)
async def area_summary(area_name: str):
    """Return cross-dataset stats for a single area."""
    async with engine.connect() as conn:
        tx = await conn.execute(
            text("""
                SELECT COUNT(*), AVG(actual_worth), MIN(actual_worth),
                       MAX(actual_worth), AVG(procedure_area)
                FROM raw_transactions WHERE area_name_en = :area
            """),
            {"area": area_name},
        )
        tx_row = tx.fetchone()

        rent = await conn.execute(
            text("""
                SELECT COUNT(*), AVG(annual_amount), MIN(annual_amount),
                       MAX(annual_amount), AVG(actual_area)
                FROM raw_rent_contracts WHERE area_name_en = :area
            """),
            {"area": area_name},
        )
        rent_row = rent.fetchone()

        val = await conn.execute(
            text("""
                SELECT COUNT(*), AVG(actual_worth), MIN(actual_worth),
                       MAX(actual_worth), AVG(procedure_area)
                FROM raw_valuations WHERE area_name_en = :area
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
