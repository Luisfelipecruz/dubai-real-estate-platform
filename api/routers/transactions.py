from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import text

from database import engine
from models.transaction import TransactionOut, TransactionListResponse

router = APIRouter()

SORT_FIELDS = {"instance_date", "actual_worth", "procedure_area"}
DEFAULT_SORT = "instance_date"


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    area_name: str | None = None,
    trans_group: str | None = None,
    property_type: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    rooms: str | None = None,
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
    if trans_group:
        conditions.append("trans_group_en = :trans_group")
        params["trans_group"] = trans_group
    if property_type:
        conditions.append("property_type_en = :property_type")
        params["property_type"] = property_type
    if min_amount is not None:
        conditions.append("actual_worth >= :min_amount")
        params["min_amount"] = min_amount
    if max_amount is not None:
        conditions.append("actual_worth <= :max_amount")
        params["max_amount"] = max_amount
    if date_from:
        conditions.append("instance_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("instance_date <= :date_to")
        params["date_to"] = date_to
    if rooms:
        conditions.append("rooms_en = :rooms")
        params["rooms"] = rooms

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sort_col = sort_by if sort_by in SORT_FIELDS else DEFAULT_SORT
    order = "DESC" if sort_order == "desc" else "ASC"

    async with engine.connect() as conn:
        count_row = await conn.execute(
            text(f"SELECT COUNT(*) FROM raw_transactions {where}"), params
        )
        total = count_row.scalar()

        rows = await conn.execute(
            text(
                f"SELECT id, transaction_id, instance_date, procedure_name_en, "
                f"trans_group_en, property_type_en, property_sub_type_en, "
                f"property_usage_en, reg_type_en, area_id, area_name_en, "
                f"building_name_en, project_name_en, master_project_en, rooms_en, "
                f"procedure_area, actual_worth, meter_sale_price, meter_rent_price, "
                f"has_parking, nearest_metro_en, nearest_mall_en, nearest_landmark_en "
                f"FROM raw_transactions {where} "
                f"ORDER BY {sort_col} {order} NULLS LAST "
                f"LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        data = [TransactionOut(**dict(r._mapping)) for r in rows.fetchall()]

    return TransactionListResponse(total=total, limit=limit, offset=offset, data=data)
