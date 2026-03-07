from pydantic import BaseModel
from datetime import datetime


class ValuationOut(BaseModel):
    id: int
    procedure_number: int
    instance_date: datetime | None
    procedure_name_en: str | None
    procedure_year: int | None
    property_type_en: str | None
    property_sub_type_en: str | None
    area_id: int | None
    area_name_en: str | None
    procedure_area: float | None
    actual_area: float | None
    actual_worth: float | None
    property_total_value: float | None
    row_status_code: str | None


class ValuationListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    data: list[ValuationOut]
