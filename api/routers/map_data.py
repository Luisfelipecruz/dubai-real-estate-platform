"""Map data endpoint: area-aggregated transactions with coordinates for visualization.

Coordinates come from PostGIS: each area is joined to its community polygon
(loaded from the DLD Community.kml export by scripts/load_communities.py) and the
point is derived with ST_Centroid.

This replaced a hardcoded AREA_COORDS dictionary of 70 hand-typed approximate
centroids, which had two bugs worth remembering: Marsa Dubai and Dubai Marina
resolved to the identical point, as did Burj Khalifa and Downtown Dubai, so those
areas stacked on top of each other on the map. Coverage went from 70 hand-listed
areas to 222 real polygons.
"""

from fastapi import APIRouter
from sqlalchemy import text

from database import engine

router = APIRouter()


@router.get("/map/transactions")
async def get_map_transactions(
    trans_group: str | None = None,
    property_type: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
):
    """Return area-aggregated transaction data with coordinates for map visualization."""
    conditions = []
    params: dict = {}

    if trans_group:
        conditions.append("trans_group_en = :trans_group")
        params["trans_group"] = trans_group
    if property_type:
        conditions.append("property_type_en = :property_type")
        params["property_type"] = property_type
    if year_from:
        conditions.append("EXTRACT(YEAR FROM instance_date) >= :year_from")
        params["year_from"] = year_from
    if year_to:
        conditions.append("EXTRACT(YEAR FROM instance_date) <= :year_to")
        params["year_to"] = year_to

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Aggregate first, then join the 222-row polygon table — joining before the
    # GROUP BY would drag the geometry through the aggregation for every row.
    async with engine.connect() as conn:
        rows = await conn.execute(text(f"""
            WITH agg AS (
                SELECT
                    area_name_en,
                    area_id,
                    trans_group_en,
                    COUNT(*) AS transaction_count,
                    AVG(actual_worth) AS avg_amount,
                    SUM(actual_worth) AS total_volume,
                    AVG(meter_sale_price) AS avg_price_sqm,
                    MIN(instance_date) AS earliest_date,
                    MAX(instance_date) AS latest_date
                FROM raw_transactions
                {where}
                GROUP BY area_name_en, area_id, trans_group_en
            )
            SELECT
                a.area_name_en,
                a.area_id,
                a.trans_group_en,
                a.transaction_count,
                a.avg_amount,
                a.total_volume,
                a.avg_price_sqm,
                a.earliest_date,
                a.latest_date,
                ST_Y(ST_Centroid(c.geom)) AS latitude,
                ST_X(ST_Centroid(c.geom)) AS longitude
            FROM agg a
            JOIN communities c
              ON UPPER(TRIM(a.area_name_en)) = c.community_name_norm
            ORDER BY a.total_volume DESC
        """), params)

        features = [
            {
                "area_name": r[0],
                "area_id": r[1],
                "trans_group": r[2],
                "transaction_count": r[3],
                "avg_amount": round(float(r[4]), 2) if r[4] else 0,
                "total_volume": round(float(r[5]), 2) if r[5] else 0,
                "avg_price_sqm": round(float(r[6]), 2) if r[6] else 0,
                "earliest_date": r[7].isoformat() if r[7] else None,
                "latest_date": r[8].isoformat() if r[8] else None,
                "latitude": round(float(r[9]), 6),
                "longitude": round(float(r[10]), 6),
            }
            for r in rows.fetchall()
        ]

    return {"features": features, "total": len(features)}


@router.get("/map/filters")
async def get_map_filters():
    """Return available filter options for the map."""
    async with engine.connect() as conn:
        groups = await conn.execute(text(
            "SELECT DISTINCT trans_group_en FROM raw_transactions WHERE trans_group_en IS NOT NULL ORDER BY 1"
        ))
        types = await conn.execute(text(
            "SELECT DISTINCT property_type_en FROM raw_transactions WHERE property_type_en IS NOT NULL ORDER BY 1"
        ))
        years = await conn.execute(text(
            "SELECT MIN(EXTRACT(YEAR FROM instance_date))::int, MAX(EXTRACT(YEAR FROM instance_date))::int FROM raw_transactions WHERE instance_date IS NOT NULL"
        ))
        year_row = years.first()

    return {
        "trans_groups": [r[0] for r in groups],
        "property_types": [r[0] for r in types],
        "year_min": year_row[0] if year_row else None,
        "year_max": year_row[1] if year_row else None,
    }
