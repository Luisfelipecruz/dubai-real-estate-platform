"""Pydantic schemas for the spatial community endpoints."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class CommunityOut(BaseModel):
    id: int
    community_name_en: str
    community_number: str | None = None
    latitude: float = Field(..., ge=-90, le=90, description="Centroid latitude (WGS84)")
    longitude: float = Field(..., ge=-180, le=180, description="Centroid longitude (WGS84)")
    area_km2: float = Field(..., ge=0, description="Polygon area in square kilometres")


class CommunityListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    data: list[CommunityOut]


class CommunityFeatureProperties(BaseModel):
    """Feature properties. The transaction fields are null for the communities that
    no transaction area name matches — 115 of the 222, so a choropleth on this
    endpoint is legitimately holey. That is the data, not a bug in the join."""

    id: int
    community_name_en: str
    community_number: str | None = None
    area_km2: float = Field(..., ge=0)
    vertices: int = Field(..., ge=0, description="Vertex count after simplification")
    txn_area_name: str | None = Field(
        None,
        description="The transaction table's own spelling of this area, or null when no "
        "transaction area name matches. The sources disagree on case -- 'AL MANARA' in "
        "the KML vs 'Al Manara' in the DLD CSV -- so this is the value to use when "
        "drilling into the /areas endpoints.",
    )
    transaction_count: int | None = None
    avg_amount: float | None = None
    avg_price_sqm: float | None = None


class CommunityFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: int
    geometry: dict[str, Any] = Field(..., description="GeoJSON MultiPolygon, WGS84 (EPSG:4326)")
    properties: CommunityFeatureProperties


class CommunityFeatureCollection(BaseModel):
    """A real GeoJSON FeatureCollection, so deck.gl / Leaflet / QGIS can consume it directly.

    `simplify_tolerance_deg` is echoed back because the geometry is lossy by default
    and a client that renders it should be able to say by how much.
    """

    type: Literal["FeatureCollection"] = "FeatureCollection"
    simplify_tolerance_deg: float = Field(..., ge=0)
    total: int
    vertices: int = Field(..., ge=0, description="Total vertices across all features as returned")
    features: list[CommunityFeature]


class CommunityNearby(BaseModel):
    id: int
    community_name_en: str
    distance_m: float = Field(..., ge=0, description="Metres from the query point")


class CommunityNearbyResponse(BaseModel):
    center: dict[str, float]
    radius_km: float
    total: int
    data: list[CommunityNearby]


class CommunityTransactionSummary(BaseModel):
    id: int
    community_name_en: str
    transaction_count: int
    avg_amount: float
    total_volume: float


# ── polygon ↔ polygon operations ──────────────────────────────────────────
# Everything above probes the polygons with a *point*. These three take a
# polygon as the operand, which is where the DE-9IM predicates start to matter.


class CommunityNeighbor(BaseModel):
    id: int
    community_name_en: str
    shared_boundary_m: float = Field(
        ..., ge=0, description="Length of the shared boundary in metres"
    )


class CommunityNeighborsResponse(BaseModel):
    id: int
    community_name_en: str
    predicate: str = Field(..., description="touches | intersects | overlaps")
    total: int
    data: list[CommunityNeighbor]


class CommunityOverlap(BaseModel):
    a_id: int
    a_name: str
    b_id: int
    b_name: str
    relationship: str = Field(
        ..., description="disjoint | touches | overlaps | a_contains_b | b_contains_a | equal"
    )
    overlap_m2: float = Field(..., ge=0, description="Area of ST_Intersection, in real m²")
    a_area_m2: float = Field(..., ge=0)
    b_area_m2: float = Field(..., ge=0)
    overlap_pct_of_a: float = Field(..., ge=0)
    overlap_pct_of_b: float = Field(..., ge=0)


class CommunityDissolve(BaseModel):
    input_ids: list[int]
    resolved: int = Field(..., description="How many of the requested ids existed")
    parts: int = Field(..., description="Disjoint pieces in the unioned geometry")
    total_area_m2: float = Field(..., ge=0, description="Area of the ST_Union result")
    sum_of_parts_m2: float = Field(
        ..., ge=0, description="Sum of the individual areas, before the union"
    )
    overlap_area_m2: float = Field(
        ...,
        ge=0,
        description="Area double-counted by summing the parts, measured directly as "
        "ST_Union of the pairwise ST_Intersections. This is the honest number: "
        "sum_of_parts - total_area looks like it should equal it, but geodesic area "
        "of the merged boundary carries ~0.003% error, which on a 330 km² district "
        "is ~10,000 m² — larger than the real overlap, and can make the subtraction "
        "go negative. Exact unless three or more inputs overlap in one place.",
    )
    perimeter_m: float = Field(..., ge=0)
    centroid: dict[str, float]
