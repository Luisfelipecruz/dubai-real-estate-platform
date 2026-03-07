from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import text

from database import engine
from models.rent import RentOut, RentListResponse

router = APIRouter()

SORT_FIELDS = {"contract_start_date", "annual_amount", "contract_amount"}
DEFAULT_SORT = "contract_start_date"


@router.get("/rents", response_model=RentListResponse)
async def list_rents(
    area_name: str | None = None,
    property_type: str | None = None,
    contract_reg_type: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
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
        conditions.append("ejari_property_type_en = :property_type")
        params["property_type"] = property_type
    if contract_reg_type:
        conditions.append("contract_reg_type_en = :contract_reg_type")
        params["contract_reg_type"] = contract_reg_type
    if min_amount is not None:
        conditions.append("annual_amount >= :min_amount")
        params["min_amount"] = min_amount
    if max_amount is not None:
        conditions.append("annual_amount <= :max_amount")
        params["max_amount"] = max_amount
    if date_from:
        conditions.append("contract_start_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("contract_start_date <= :date_to")
        params["date_to"] = date_to

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sort_col = sort_by if sort_by in SORT_FIELDS else DEFAULT_SORT
    order = "DESC" if sort_order == "desc" else "ASC"

    async with engine.connect() as conn:
        count_row = await conn.execute(
            text(f"SELECT COUNT(*) FROM raw_rent_contracts {where}"), params
        )
        total = count_row.scalar()

        rows = await conn.execute(
            text(
                f"SELECT id, contract_id, line_number, contract_start_date, "
                f"contract_end_date, contract_reg_type_en, contract_amount, "
                f"annual_amount, ejari_property_type_en, ejari_property_sub_type_en, "
                f"ejari_bus_property_type_en, property_usage_en, tenant_type_en, "
                f"is_free_hold, area_id, area_name_en, project_name_en, "
                f"master_project_en, no_of_prop, actual_area, nearest_metro_en, "
                f"nearest_mall_en, nearest_landmark_en "
                f"FROM raw_rent_contracts {where} "
                f"ORDER BY {sort_col} {order} NULLS LAST "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        data = [RentOut(**dict(r._mapping)) for r in rows.fetchall()]

    return RentListResponse(total=total, limit=limit, offset=offset, data=data)
