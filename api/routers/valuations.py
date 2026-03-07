from fastapi import APIRouter, Query
from sqlalchemy import text

from database import engine
from models.valuation import ValuationOut, ValuationListResponse

router = APIRouter()

SORT_FIELDS = {"instance_date", "actual_worth", "property_total_value"}
DEFAULT_SORT = "instance_date"


@router.get("/valuations", response_model=ValuationListResponse)
async def list_valuations(
    area_name: str | None = None,
    property_type: str | None = None,
    procedure_year: int | None = None,
    min_worth: float | None = None,
    max_worth: float | None = None,
    sort_by: str = Query(DEFAULT_SORT, description="Sort field"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if area_name:
        conditions.append("area_name_en ILIKE :area_name")
        params["area_name"] = f"%{area_name}%"
    if property_type:
        conditions.append("property_type_en = :property_type")
        params["property_type"] = property_type
    if procedure_year is not None:
        conditions.append("procedure_year = :procedure_year")
        params["procedure_year"] = procedure_year
    if min_worth is not None:
        conditions.append("actual_worth >= :min_worth")
        params["min_worth"] = min_worth
    if max_worth is not None:
        conditions.append("actual_worth <= :max_worth")
        params["max_worth"] = max_worth

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sort_col = sort_by if sort_by in SORT_FIELDS else DEFAULT_SORT
    order = "DESC" if sort_order == "desc" else "ASC"

    async with engine.connect() as conn:
        count_row = await conn.execute(
            text(f"SELECT COUNT(*) FROM raw_valuations {where}"), params
        )
        total = count_row.scalar()

        rows = await conn.execute(
            text(
                f"SELECT id, procedure_number, instance_date, procedure_name_en, "
                f"procedure_year, property_type_en, property_sub_type_en, "
                f"area_id, area_name_en, procedure_area, actual_area, "
                f"actual_worth, property_total_value, row_status_code "
                f"FROM raw_valuations {where} "
                f"ORDER BY {sort_col} {order} NULLS LAST "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        data = [ValuationOut(**dict(r._mapping)) for r in rows.fetchall()]

    return ValuationListResponse(total=total, limit=limit, offset=offset, data=data)
