from pydantic import BaseModel, Field


class AreaHistoryPoint(BaseModel):
    period: str = Field(..., description="Year as 'YYYY'")
    sale_count: int
    median_price_sqm: float | None = Field(
        None, description="Median AED per m² of sold area (PERCENTILE_CONT, not AVG)"
    )
    median_price: float | None = None
    rent_count: int
    median_annual_rent: float | None = Field(
        None,
        description="Median annual rent PER PROPERTY. `annual_amount` is the CONTRACT "
        "total and one contract can cover hundreds of properties, each carrying the full "
        "portfolio amount on its own row -- so this divides by no_of_prop. Using the raw "
        "column produces gross yields above 200%.",
    )
    is_partial: bool = Field(
        False,
        description="This period extends beyond the last date present in the data, so its "
        "counts are not comparable with complete periods. Render it, but mark it.",
    )


class AreaHistory(BaseModel):
    """Sale history is a genuine time series. Rent history is NOT -- see below."""

    area_name_en: str
    interval: str
    points: list[AreaHistoryPoint]
    sales_are_historical: bool = Field(
        True, description="Transactions span many years and can be plotted as a trend."
    )
    rents_are_historical: bool = Field(
        False,
        description="FALSE for the current data. Every rent contract in the DLD portal "
        "export was REGISTERED inside one window (see rent_registered_from/to) -- it is a "
        "year-to-date snapshot of active contracts, not a history. The spread of "
        "contract_start_date makes it look like a time series and it is not: plotting rent "
        "counts by start year yields a fake 20x hockey stick, because early years hold only "
        "the few long-running contracts still active at export time. Show rents as a "
        "snapshot; do not draw a trend through them.",
    )
    rent_registered_from: str | None = None
    rent_registered_to: str | None = None


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
