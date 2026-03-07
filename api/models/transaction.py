from pydantic import BaseModel
from datetime import date, datetime


class TransactionOut(BaseModel):
    id: int
    transaction_id: str
    instance_date: date | None
    procedure_name_en: str | None
    trans_group_en: str | None
    property_type_en: str | None
    property_sub_type_en: str | None
    property_usage_en: str | None
    reg_type_en: str | None
    area_id: int | None
    area_name_en: str | None
    building_name_en: str | None
    project_name_en: str | None
    master_project_en: str | None
    rooms_en: str | None
    procedure_area: float | None
    actual_worth: float | None
    meter_sale_price: float | None
    meter_rent_price: float | None
    has_parking: bool | None
    nearest_metro_en: str | None
    nearest_mall_en: str | None
    nearest_landmark_en: str | None


class TransactionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    data: list[TransactionOut]
