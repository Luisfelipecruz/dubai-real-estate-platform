from pydantic import BaseModel


class AreaOverview(BaseModel):
    area_id: int | None
    area_name_en: str
    transaction_count: int
    rent_count: int
    valuation_count: int
    avg_transaction_price: float | None
    avg_rent_amount: float | None


class AreaSummary(BaseModel):
    area_name_en: str
    transactions: "AreaDatasetStats"
    rents: "AreaDatasetStats"
    valuations: "AreaDatasetStats"


class AreaDatasetStats(BaseModel):
    count: int
    avg_price: float | None
    min_price: float | None
    max_price: float | None
    avg_area_sqm: float | None
