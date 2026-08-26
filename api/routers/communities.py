"""Spatial endpoints over the Dubai community boundary polygons.

These are the queries that only make sense with real geometry in the database —
point-in-polygon containment and radius search — as opposed to looking a name up
in a dictionary. Both are backed by the GiST index `idx_communities_geom`;
see docs/postgis-query-plans.md for the plans with and without it.
"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from database import engine
from models.community import (
    CommunityDissolve,
    CommunityFeature,
    CommunityFeatureCollection,
    CommunityFeatureProperties,
    CommunityListResponse,
    CommunityNearby,
    CommunityNearbyResponse,
    CommunityNeighbor,
    CommunityNeighborsResponse,
    CommunityOut,
    CommunityOverlap,
    CommunityTransactionSummary,
)

router = APIRouter()

# The three DE-9IM predicates this API exposes for adjacency. Whitelisted rather
# than interpolated freely — the value reaches SQL as an identifier, not a bind
# parameter, so it must never come straight from the query string.
_ADJACENCY_PREDICATES = {
    "touches": "ST_Touches",       # boundaries meet, interiors do NOT
    "intersects": "ST_Intersects",  # any shared point at all — the loosest
    "overlaps": "ST_Overlaps",     # interiors intersect, neither contains the other
}


@router.get("/communities/geojson", response_model=CommunityFeatureCollection)
async def communities_geojson(
    simplify: float = Query(
        0.0001,
        ge=0,
        le=0.01,
        description="Douglas-Peucker tolerance in DEGREES. 0 returns full fidelity. "
        "At Dubai's latitude 0.0001 deg is about 10 m.",
    ),
    with_stats: bool = Query(True, description="Join transaction aggregates for choropleth fills"),
    name: str | None = Query(
        None,
        description="Return only the community with this name, matched case- and "
        "whitespace-insensitively. Lets a detail page fetch one polygon instead of all 222.",
    ),
):
    """The community boundaries as GeoJSON — the polygons themselves, not their centroids.

    Everything else in this API reduces geometry to a derived scalar: ST_Centroid for a
    map pin, ST_Area for a number. This is the only endpoint that returns the shape, which
    is what makes a boundary layer possible instead of a scatter of dots.

    **Why it is simplified by default.** Measured on the real table: full fidelity is
    963,041 bytes over 34,326 vertices (one polygon alone carries 2,247). At a 0.0001-degree
    tolerance that becomes 144,093 bytes over 4,900 vertices — 6.7x smaller for roughly 10 m
    of boundary error, which is well under the width of the roads these boundaries run along.

    **The caveat that matters.** ST_SimplifyPreserveTopology preserves the topology of each
    geometry *individually* — it will not self-intersect a polygon or collapse it to nothing.
    It does NOT preserve topology *between* neighbours: two polygons sharing a border are
    simplified independently, so the shared edge is decimated twice and can crack apart into
    slivers and gaps. See docs/polygon-simplification.md, which measures exactly how many of
    the 483 touching pairs survive. Rendering tolerates this; area accounting must not, which
    is why every area figure in this API comes from the unsimplified geom.
    """
    tol = float(simplify)

    stats_cte = (
        """
        stats AS (
            SELECT UPPER(TRIM(area_name_en)) AS norm,
                   -- the transaction-side spelling, carried through so a client can
                   -- drill into /areas/{name}/... without having to guess it. The two
                   -- sources disagree on case: 'AL MANARA' in the KML, 'Al Manara' in
                   -- the DLD CSV.
                   MIN(area_name_en)         AS txn_area_name,
                   COUNT(*)                  AS transaction_count,
                   AVG(actual_worth)         AS avg_amount,
                   AVG(meter_sale_price)     AS avg_price_sqm
              FROM raw_transactions
             WHERE area_name_en IS NOT NULL
             GROUP BY 1
        ),
        """
        if with_stats
        else ""
    )
    stats_join = (
        "LEFT JOIN stats s ON s.norm = c.community_name_norm" if with_stats else ""
    )
    stats_cols = (
        "s.txn_area_name, s.transaction_count, s.avg_amount, s.avg_price_sqm"
        if with_stats
        else "NULL::text AS txn_area_name, NULL::bigint AS transaction_count, "
        "NULL::numeric AS avg_amount, NULL::numeric AS avg_price_sqm"
    )

    name_filter = "WHERE c.community_name_norm = UPPER(TRIM(:name))" if name else ""
    params: dict = {"tol": tol}
    if name:
        params["name"] = name

    async with engine.connect() as conn:
        rows = await conn.execute(
            text(f"""
                WITH {stats_cte}
                shaped AS (
                    SELECT
                        c.id,
                        c.community_name_en,
                        c.community_number,
                        -- area is taken from the ORIGINAL geom on purpose: simplification
                        -- moves vertices, and reporting the area of a shape you simplified
                        -- for display would quietly corrupt every number downstream
                        ST_Area(c.geom::geography) / 1e6 AS area_km2,
                        -- The casts are load-bearing. Postgres infers a bind parameter's
                        -- type from its FIRST use, so an uncast `:tol > 0` infers integer,
                        -- 0.0001 arrives as 0, the CASE takes the ELSE branch, and you get
                        -- full-fidelity geometry back while the response still cheerfully
                        -- echoes simplify_tolerance_deg = 0.0001. It fails silently and
                        -- looks like it worked -- same shape of bug as to_date() returning
                        -- NULL on a format mismatch.
                        CASE WHEN CAST(:tol AS double precision) > 0
                             THEN ST_SimplifyPreserveTopology(
                                      c.geom, CAST(:tol AS double precision))
                             ELSE c.geom
                        END AS geom,
                        {stats_cols}
                    FROM communities c
                    {stats_join}
                    {name_filter}
                )
                SELECT
                    id,
                    community_name_en,
                    community_number,
                    area_km2,
                    ST_AsGeoJSON(geom)::json AS geometry,
                    ST_NPoints(geom)         AS vertices,
                    txn_area_name,
                    transaction_count,
                    avg_amount,
                    avg_price_sqm
                FROM shaped
                WHERE geom IS NOT NULL
                ORDER BY community_name_en
            """),
            params,
        )

        features = []
        vertices = 0
        for r in rows:
            vertices += r[5]
            features.append(
                CommunityFeature(
                    id=r[0],
                    geometry=r[4],
                    properties=CommunityFeatureProperties(
                        id=r[0],
                        community_name_en=r[1],
                        community_number=r[2],
                        area_km2=round(float(r[3]), 3),
                        vertices=r[5],
                        txn_area_name=r[6],
                        transaction_count=int(r[7]) if r[7] is not None else None,
                        avg_amount=round(float(r[8]), 2) if r[8] is not None else None,
                        avg_price_sqm=round(float(r[9]), 2) if r[9] is not None else None,
                    ),
                )
            )

    return CommunityFeatureCollection(
        simplify_tolerance_deg=tol,
        total=len(features),
        vertices=vertices,
        features=features,
    )


@router.get("/communities", response_model=CommunityListResponse)
async def list_communities(
    name: str | None = Query(None, description="Case-insensitive partial name match"),
    limit: int = Query(50, ge=1, le=250),
    offset: int = Query(0, ge=0),
):
    """List community polygons with derived centroid and area."""
    where = "WHERE community_name_en ILIKE :name" if name else ""
    params: dict = {"limit": limit, "offset": offset}
    if name:
        params["name"] = f"%{name}%"

    async with engine.connect() as conn:
        total = (
            await conn.execute(text(f"SELECT COUNT(*) FROM communities {where}"), params)
        ).scalar()

        rows = await conn.execute(
            text(f"""
                SELECT
                    id,
                    community_name_en,
                    community_number,
                    ST_Y(ST_Centroid(geom)) AS latitude,
                    ST_X(ST_Centroid(geom)) AS longitude,
                    -- cast to geography so the answer is in square metres, not
                    -- square degrees, which are meaningless as an area
                    ST_Area(geom::geography) / 1e6 AS area_km2
                FROM communities
                {where}
                ORDER BY community_name_en
                LIMIT :limit OFFSET :offset
            """),
            params,
        )

        data = [
            CommunityOut(
                id=r[0],
                community_name_en=r[1],
                community_number=r[2],
                latitude=round(float(r[3]), 6),
                longitude=round(float(r[4]), 6),
                area_km2=round(float(r[5]), 3),
            )
            for r in rows.fetchall()
        ]

    return CommunityListResponse(total=total, limit=limit, offset=offset, data=data)


@router.get("/communities/contains", response_model=CommunityOut)
async def community_containing_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Point-in-polygon: which community contains this coordinate?

    Uses ST_Contains, which the planner satisfies in two stages: the GiST index
    answers the bounding-box operator (geom ~ point) first, then the exact
    containment predicate runs only on the surviving candidates.
    """
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("""
                    SELECT
                        id,
                        community_name_en,
                        community_number,
                        ST_Y(ST_Centroid(geom)) AS latitude,
                        ST_X(ST_Centroid(geom)) AS longitude,
                        ST_Area(geom::geography) / 1e6 AS area_km2
                    FROM communities
                    WHERE ST_Contains(geom, ST_SetSRID(ST_Point(:lng, :lat), 4326))
                    LIMIT 1
                """),
                {"lat": lat, "lng": lng},
            )
        ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="No community contains that point")

    return CommunityOut(
        id=row[0],
        community_name_en=row[1],
        community_number=row[2],
        latitude=round(float(row[3]), 6),
        longitude=round(float(row[4]), 6),
        area_km2=round(float(row[5]), 3),
    )


@router.get("/communities/nearby", response_model=CommunityNearbyResponse)
async def communities_nearby(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=100),
):
    """Communities whose boundary lies within `radius_km` of a point.

    ST_DWithin on the geography type measures real metres on the spheroid.

    The ordering is subtle and was a real bug here: `geom <-> point` on the
    *geometry* type orders by planar degrees, not metres. At Dubai's latitude a
    degree of longitude is ~101 km while a degree of latitude is ~111 km, so
    degree-ordering and metre-ordering disagree — the test caught two polygons
    swapped at 1.96 km vs 1.99 km. Casting both sides to geography makes `<->`
    return true spheroid metres, and the functional index
    `idx_communities_geog` on `(geom::geography)` keeps it index-assisted.
    """
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("""
                SELECT
                    id,
                    community_name_en,
                    ST_Distance(
                        geom::geography,
                        ST_SetSRID(ST_Point(:lng, :lat), 4326)::geography
                    ) AS distance_m
                FROM communities
                WHERE ST_DWithin(
                    geom::geography,
                    ST_SetSRID(ST_Point(:lng, :lat), 4326)::geography,
                    :radius_m
                )
                ORDER BY geom::geography <-> ST_SetSRID(ST_Point(:lng, :lat), 4326)::geography
            """),
            {"lat": lat, "lng": lng, "radius_m": radius_km * 1000},
        )

        data = [
            CommunityNearby(
                id=r[0],
                community_name_en=r[1],
                distance_m=round(float(r[2]), 1),
            )
            for r in rows.fetchall()
        ]

    return CommunityNearbyResponse(
        center={"lat": lat, "lng": lng},
        radius_km=radius_km,
        total=len(data),
        data=data,
    )


@router.get("/communities/overlap", response_model=CommunityOverlap)
async def community_overlap(
    a: int = Query(..., description="First community id"),
    b: int = Query(..., description="Second community id"),
):
    """Polygon algebra: the shared area between two communities.

    `ST_Intersection` returns a *new geometry* — the shared region — rather than
    a boolean. Its area is then taken on the geography cast, because
    `ST_Area(geometry)` in SRID 4326 returns square *degrees*, which is not a
    unit of area at all. Same class of bug as ordering by `<->` on geometry.

    `relationship` names the DE-9IM case, which is the part worth knowing:
    touches (boundaries only), overlaps (interiors intersect, neither contains
    the other), contains/within, equal, or disjoint.
    """
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("""
                    SELECT
                        a.id, a.community_name_en,
                        b.id, b.community_name_en,
                        CASE
                            WHEN ST_Equals(a.geom, b.geom)      THEN 'equal'
                            WHEN ST_Contains(a.geom, b.geom)    THEN 'a_contains_b'
                            WHEN ST_Within(a.geom, b.geom)      THEN 'b_contains_a'
                            WHEN ST_Overlaps(a.geom, b.geom)    THEN 'overlaps'
                            WHEN ST_Touches(a.geom, b.geom)     THEN 'touches'
                            ELSE 'disjoint'
                        END AS relationship,
                        ST_Area(ST_Intersection(a.geom, b.geom)::geography) AS overlap_m2,
                        ST_Area(a.geom::geography) AS a_area_m2,
                        ST_Area(b.geom::geography) AS b_area_m2
                    FROM communities a, communities b
                    WHERE a.id = :a AND b.id = :b
                """),
                {"a": a, "b": b},
            )
        ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="One or both communities not found")

    overlap_m2, a_area, b_area = float(row[5]), float(row[6]), float(row[7])
    return CommunityOverlap(
        a_id=row[0],
        a_name=row[1],
        b_id=row[2],
        b_name=row[3],
        relationship=row[4],
        overlap_m2=round(overlap_m2, 2),
        a_area_m2=round(a_area, 2),
        b_area_m2=round(b_area, 2),
        overlap_pct_of_a=round(100 * overlap_m2 / a_area, 6) if a_area else 0.0,
        overlap_pct_of_b=round(100 * overlap_m2 / b_area, 6) if b_area else 0.0,
    )


@router.get("/communities/dissolve", response_model=CommunityDissolve)
async def community_dissolve(
    ids: str = Query(..., description="Comma-separated community ids, e.g. 1,2,3"),
):
    """Aggregate several polygons into one district with `ST_Union`.

    This is the "merge these areas into a reporting district" answer. `ST_Union`
    is an aggregate here: it dissolves the shared boundaries rather than just
    collecting the parts, which is what separates it from `ST_Collect`.

    `overlap_area_m2` is the interesting number: the area that summing the parts
    would have double-counted.

    It is measured *directly* — `ST_Union` of the pairwise `ST_Intersection`s —
    rather than as `sum_of_parts - total_area`, and that choice is deliberate.
    The subtraction is exact in planar terms (verified: planar diff and planar
    intersection agree to ten significant figures) but **not** on the geography
    cast, because the geodesic area of a merged boundary carries roughly 0.003%
    error. On a 330 km² district that is ~10,000 m² — an order of magnitude
    larger than the real 5,471 m² overlap, enough to drive the subtraction
    negative. Measure the overlap, do not infer it from two big numbers.
    """
    try:
        id_list = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="ids must be comma-separated integers")

    if not id_list:
        raise HTTPException(status_code=422, detail="ids must contain at least one id")
    if len(id_list) > 250:
        raise HTTPException(status_code=422, detail="at most 250 ids")

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("""
                    WITH picked AS (
                        SELECT id, geom FROM communities WHERE id = ANY(:ids)
                    ), merged AS (
                        SELECT ST_Union(geom) AS geom FROM picked
                    ), shared AS (
                        -- the double-counted region, measured rather than inferred
                        SELECT ST_Union(ST_Intersection(a.geom, b.geom)) AS geom
                          FROM picked a JOIN picked b
                            ON a.id < b.id AND ST_Overlaps(a.geom, b.geom)
                    )
                    SELECT
                        (SELECT COUNT(*) FROM picked)                          AS resolved,
                        ST_NumGeometries(ST_Multi(m.geom))                     AS parts,
                        ST_Area(m.geom::geography)                             AS total_area_m2,
                        (SELECT COALESCE(SUM(ST_Area(geom::geography)), 0)
                           FROM picked)                                        AS sum_parts_m2,
                        COALESCE(
                            (SELECT ST_Area(geom::geography) FROM shared), 0
                        )                                                      AS overlap_m2,
                        ST_Perimeter(m.geom::geography)                        AS perimeter_m,
                        ST_Y(ST_Centroid(m.geom))                              AS lat,
                        ST_X(ST_Centroid(m.geom))                              AS lng
                    FROM merged m
                    WHERE m.geom IS NOT NULL
                """),
                {"ids": id_list},
            )
        ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="None of those community ids exist")

    return CommunityDissolve(
        input_ids=id_list,
        resolved=row[0],
        parts=row[1],
        total_area_m2=round(float(row[2]), 2),
        sum_of_parts_m2=round(float(row[3]), 2),
        overlap_area_m2=round(float(row[4]), 2),
        perimeter_m=round(float(row[5]), 2),
        centroid={"lat": round(float(row[6]), 6), "lng": round(float(row[7]), 6)},
    )


@router.get(
    "/communities/{community_id}/neighbors",
    response_model=CommunityNeighborsResponse,
)
async def community_neighbors(
    community_id: int,
    predicate: str = Query(
        "touches",
        description="touches (boundaries meet) | intersects (any shared point) | "
        "overlaps (interiors intersect, neither contains the other)",
    ),
):
    """Adjacency: which communities border this one?

    A spatial **self-join** — the first query in this project where a polygon is
    the operand rather than the probe. Without an index it is O(n²): 222
    polygons is 49,284 candidate pairs, and the plan shows exactly that
    (`Rows Removed by Join Filter: 48801`, plus the 483 that matched).

    With `idx_communities_geom` the planner runs it in two stages: the GiST
    index answers the bounding-box operator `geom && a.geom` first, and the
    exact `ST_Touches` predicate refines only the survivors. See
    docs/polygon-adjacency-plans.md — including the honest finding that at this
    row count the index buys far less than the raw wall-clock suggests.

    The `predicate` choice is the DE-9IM distinction, measured on this dataset:
    483 touching pairs, 131 overlapping, 614 intersecting — and 483 + 131 = 614
    exactly, because no pair here contains or equals another.
    """
    fn = _ADJACENCY_PREDICATES.get(predicate.lower())
    if fn is None:
        raise HTTPException(
            status_code=422,
            detail=f"predicate must be one of {sorted(_ADJACENCY_PREDICATES)}",
        )

    async with engine.connect() as conn:
        origin = (
            await conn.execute(
                text("SELECT id, community_name_en FROM communities WHERE id = :id"),
                {"id": community_id},
            )
        ).first()

        if origin is None:
            raise HTTPException(status_code=404, detail="Community not found")

        rows = await conn.execute(
            text(f"""
                SELECT
                    b.id,
                    b.community_name_en,
                    -- the shared boundary is a LINE, so its length is what has
                    -- meaning here, not an area; geography again for metres
                    ST_Length(ST_Intersection(a.geom, b.geom)::geography) AS shared_m
                FROM communities a
                JOIN communities b
                  ON a.id <> b.id
                 AND {fn}(a.geom, b.geom)
                WHERE a.id = :id
                ORDER BY shared_m DESC, b.community_name_en
            """),
            {"id": community_id},
        )

        data = [
            CommunityNeighbor(
                id=r[0],
                community_name_en=r[1],
                shared_boundary_m=round(float(r[2] or 0.0), 2),
            )
            for r in rows.fetchall()
        ]

    return CommunityNeighborsResponse(
        id=origin[0],
        community_name_en=origin[1],
        predicate=predicate.lower(),
        total=len(data),
        data=data,
    )


@router.get(
    "/communities/{community_id}/transactions",
    response_model=CommunityTransactionSummary,
)
async def community_transactions(community_id: int):
    """Transaction summary for the area matching this community polygon."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("""
                    SELECT
                        c.id,
                        c.community_name_en,
                        COUNT(t.id) AS transaction_count,
                        AVG(t.actual_worth) AS avg_amount,
                        SUM(t.actual_worth) AS total_volume
                    FROM communities c
                    LEFT JOIN raw_transactions t
                      ON UPPER(TRIM(t.area_name_en)) = c.community_name_norm
                    WHERE c.id = :community_id
                    GROUP BY c.id, c.community_name_en
                """),
                {"community_id": community_id},
            )
        ).first()

    if row is None:
        raise HTTPException(status_code=404, detail="Community not found")

    return CommunityTransactionSummary(
        id=row[0],
        community_name_en=row[1],
        transaction_count=row[2],
        avg_amount=round(float(row[3]), 2) if row[3] else 0.0,
        total_volume=round(float(row[4]), 2) if row[4] else 0.0,
    )
