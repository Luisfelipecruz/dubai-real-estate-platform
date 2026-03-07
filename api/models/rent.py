from pydantic import BaseModel
from datetime import date


class RentOut(BaseModel):
    id: int
    contract_id: str
    line_number: int
    contract_start_date: date | None
    contract_end_date: date | None
    contract_reg_type_en: str | None
    contract_amount: float | None
    annual_amount: float | None
    ejari_property_type_en: str | None
    ejari_property_sub_type_en: str | None
    ejari_bus_property_type_en: str | None
    property_usage_en: str | None
    tenant_type_en: str | None
    is_free_hold: bool | None
    area_id: int | None
    area_name_en: str | None
    project_name_en: str | None
    master_project_en: str | None
    no_of_prop: int | None
    actual_area: float | None
    nearest_metro_en: str | None
    nearest_mall_en: str | None
    nearest_landmark_en: str | None


class RentListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    data: list[RentOut]
