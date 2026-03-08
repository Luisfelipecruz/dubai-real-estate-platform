"""Map data endpoint: area-aggregated transactions with coordinates for visualization."""

from fastapi import APIRouter, Query
from sqlalchemy import text

from database import engine

router = APIRouter()

# Approximate coordinates for major Dubai areas
# Source: Dubai Land Department area centroids
AREA_COORDS = {
    "Marsa Dubai": (25.0800, 55.1400),
    "Al Barsha South Fourth": (25.0950, 55.1900),
    "Burj Khalifa": (25.1972, 55.2744),
    "Al Merkadh": (25.2600, 55.3200),
    "Al Thanayah Fifth": (25.1150, 55.1950),
    "Madinat Al Mataar": (25.2300, 55.3500),
    "Palm Jumeirah": (25.1124, 55.1390),
    "Business Bay": (25.1860, 55.2640),
    "Dubai Marina": (25.0800, 55.1400),
    "Downtown Dubai": (25.1972, 55.2744),
    "Jumeirah Village Circle": (25.0650, 55.2100),
    "Al Barsha South Third": (25.0980, 55.2000),
    "Wadi Al Safa 5": (25.0550, 55.2400),
    "Jabal Ali First": (25.0200, 55.0700),
    "Al Hebiah Fourth": (25.0300, 55.2300),
    "Al Yelayiss 2": (25.0050, 55.1300),
    "Al Thanayah Fourth": (25.1100, 55.1900),
    "Hadaeq Sheikh Mohammed Bin Rashid": (25.0500, 55.2600),
    "Mirdif": (25.2200, 55.4200),
    "Al Warsan First": (25.1600, 55.4000),
    "Al Barsha South Second": (25.1000, 55.2050),
    "Me'Aisem First": (25.0450, 55.2000),
    "Wadi Al Safa 7": (25.0500, 55.2200),
    "Al Yufrah 2": (25.0100, 55.1600),
    "Nadd Hessa": (25.0700, 55.2400),
    "Saih Shuaib 2": (24.9500, 55.1500),
    "Al Hebiah First": (25.0400, 55.2200),
    "World Islands": (25.2200, 55.1700),
    "Oud Al Muteena First": (25.2800, 55.3900),
    "Al Thanyah First": (25.1200, 55.1800),
    "Al Jadaf": (25.2100, 55.3300),
    "Al Quoz Industrial Fourth": (25.1400, 55.2200),
    "Al Quoz Industrial First": (25.1500, 55.2100),
    "Al Warsan Second": (25.1500, 55.4100),
    "Umm Hurair Second": (25.2300, 55.3200),
    "Al Barshaa South First": (25.1020, 55.2100),
    "Dubai Investment Park First": (25.0000, 55.1500),
    "Dubai Investment Park Second": (24.9900, 55.1400),
    "Al Quoz Third": (25.1350, 55.2300),
    "Al Quoz Fourth": (25.1300, 55.2400),
    "Al Sufouh Second": (25.1100, 55.1500),
    "Al Sufouh First": (25.1050, 55.1600),
    "Jabal Ali Industrial Second": (25.0100, 55.0600),
    "Wadi Al Safa 3": (25.0600, 55.2500),
    "Al Twar First": (25.2650, 55.3700),
    "Umm Suqeim Third": (25.1300, 55.1800),
    "Al Garhoud": (25.2400, 55.3500),
    "Nad Al Sheba First": (25.1600, 55.3200),
    "Hor Al Anz": (25.2750, 55.3300),
    "Jumeirah First": (25.2100, 55.2400),
    "Al Muhaisnah Fourth": (25.2700, 55.4100),
    "Jumeirah Second": (25.2000, 55.2300),
    "Al Rashidiya": (25.2300, 55.3800),
    "Al Mamzar": (25.2900, 55.3500),
    "Al Wasl": (25.2000, 55.2600),
    "Umm Al Sheif": (25.1600, 55.2200),
    "Al Quoz First": (25.1600, 55.2000),
    "Al Quoz Second": (25.1500, 55.2200),
    "Al Karama": (25.2400, 55.3000),
    "Deira": (25.2700, 55.3200),
    "Bur Dubai": (25.2500, 55.3000),
    "Al Satwa": (25.2300, 55.2700),
    "Al Mizhar First": (25.2600, 55.4400),
    "Al Mizhar Second": (25.2500, 55.4500),
    "Al Nahda First": (25.2900, 55.3700),
    "Al Nahda Second": (25.2850, 55.3800),
    "Al Khawaneej First": (25.2700, 55.4600),
    "Al Khawaneej Second": (25.2600, 55.4700),
    "Nad Al Sheba Third": (25.1400, 55.3400),
    "Al Lisaili": (25.0500, 55.4500),
}


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

    async with engine.connect() as conn:
        rows = await conn.execute(text(f"""
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
            ORDER BY total_volume DESC
        """), params)

        features = []
        for r in rows.fetchall():
            area = r[0]
            coords = AREA_COORDS.get(area)
            if not coords:
                continue
            features.append({
                "area_name": area,
                "area_id": r[1],
                "trans_group": r[2],
                "transaction_count": r[3],
                "avg_amount": round(float(r[4]), 2) if r[4] else 0,
                "total_volume": round(float(r[5]), 2) if r[5] else 0,
                "avg_price_sqm": round(float(r[6]), 2) if r[6] else 0,
                "earliest_date": r[7].isoformat() if r[7] else None,
                "latest_date": r[8].isoformat() if r[8] else None,
                "latitude": coords[0],
                "longitude": coords[1],
            })

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
